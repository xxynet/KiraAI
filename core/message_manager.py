import asyncio
import json
import time
from asyncio import Lock
import xml.etree.ElementTree as ET
from typing import Union, Any, List, Optional
from pathlib import Path
from asyncio import Semaphore
import random
import os

from core.logging_manager import get_logger
from core.utils.common_utils import image_to_base64
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
    File,
    Video
)

from core.llm_client import LLMClient
from core.chat.session_manager import SessionManager
from .prompt_manager import PromptManager
from .adapter import AdapterManager
from .provider import ProviderManager, LLMRequest, LLMResponse
from core.plugin.plugin_handlers import event_handler_reg, EventType
from core.agent.agent_executor import AgentExecutor, AgentExecutionContext, NewMemory
from core.agent.tool import ToolSet
from core.tag import tag_registry, TagSet

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
    """Cache image/sticker VLM descriptions using MD5 hash to avoid duplicate requests"""

    _instance: Optional["ImageDescCache"] = None

    def __new__(cls, cache_file: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, cache_file: str = None):
        if self._initialized:
            return
        self._initialized = True
        if cache_file is None:
            cache_file = str(get_data_path() / "image_desc_cache.json")
        self.cache_file = cache_file
        self._cache: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._cache = {}

    def _save(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def get(self, md5: str) -> Optional[str]:
        entry = self._cache.get(md5)
        if entry:
            entry["count"] += 1
            entry["last_seen"] = int(time.time())
            self._save()
            return entry["description"]
        return None

    def set(self, md5: str, description: str):
        self._cache[md5] = {
            "description": description,
            "count": 1,
            "last_seen": int(time.time())
        }
        self._save()


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""

    def __init__(self,
                 kira_config,
                 llm_api: LLMClient,
                 provider_manager: ProviderManager,
                 adapter_manager: AdapterManager,
                 memory_manager: SessionManager,
                 prompt_manager: PromptManager,
                 max_concurrent_messages: int = 3):
        self.kira_config = kira_config
        self.bot_config = kira_config["bot_config"].get("bot")
        self.max_message_interval = float(self.bot_config.get("max_message_interval"))
        self.max_buffer_messages = int(self.bot_config.get("max_buffer_messages"))
        self.min_message_delay = float(self.bot_config.get("min_message_delay", "0.8"))
        self.max_message_delay = float(self.bot_config.get("max_message_delay", "1.5"))

        self.llm_api = llm_api

        self.message_processing_semaphore = Semaphore(max_concurrent_messages)

        # managers
        self.memory_manager = memory_manager
        self.prompt_manager = prompt_manager
        self.provider_mgr = provider_manager
        self.adapter_mgr = adapter_manager

        # message buffer
        self.session_locks: dict[str, asyncio.Lock] = {}

        self.session_buffer = SessionBufferManager(max_count=self.max_buffer_messages)

        # image description cache
        self.image_desc_cache = ImageDescCache()

        logger.info("MessageProcessor initialized")

    def get_session_lock(self, sid: str) -> Lock:
        """get session lock to avoid sending message simultaneously"""
        if sid not in self.session_locks:
            self.session_locks[sid] = asyncio.Lock()
        return self.session_locks[sid]

    def get_session_list_prompt(self) -> str:
        session_list_prompt = ""
        _chat_memory = self.memory_manager.chat_memory
        for session_id in _chat_memory:
            session_list_prompt += f"{session_id}\n"
        return session_list_prompt

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
        await self.handle_im_batch_message(batch_msg)
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
                try:
                    md5 = await ele.hash_image()
                    cached_desc = self.image_desc_cache.get(md5)
                except (ValueError, Exception) as e:
                    logger.warning(f"Failed to hash image: {e}")
                    md5 = None
                    cached_desc = None
                if cached_desc:
                    img_desc = cached_desc
                else:
                    image_base64 = await ele.to_base64()
                    img_desc = await self.llm_api.desc_img(image_base64, is_base64=True)
                    if md5:
                        self.image_desc_cache.set(md5, img_desc)
                ele.caption = img_desc
                message_str += f"[Image {img_desc}]"
            elif isinstance(ele, Sticker):
                try:
                    md5 = await ele.hash_image()
                    cached_desc = self.image_desc_cache.get(md5)
                except (ValueError, Exception) as e:
                    logger.warning(f"Failed to hash sticker: {e}")
                    md5 = None
                    cached_desc = None
                if cached_desc:
                    sticker_desc = cached_desc
                else:
                    sticker_base64 = await ele.to_base64()
                    sticker_desc = await self.llm_api.desc_img(sticker_base64, is_base64=True)
                    if md5:
                        self.image_desc_cache.set(md5, sticker_desc)
                ele.caption = sticker_desc
                message_str += f"[Sticker {sticker_desc}]"
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
        logger.info(event.get_log_info())

        # decorating event info

        sid = event.session.sid

        event.session.session_description = self.memory_manager.get_session_info(sid).session_description

        # EventType.ON_IM_MESSAGE
        im_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_MESSAGE)
        for handler in im_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
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
            await self.handle_im_batch_message(batch_msg)
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
                logger.info("Event stopped")
                return

        # Get existing session
        session_list = self.get_session_list_prompt()

        # Set session title
        if not self.memory_manager.get_session_info(sid).session_title:
            self.memory_manager.update_session_info(sid, event.session.session_title)
        session_title = self.memory_manager.get_session_info(sid).session_title

        # Build chat environment
        chat_env = {
            "platform": event.adapter.platform,
            "adapter": event.adapter.name,
            "chat_type": 'GroupMessage' if event.is_group_message() else 'DirectMessage',
            "self_id": event.self_id,
            "session_title": session_title,
            "session_description": event.session.session_description,
            "session_list": session_list
        }

        # Get chat history memory
        session_memory = self.memory_manager.fetch_memory(sid)

        # Generate agent prompt
        agent_prompt_list = self.prompt_manager.get_agent_prompt(chat_env)

        # Get default LLM model client
        llm_model = self.provider_mgr.get_default_llm()
        if not llm_model:
            llm_logger.error(f"Default LLM model not set, please set it in Configuration")
            return

        request = LLMRequest(messages=session_memory[:], tools=self.llm_api.tools_definitions, tool_funcs=self.llm_api.tools_functions, tool_set=ToolSet())
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
                logger.info("Event stopped while llm request stage")
                return

        # Register persistent tags registered by user plugins
        tag_set.register(*tag_registry.get_all())

        # Assemble messages
        for sp in request.system_prompt:
            if sp.name == "format":
                sp.content = sp.content.replace("<|message_types|>", tag_set.to_prompt())
                break
        request.assemble_prompt()

        # TODO: migrate tools & tool_func params to tool_set
        request.tools.extend(request.tool_set.to_list())

        # Print user message info
        user_message = "".join(p.to_string() for p in request.user_prompt if isinstance(p, Prompt))
        logger.info(f"processing message(s) from {sid}:\n{user_message}")

        # 把收到的消息放到新收到的消息内容中
        new_memory = NewMemory()
        new_memory.user(user_message)

        # Get max tool loop config, defaults to 2 if not a valid integer
        max_tool_loop = self.kira_config.get_config("bot_config.agent.max_tool_loop")
        try:
            max_tool_loop = int(max_tool_loop)
        except ValueError:
            max_tool_loop = 2

        max_agent_steps = max_tool_loop + 1

        agent_executor = AgentExecutor(self.llm_api, request.tool_set)
        agent_ctx = AgentExecutionContext(
            event=event,
            request=request,
            llm_model=llm_model,
            new_memory=new_memory,
        )

        async def send_llm_text(resp: LLMResponse):
            text = resp.text_response
            session_lock = self.get_session_lock(sid)
            async with session_lock:
                message_results = await self.send_xml_messages(event, text.strip(), tag_set)
                if message_results is None:
                    return
                response_with_ids = self._add_message_ids(text, message_results)
                step_result = KiraStepResult(message_results=message_results, raw_output=response_with_ids)
                # EventType.ON_STEP_RESULT
                step_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_STEP_RESULT)
                for step_handler in step_handlers:
                    await step_handler.exec_handler(event, step_result)
                    if event.is_stopped:
                        logger.info("Event stopped while ON_STEP_RESULT stage")
                        return
                logger.info(f"LLM -> {sid}: {step_result.raw_output}")
                llm_resp.text_response = step_result.raw_output

                for idx in range(-1, -len(new_memory.memory_list), -1):
                    if new_memory.memory_list[idx]["role"] == "assistant":
                        new_memory.memory_list[idx]["content"] = step_result.raw_output
                        request.messages[idx]["content"] = step_result.raw_output
                        break

        # Iter agent executor to get LLMResponse
        # TODO use llm_semaphore to restrict concurrent LLM requests
        async for step in agent_executor.run(agent_ctx, max_steps=max_agent_steps):
            llm_resp = step.llm_response
            if not llm_resp:
                break

            if llm_resp.text_response:
                await send_llm_text(llm_resp)

            if not step.has_tool_calls or step.is_final:
                break

            # Process tool calls if existed

        # Save new memory
        self.memory_manager.update_memory(sid, new_memory.memory_list)

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

        cmt_prompt = self.prompt_manager.get_comment_prompt(cmt_content)

        client = self.provider_mgr.get_default_llm()
        if not client:
            llm_logger.error(f"Default LLM model not set, please set it in Configuration")
            return

        llm_req = LLMRequest(messages=[{"role": "user", "content": cmt_prompt}])

        llm_resp = await client.chat(llm_req)

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
            message_chains = await self._parse_xml_msg(xml_data, tag_set)

            # EventType.AFTER_XML_PARSE
            llm_handlers = event_handler_reg.get_handlers(event_type=EventType.AFTER_XML_PARSE)
            for handler in llm_handlers:
                await handler.exec_handler(event, message_chains)
                if event.is_stopped:
                    logger.info("Event stopped while AFTER_XML_PARSE stage")
                    return None
        except Exception as e:
            logger.error(f"Error parsing message: {str(e)}")
            return []

        for message_chain in message_chains:
            if not message_chain.is_empty():
                result = await self.send_message_chain(event.sid, message_chain)
                if not result.ok and result.err:
                    logger.error(result.err)
                message_results.append(result)

                # add random message delay
                await asyncio.sleep(random.uniform(self.min_message_delay, self.max_message_delay))
            else:
                message_results.append(KiraIMSentResult(ok=False, err="Blank message list detected"))
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
    async def _parse_xml_msg(xml_data, tag_set: TagSet) -> list[MessageChain]:
        """Parse xml to list[MessageChain]"""
        root = ET.fromstring(f"<root>{xml_data}</root>")
        message_chains = []

        for msg in root.findall("msg"):
            message_elements = []
            for child in msg:
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
                message_chains.append(MessageChain(message_elements))

        return message_chains

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
