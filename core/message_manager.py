import asyncio
import json
import time
from asyncio import Lock
import xml.etree.ElementTree as ET
from typing import Union, Any, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.event_bus import EventBus
from pathlib import Path
from asyncio import Semaphore
import random
import os

from core.logging_manager import get_logger
from core.utils.common_utils import desc_img
from core.utils.path_utils import get_data_path
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraCommentEvent, MessageChain
from core.chat.message_utils import KiraIMSentResult, KiraStepResult
from core.prompt_manager import Prompt

from core.chat.message_elements import (
    BaseMessageElement,
    Text,
    Image,
    At,
    Reply,
    Forward,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke,
    Json,
    File,
    Video
)

from core.llm_client import LLMClient
from core.chat.session_manager import SessionManager
from .prompt_manager import PromptManager
from .adapter import AdapterManager
from .agent.skills_mgr import SkillsManager
from .agent.mcp_mgr import MCPManager
from .provider import ProviderManager, LLMRequest, LLMResponse
from core.plugin.plugin_handlers import event_handler_reg, EventType
from core.agent.agent_executor import AgentExecutor, AgentExecutionContext
from core.agent.message import OpenAIMessage
from core.tag import tag_registry, TagSet, BaseTag, RootTagAction
from core.db.service import DatabaseService

from core.provider import LLMModelClient


logger = get_logger("message", "cyan")
llm_logger = get_logger("llm", "purple")


class SessionBuffer:
    def __init__(self, max_count: int = None):
        self.buffer: list = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.max_count = max_count

    def add(self, message: KiraMessageEvent):
        self.buffer.append(message)

    def pop(self, count: int = 1):
        if self.get_length() < count:
            popped = self.buffer[:]
            self.buffer.clear()
            return popped
        popped = self.buffer[:count]
        del self.buffer[:count]
        return popped

    def flush(self, count: int = None):
        if count and count <= len(self.buffer):
            pending_messages = self.buffer[:count]
            del self.buffer[:count]
        else:
            pending_messages = self.buffer[:]
            self.buffer.clear()
        return pending_messages

    def get_length(self):
        return len(self.buffer)

    def get_buffer_lock(self) -> Lock:
        """get buffer lock"""
        return self.lock


class SessionBufferManager:
    def __init__(self, max_count: int = None):
        self.buffers: dict[str, SessionBuffer] = {}
        self.max_count = max_count

    def get_buffer(self, session: str):
        if session not in self.buffers:
            self.buffers[session] = SessionBuffer(self.max_count)
        return self.buffers[session]


class ImageDescCache:
    """Cache image/sticker VLM descriptions using MD5 hash backed by database."""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service

    async def get(self, md5: str) -> Optional[str]:
        entry = await self.db.get_image_desc_cache(md5)
        if entry:
            await self.db.update_image_desc_cache(
                md5,
                count=entry["count"] + 1,
                last_seen=int(time.time()),
            )
            return entry["description"]
        return None

    async def set(self, md5: str, description: str):
        # Never cache an empty/failed description: an empty string would otherwise be
        # stored permanently as the caption for this md5 and served to every later hit.
        if not description:
            return
        existing = await self.db.get_image_desc_cache(md5)
        if existing:
            # Preserve the accumulated hit count that cleanup relies on; resetting it to 1
            # on every update would prevent frequently-seen entries from being retained.
            await self.db.update_image_desc_cache(
                md5,
                description=description,
                count=existing["count"],
                last_seen=int(time.time()),
            )
        else:
            await self.db.add_image_desc_cache(
                md5,
                description,
                count=1,
                last_seen=int(time.time()),
            )


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""

    def __init__(self,
                 db: DatabaseService,
                 kira_config,
                 llm_api: LLMClient,
                 provider_manager: ProviderManager,
                 skills_manager: SkillsManager,
                 adapter_manager: AdapterManager,
                 session_manager: SessionManager,
                 prompt_manager: PromptManager,
                 mcp_manager: MCPManager,
                 max_concurrent_messages: int = 3):
        self.db = db
        self.kira_config = kira_config
        self.bot_config = kira_config["bot_config"].get("bot")
        self.max_message_interval = float(self.bot_config.get("max_message_interval"))
        self.max_buffer_messages = int(self.bot_config.get("max_buffer_messages"))
        self.min_message_delay = float(self.bot_config.get("min_message_delay", "0.8"))
        self.max_message_delay = float(self.bot_config.get("max_message_delay", "1.5"))

        self.llm_api = llm_api
        self.event_bus: Optional[EventBus] = None

        self.message_processing_semaphore = Semaphore(max_concurrent_messages)

        # managers
        self.session_manager = session_manager
        self.prompt_manager = prompt_manager
        self.provider_mgr = provider_manager
        self.adapter_mgr = adapter_manager
        self.skills_manager = skills_manager
        self.mcp_manager = mcp_manager

        # message buffer
        self.session_locks: dict[str, asyncio.Lock] = {}

        self.session_buffer = SessionBufferManager(max_count=self.max_buffer_messages)

        # image description cache
        self.image_desc_cache = ImageDescCache(db)

        logger.info("MessageProcessor initialized")

    def get_session_lock(self, sid: str) -> Lock:
        """get session lock to avoid sending message simultaneously"""
        if sid not in self.session_locks:
            self.session_locks[sid] = asyncio.Lock()
        return self.session_locks[sid]

    def get_session_buffer_length(self, sid: str) -> int:
        buffer = self.session_buffer.get_buffer(sid)
        return buffer.get_length()

    async def pop_session_messages(self, sid: str, count: int = 1):
        buffer = self.session_buffer.get_buffer(sid)
        buffer.pop(count)

    async def flush_session_messages(self, sid: str, extra_event: KiraMessageEvent | None = None) -> bool:
        buffer = self.session_buffer.get_buffer(sid)
        async with buffer.lock:
            if extra_event is not None:
                buffer.add(extra_event)
            pending_messages: list[KiraMessageEvent] = buffer.flush()
        if not pending_messages:
            return False
        last_event = pending_messages[-1]
        batch_msg = KiraMessageBatchEvent(
            message_types=last_event.message_types,
            timestamp=int(time.time()),
            adapter=last_event.adapter,
            session=last_event.session,
            messages=[m.message for m in pending_messages]
        )
        await self.event_bus.publish(batch_msg)
        return True

    async def message_format_to_text(self, message_chain: MessageChain):
        """将平台使用标准消息格式封装的消息转换为LLM可以接收的字符串"""
        message_str = ""
        for ele in message_chain:
            if isinstance(ele, Text):
                message_str += ele.text
            elif isinstance(ele, Emoji):
                if ele.emoji_desc:
                    message_str += f"[Emoji {ele.emoji_desc} (ID: {ele.emoji_id})]"
                else:
                    message_str += f"[Emoji {ele.emoji_id}]"
            elif isinstance(ele, At):
                if ele.nickname:
                    message_str += f"[At {ele.pid}(nickname: {ele.nickname})]"
                else:
                    message_str += f"[At {ele.pid}]"
            elif isinstance(ele, Image):
                if ele.caption is None:
                    try:
                        md5 = await ele.hash_image()
                        cached_desc = await self.image_desc_cache.get(md5)
                    except (ValueError, Exception) as e:
                        logger.warning(f"Failed to hash image: {e}")
                        md5 = None
                        cached_desc = None
                    if cached_desc:
                        img_desc = cached_desc
                    else:
                        try:
                            vlm_model = self.provider_mgr.get_default_vlm()
                            img_desc = await desc_img(client=vlm_model, image=ele)
                        except Exception as e:
                            logger.error(f"Failed to get default VLM model for image description: {e}")
                            img_desc = ""

                        if md5 and img_desc:
                            try:
                                await self.image_desc_cache.set(md5, img_desc)
                            except Exception as e:
                                logger.warning(f"Failed to cache image desc: {e}")
                    ele.caption = img_desc
                else:
                    try:
                        md5 = await ele.hash_image()
                        cached = await self.image_desc_cache.get(md5)
                        if not cached:
                            await self.image_desc_cache.set(md5, ele.caption)
                    except Exception as e:
                        logger.warning(f"Failed to cache image desc: {e}")
                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()
                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)
                    message_str += f"[Image {str(ele.caption)}, file_path: {path_result}]"
                except Exception as e:
                    logger.warning(f"Failed to save image: {e}")
                    message_str += f"[Image {str(ele.caption)}]"
            elif isinstance(ele, Sticker):
                if ele.caption is None:
                    try:
                        md5 = await ele.hash_image()
                        cached_desc = await self.image_desc_cache.get(md5)
                    except (ValueError, Exception) as e:
                        logger.warning(f"Failed to hash sticker: {e}")
                        md5 = None
                        cached_desc = None
                    if cached_desc:
                        sticker_desc = cached_desc
                    else:
                        try:
                            vlm_model = self.provider_mgr.get_default_vlm()
                            sticker_desc = await desc_img(client=vlm_model, image=ele)
                        except Exception as e:
                            logger.error(f"Failed to get default VLM model for sticker description: {e}")
                            sticker_desc = ""

                        if md5 and sticker_desc:
                            try:
                                await self.image_desc_cache.set(md5, sticker_desc)
                            except Exception as e:
                                logger.warning(f"Failed to cache sticker desc: {e}")
                    ele.caption = sticker_desc
                else:
                    try:
                        md5 = await ele.hash_image()
                        cached = await self.image_desc_cache.get(md5)
                        if not cached:
                            await self.image_desc_cache.set(md5, ele.caption)
                    except Exception as e:
                        logger.warning(f"Failed to cache sticker desc: {e}")
                message_str += f"[Sticker {str(ele.caption)}]"
            elif isinstance(ele, Reply):
                if ele.chain:
                    ele.chain.message_list = [x for x in ele.chain if not isinstance(x, Reply)]
                    reply_content = await self.message_format_to_text(ele.chain)
                    message_str += f"[Reply ID: {ele.message_id} content: {reply_content}]"
                elif ele.message_content:
                    message_str += f"[Reply ID: {ele.message_id} content: {ele.message_content}]"
                else:
                    message_str += f"[Reply ID: {ele.message_id}]"
            elif isinstance(ele, Forward):
                if ele.chains:
                    forward_contents = ""
                    for i, chain in enumerate(ele.chains):
                        ele.chains[i].message_list = [x for x in chain if not isinstance(x, Forward)]
                        forward_content = await self.message_format_to_text(ele.chains[i])
                        forward_contents += f"\n{forward_content}\n"
                    message_str += f"[Forward {forward_contents.strip()}]"
            elif isinstance(ele, Record):
                record_text = await self.llm_api.speech_to_text(record=ele)
                ele.transcript = record_text
                message_str += f"[Record {record_text}]"
            elif isinstance(ele, Notice):
                message_str += f"{ele.text}"
            elif isinstance(ele, Json):
                try:
                    card_str = json.dumps(ele.data, ensure_ascii=False)
                except (TypeError, ValueError):
                    card_str = json.dumps(str(ele.data), ensure_ascii=False)
                message_str += f"[Json card {card_str}]"
            elif isinstance(ele, File):
                try:
                    file_size = int(ele.size)
                except Exception as _:
                    file_size = None

                # TODO Make it customizable
                if not file_size or file_size > 10 * 1024 * 1024:
                    message_str += f"[File name: {ele.name} (File size over 10MB, not cached)]"
                    continue

                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()

                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)

                    message_str += f"[File name: {ele.name}, file_path: {path_result}]"
                except Exception as e:
                    logger.error(f"Failed to save temp file: {e}")
            elif isinstance(ele, Video):
                try:
                    video_file_size = int(ele.size)
                except Exception as _:
                    video_file_size = None

                # TODO Make it customizable
                if not video_file_size or video_file_size > 10 * 1024 * 1024:
                    message_str += f"[Video name: {ele.name} (Video size over 10MB, not cached)]"
                    continue

                try:
                    path = Path(await ele.to_path())
                    data_dir = get_data_path()

                    try:
                        rel = path.relative_to(data_dir)
                        path_result = f"data/{rel}"
                    except ValueError:
                        path_result = str(path)

                    message_str += f"[Video name: {ele.name}, file_path: {path_result}]"
                except Exception as e:
                    logger.error(f"Failed to save temp video file: {e}")
            else:
                pass
        return message_str

    async def handle_im_message(self, event: KiraMessageEvent):
        """process im message"""

        # decorating event info

        sid = event.session.sid

        event.session.session_description = self.session_manager.get_session_info(sid).session_description

        # EventType.ON_IM_MESSAGE
        im_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_MESSAGE)
        for handler in im_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
                # Print event
                logger.info(event.get_log_info())
                return

        # Print event
        logger.info(event.get_log_info())

        # Check if message chain is valid, filter out unprocessed notice messages
        if event.message.chain.is_empty():
            return

        if event.process_strategy == "discard":
            return

        if event.process_strategy == "trigger":
            batch_msg = KiraMessageBatchEvent(
                message_types=event.message_types,
                timestamp=int(time.time()),
                adapter=event.adapter,
                session=event.session,
                messages=[event.message]
            )
            await self.event_bus.publish(batch_msg)
            return

        if event.process_strategy == "buffer":
            buffer = self.session_buffer.get_buffer(sid)
            async with buffer.lock:
                buffer.add(event)

            # EventType.ON_MESSAGE_BUFFERED
            im_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_MESSAGE_BUFFERED)
            for handler in im_handlers:
                await handler.exec_handler(event.session.sid)
            return

        if event.process_strategy == "flush":
            flushed = await self.flush_session_messages(sid, extra_event=event)
            if not flushed:
                logger.warning(f"No pending messages to flush for session {sid}")
            return

    async def handle_im_batch_message(self, event: KiraMessageBatchEvent):
        # Start processing
        sid = event.session.sid

        for i, message in enumerate(event.messages):
            # TODO Add support for multimodal image/document comprehension
            message_str = await self.message_format_to_text(message.chain)
            message.message_str = message_str

        # EventType.ON_IM_BATCH_MESSAGE
        im_batch_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_BATCH_MESSAGE)
        for handler in im_batch_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
                logger.info(f"[ON_IM_BATCH_MESSAGE] Event {event.event_id} stopped")
                return

        # Set session title
        if not self.session_manager.get_session_info(sid).session_title:
            self.session_manager.update_session_info(sid, event.session.session_title)
        session_title = self.session_manager.get_session_info(sid).session_title

        # Build chat environment
        chat_env = {
            "platform": event.adapter.platform,
            "adapter": event.adapter.name,
            "chat_type": 'GroupMessage' if event.is_group_message() else 'DirectMessage',
            "self_id": event.self_id,
            "session_title": session_title,
            "session_description": event.session.session_description
        }

        # Get chat history memory
        session_memory = self.session_manager.fetch_memory(sid)

        # Generate agent prompt
        agent_prompt_list = await self.prompt_manager.get_agent_prompt(chat_env)

        # Inject skills prompt (filtered by scope)
        allowed_skills = []
        for s in self.skills_manager.skills_info:
            if not s.enabled:
                continue
            if self.skills_manager.is_skill_allowed(s.name, sid):
                allowed_skills.append(s)
        if allowed_skills:
            for i, p in enumerate(agent_prompt_list):
                if p.name == "tools":
                    agent_prompt_list.insert(i+1, self.skills_manager.build_skills_prompt(allowed_skills))
                    break
        
        model_group: list[LLMModelClient] = []
        if event.model_group:
            model_group = [m for m in event.model_group if isinstance(m, LLMModelClient)]
        if not model_group:
            # Get default LLM model client
            try:
                default_llm = self.provider_mgr.get_default_llm()
                if not default_llm:
                    llm_logger.error(f"Default LLM model not set, please set it in Configuration")
                    return
                model_group = [default_llm]
            except Exception as _:
                llm_logger.error(f"Default LLM model not set, please set it in Configuration")
                return

        # Filter tools by scope
        tool_server_map = self.mcp_manager.get_tool_server_map()

        tool_set = self.llm_api.build_tool_set()
        # Remove tools blocked by MCP server scope
        tool_set.tools = [
            t for t in tool_set.tools
            if not (tool_server_map.get(t.name)
                    and not self.mcp_manager.is_server_allowed(tool_server_map[t.name], sid))
        ]

        request = LLMRequest(messages=session_memory[:], tool_set=tool_set)
        request.system_prompt.extend(agent_prompt_list)

        # Add received im messages
        for i, message in enumerate(event.messages):
            request.user_prompt.append(Prompt(message.message_str, name="message", source="system"))

        # Build tag set
        tag_set = TagSet()

        # EventType.ON_LLM_REQUEST
        llm_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_LLM_REQUEST)
        for handler in llm_handlers:
            await handler.exec_handler(event, request, tag_set)
            if event.is_stopped:
                logger.info(f"Event {event.event_id} stopped while llm request stage")
                return

        # Register persistent tags registered by user plugins
        tag_set.register(*tag_registry.get_all())
        tag_set.register(*tag_registry.get_all_root())

        # Assemble messages
        root_prompt = tag_set.to_root_prompt()
        for sp in request.system_prompt:
            if sp.name == "format":
                sp.content = sp.content.replace("<|message_types|>", tag_set.to_prompt())
                sp.content = sp.content.replace("<|root_tags|>",
                    f"此外，你可以在<msg>标签外使用以下控制标签（与<msg>同级）：\n{root_prompt}" if root_prompt else "")
                break
        request.assemble_prompt()

        # Re-derive tools list after plugins may have added to tool_set
        request.tools = request.tool_set.to_list()
        # Recompute tool_choice if it was auto-derived (not explicitly set by a plugin)
        if request.tool_choice in ("auto", "none"):
            request.tool_choice = "auto" if request.tools else "none"

        # Print user message info (skip persist=False prompts to avoid log spam)
        user_message = "".join(p.to_string() for p in request.user_prompt if isinstance(p, Prompt) and p.persist)
        logger.info(f"processing message(s) from {sid}:\n{user_message}")

        # 把收到的消息放到新收到的消息内容中（仅持久化 persist=True 的 Prompt）
        persist_message = "".join(p.to_string() for p in request.user_prompt if isinstance(p, Prompt) and p.persist)
        new_messages: list[OpenAIMessage] = []
        new_messages.append(OpenAIMessage(role="user", content=persist_message))

        # Get max tool loop config, defaults to 2 if not a valid integer
        # Note: This variable represents the total agent loop iterations (not just tool calls),
        # but the name is kept as-is for backward compatibility with existing config files.
        max_tool_loop = self.kira_config.get_config("bot_config.agent.max_tool_loop")
        try:
            max_tool_loop = int(max_tool_loop)
        except ValueError:
            max_tool_loop = 2

        max_agent_steps = max_tool_loop

        agent_executor = AgentExecutor(self.llm_api, request.tool_set)
        agent_ctx = AgentExecutionContext(
            event=event,
            request=request,
            new_messages=new_messages,
            model_group=model_group,
        )

        async def send_llm_text(resp: LLMResponse) -> bool:
            """Process and send LLM text response. Returns False if stopped, True to continue."""
            text = resp.text_response
            message_results = []
            raw_output = ""
            if text:
                session_lock = self.get_session_lock(sid)
                async with session_lock:
                    message_results = await self.send_xml_messages(event, text.strip(), tag_set)
                    if message_results is None:
                        return False
                    raw_output = self._add_message_ids(text, message_results)
                    logger.info(f"LLM -> {sid}: {raw_output}")
            step_result = KiraStepResult(message_results=message_results, raw_output=raw_output)
            # EventType.ON_STEP_RESULT
            step_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_STEP_RESULT)
            for step_handler in step_handlers:
                await step_handler.exec_handler(event, step_result)
                if event.is_stopped:
                    logger.info(f"Event {event.event_id} stopped while ON_STEP_RESULT stage")
                    return False
            if raw_output:
                llm_resp.text_response = step_result.raw_output
                for idx in range(-1, -len(new_messages), -1):
                    if new_messages[idx].role == "assistant":
                        new_messages[idx].content = step_result.raw_output
                        request.messages[idx].content = step_result.raw_output
                        break
            return True

        # Iter agent executor to get LLMResponse
        # TODO use llm_semaphore to restrict concurrent LLM requests
        async for step in agent_executor.run(agent_ctx, max_steps=max_agent_steps):
            llm_resp = step.llm_response
            if not llm_resp:
                break

            # Record LLM usage telemetry per step
            try:
                await self.db.add_telemetry_llm_usage(
                    timestamp=int(time.time()),
                    model=step.model_id,
                    input_tokens=llm_resp.input_tokens or 0,
                    output_tokens=llm_resp.output_tokens or 0,
                    cached_tokens=llm_resp.cached_tokens,
                    response_time_ms=int((llm_resp.time_consumed or 0) * 1000),
                    success=(step.state != "error"),
                )
            except Exception as e:
                logger.debug(f"Failed to record telemetry LLM usage: {e}")

            if not await send_llm_text(llm_resp):
                break

            if not step.has_tool_calls or step.is_final:
                break

            # Process tool calls if existed

        # Save new memory
        self.session_manager.update_memory(sid, new_messages)

    async def handle_cmt_message(self, msg: KiraCommentEvent):
        """process comment message"""

        if msg.sub_cmt_id:
            logger.info(f"[{msg.adapter_name} | {msg.sub_cmt_id}] [{msg.commenter_nickname}]: {msg.sub_cmt_content[0].text}")
            cmt_content = f"""You: {msg.cmt_content[0].text}
            {msg.commenter_nickname}: {msg.sub_cmt_content[0].text}
            """
        else:
            logger.info(f"[{msg.adapter_name} | {msg.cmt_id}] [{msg.commenter_nickname}]: {msg.cmt_content[0].text}")
            cmt_content = f"""{msg.commenter_nickname}: {msg.cmt_content[0].text}"""

        cmt_prompt = await self.prompt_manager.get_comment_prompt(cmt_content)

        client = self.provider_mgr.get_default_llm()
        if not client:
            llm_logger.error(f"Default LLM model not set, please set it in Configuration")
            return

        llm_req = LLMRequest(messages=[OpenAIMessage(role="user", content=cmt_prompt)])

        llm_resp = await client.chat(llm_req)

        try:
            await self.db.add_telemetry_llm_usage(
                timestamp=int(time.time()),
                model=client.model.model_id,
                input_tokens=llm_resp.input_tokens or 0,
                output_tokens=llm_resp.output_tokens or 0,
                cached_tokens=llm_resp.cached_tokens,
                response_time_ms=int((llm_resp.time_consumed or 0) * 1000),
                success=True,
            )
        except Exception as e:
            logger.debug(f"Failed to record telemetry LLM usage: {e}")

        response = llm_resp.text_response.strip()

        logger.info(f"LLM: {response}")

        if response:
            await self.adapter_mgr.get_adapter(msg.adapter_name).send_comment(
                text=response,
                root=msg.cmt_id,
                sub=msg.sub_cmt_id
            )
        else:
            logger.warning("Blank LLM response")

    async def send_xml_messages(self, event: KiraMessageBatchEvent, xml_data: str, tag_set: TagSet) -> Optional[List[KiraIMSentResult]]:
        """
        send message via session id & xml data
        :param event: KiraMessageBatchEvent
        :param xml_data: xml string
        :param tag_set: TagSet object
        :return: list[KiraIMSentResult]
        """
        parts = event.sid.split(":")
        if len(parts) != 3:
            raise ValueError("invalid target, must follow the form of <adapter>:<dm|gm>:<id>")

        message_results = []
        try:
            actions = await self._parse_xml_msg(xml_data, tag_set)

            # EventType.AFTER_XML_PARSE
            llm_handlers = event_handler_reg.get_handlers(event_type=EventType.AFTER_XML_PARSE)
            for handler in llm_handlers:
                await handler.exec_handler(event, actions)
                if event.is_stopped:
                    logger.info(f"Event {event.event_id} stopped while AFTER_XML_PARSE stage")
                    return None
        except Exception as e:
            logger.error(f"Error parsing message: {str(e)}")
            return []

        for action in actions:
            if isinstance(action, MessageChain):
                if not action.is_empty():
                    result = await self.send_message_chain(event.sid, action)
                    if not result.ok and result.err:
                        logger.error(result.err)
                else:
                    result = KiraIMSentResult(ok=False, err="Blank message list detected")
                message_results.append(result)
                # EventType.ON_MESSAGE_SENT
                sent_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_MESSAGE_SENT)
                for handler in sent_handlers:
                    await handler.exec_handler(event, action, result)
                    if event.is_stopped:
                        logger.info(f"Event {event.event_id} stopped while ON_MESSAGE_SENT stage")
                        return message_results
                await asyncio.sleep(random.uniform(self.min_message_delay, self.max_message_delay))
            elif isinstance(action, RootTagAction):
                try:
                    await action.tag.handle(action.value, **action.attrs)
                except Exception as e:
                    logger.error(f"Error executing root tag <{action.tag.name}>{action.value}: {e}")

        return message_results

    async def send_message_chain(self, session: str, chain: MessageChain) -> KiraIMSentResult:
        """
        Send a MessageChain to target.

        :param session: adapter_name:dm|gm:session_id
        :param chain: MessageChain instance
        :return: message_id (empty string if failed)
        """
        parts = session.split(":")
        if len(parts) != 3:
            raise ValueError("invalid target, must follow <adapter>:<dm|gm>:<id>")

        adapter_name, chat_type, pid = parts
        adapter = self.adapter_mgr.get_adapter(adapter_name)

        if chat_type == "dm":
            result = await adapter.send_direct_message(pid, chain)
        elif chat_type == "gm":
            result = await adapter.send_group_message(pid, chain)
        else:
            raise ValueError("chat_type must be 'dm' or 'gm'")

        if not result:
            return KiraIMSentResult(ok=False)

        return result

    @staticmethod
    async def _parse_xml_msg(xml_data, tag_set: TagSet) -> list[Union[MessageChain, RootTagAction]]:
        """Parse xml into an ordered list of MessageChain and RootTagAction."""
        root = ET.fromstring(f"<root>{xml_data}</root>")
        actions: list[Union[MessageChain, RootTagAction]] = []

        for element in root:
            if element.tag == "msg":
                message_elements = []
                for child in element:
                    tag = child.tag
                    value = child.text.strip() if child.text else ""
                    attrs = child.attrib

                    if tag in tag_set:
                        tag_inst = tag_set.get(name=tag)
                        tag_res = await tag_inst.handle(value, **attrs)

                        if isinstance(tag_res, BaseMessageElement):
                            message_elements.append(tag_res)
                        elif isinstance(tag_res, list):
                            message_elements.extend(tag_res)

                if message_elements:
                    actions.append(MessageChain(message_elements))
            elif element.tag in tag_set:
                root_tag = tag_set.get(name=element.tag)
                if root_tag and root_tag.parent is None:
                    value = element.text.strip() if element.text else ""
                    actions.append(RootTagAction(tag=root_tag, value=value, attrs=element.attrib))

        return actions

    @staticmethod
    def _add_message_ids(xml_data: str, message_results: List[KiraIMSentResult]) -> str:
        """为XML响应添加消息ID"""
        try:
            root = ET.fromstring(f"<root>{xml_data}</root>")

            for i, msg in enumerate(root.findall("msg")):
                if i < len(message_results):
                    message_id = message_results[i].message_id
                    if not message_id:
                        message_id = ""
                    msg.set("message_id", message_id)

            return ET.tostring(root, encoding='unicode', method='xml')[6:-7]

        except Exception as e:
            logger.error(f"Error adding message IDs: {str(e)}")
            return xml_data

    async def cleanup_image_desc_cache_task(self):
        """Background task: clean up expired image desc cache every 24 hours."""
        while True:
            try:
                deleted = await self.db.cleanup_expired_image_desc_cache()
                if deleted:
                    logger.info(f"Cleaned up {deleted} expired image desc cache entries")
                await asyncio.sleep(24 * 60 * 60)
            except asyncio.CancelledError:
                logger.info("Image desc cache cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in image desc cache cleanup: {e}")
