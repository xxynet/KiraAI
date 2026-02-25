import asyncio
import time
from asyncio import Lock
import xml.etree.ElementTree as ET
from typing import Union, Any, List
from pathlib import Path
from asyncio import Semaphore
import random
import os

from core.logging_manager import get_logger
from core.services.runtime import get_adapter_by_name
from core.utils.common_utils import image_to_base64
from core.utils.path_utils import get_data_path
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent,  KiraCommentEvent, MessageChain
from core.prompt_manager import Prompt

from core.chat.message_elements import (
    BaseMessageElement,
    Text,
    Image,
    At,
    Reply,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke,
    File
)

from core.llm_client import LLMClient
from core.chat.memory_manager import MemoryManager
from .prompt_manager import PromptManager
from .provider import ProviderManager, LLMRequest, LLMResponse
from core.plugin.plugin_handlers import event_handler_reg, EventType

logger = get_logger("message_processor", "cyan")


class SessionBuffer:
    def __init__(self, max_count: int = None):
        self.buffer: list = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.max_count = max_count

    def add(self, message: KiraMessageEvent):
        self.buffer.append(message)

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


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""

    def __init__(self,
                 kira_config,
                 llm_api: LLMClient,
                 provider_manager: ProviderManager,
                 memory_manager: MemoryManager,
                 prompt_manager: PromptManager,
                 max_concurrent_messages: int = 3):
        self.kira_config = kira_config
        self.bot_config = kira_config["bot_config"].get("bot")
        self.max_message_interval = float(self.bot_config.get("max_message_interval"))
        self.max_buffer_messages = int(self.bot_config.get("max_buffer_messages"))
        self.min_message_delay = float(self.bot_config.get("min_message_delay", "0.8"))
        self.max_message_delay = float(self.bot_config.get("max_message_delay", "1.5"))

        self.llm_api = llm_api
        self.provider_mgr = provider_manager

        self.message_processing_semaphore = Semaphore(max_concurrent_messages)

        # managers
        self.memory_manager = memory_manager
        self.prompt_manager = prompt_manager

        # message buffer
        self.session_locks: dict[str, asyncio.Lock] = {}

        self.session_buffer = SessionBufferManager(max_count=self.max_buffer_messages)

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

    async def message_format_to_text(self, message_list: list[BaseMessageElement]):
        """将平台使用标准消息格式封装的消息转换为LLM可以接收的字符串"""
        message_str = ""
        for ele in message_list:
            if isinstance(ele, Text):
                message_str += ele.text
            elif isinstance(ele, Emoji):
                message_str += f"[Emoji {ele.emoji_id}]"
            elif isinstance(ele, At):
                if ele.nickname:
                    message_str += f"[At {ele.pid}(nickname: {ele.nickname})]"
                else:
                    message_str += f"[At {ele.pid}]"
            elif isinstance(ele, Image):
                img_desc = await self.llm_api.desc_img(ele.url)
                message_str += f"[Image {img_desc}]"
            elif isinstance(ele, Sticker):
                sticker_desc = await self.llm_api.desc_img(ele.sticker_bs64, is_base64=True)
                message_str += f"[Sticker {sticker_desc}]"
            elif isinstance(ele, Reply):
                if ele.message_content:
                    message_str += f"[Reply {ele.message_content}]"
                else:
                    message_str += f"[Reply {ele.message_id}]"
            elif isinstance(ele, Record):
                record_text = await self.llm_api.speech_to_text(ele.bs64)
                message_str += f"[Record {record_text}]"
            elif isinstance(ele, Notice):
                message_str += f"{ele.text}"
            elif isinstance(ele, File):
                # TODO parse file
                message_str += f"[File {ele.name}]"
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
                logger.info("Event stopped")
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
            return

        if event.process_strategy == "flush":
            flushed = await self.flush_session_messages(sid, extra_event=event)
            if not flushed:
                logger.warning(f"No pending messages to flush for session {sid}")
            return

        # # buffer
        # buffer = self.session_buffer.get_buffer(sid)
        #
        # async with buffer.lock:
        #     buffer.add(event)
        #     message_count = buffer.get_length()
        #
        # if message_count < self.max_buffer_messages:
        #     await asyncio.sleep(self.max_message_interval)
        #
        # if buffer.get_length() == message_count:
        #     # print("no new message coming, processing")
        #     async with buffer.lock:
        #         pending_messages: list[KiraMessageEvent] = buffer.flush(count=message_count)
        #     logger.info(f"deleted {message_count} message(s) from buffer")
        # else:
        #     # print("new message coming")
        #     return None
        #
        # last_event = pending_messages[-1]
        #
        # batch_msg = KiraMessageBatchEvent(
        #     message_types=last_event.message_types,
        #     timestamp=int(time.time()),
        #     adapter=last_event.adapter,
        #     session=last_event.session,
        #     messages=[m.message for m in pending_messages]
        # )
        # await self.handle_im_batch_message(batch_msg)

    async def handle_im_batch_message(self, event: KiraMessageBatchEvent):
        # Start processing
        sid = event.session.sid

        # formatted_messages_str = ""
        for i, message in enumerate(event.messages):
            message_list = message.chain
            message_str = await self.message_format_to_text(message_list)
            message.message_str = message_str

            # formatted_message = self.prompt_manager.format_user_message(message)
            # formatted_messages_str += f"{formatted_message}\n"
        # user_prompt = "".join([p.content for p in event.prompt])
        # logger.info(f"processing message(s) from {event.adapter.name}:\n{formatted_messages_str}")

        # EventType.ON_IM_BATCH_MESSAGE
        im_batch_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_BATCH_MESSAGE)
        for handler in im_batch_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
                return

        # user_prompt = "".join([p.content for p in event.prompt])
        # user_prompt = "废弃的 user prompt"
        # logger.info(f"processing message(s) from {sid}:\n{user_prompt}")

        # Get existing session
        session_list = self.get_session_list_prompt()

        session_title = self.memory_manager.get_session_info(sid).session_title
        if not session_title:
            session_title = event.session.session_title

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
        # Get core memory
        core_memory = self.memory_manager.get_core_memory()

        # 构建用户标识（跨 recall / profile 复用）
        user_key = f"{event.adapter.name}:{event.messages[-1].sender.user_id}"

        # Recall long-term memories (RAG)
        recalled_memories_str = ""
        # try:
        #     recalled = await self.memory_manager.recall(user_prompt, user_id=user_key, k=5)
        #
        #     # 群聊场景：额外搜索群级记忆（海马体在群聊中提取的事实存储在群 ID 下）
        #     if event.is_group_message():
        #         group_key = f"{event.adapter.name}:group:{event.session.session_id}"
        #         group_recalled = await self.memory_manager.recall(
        #             user_prompt, user_id=group_key, k=3
        #         )
        #         # 去重后合并
        #         existing_ids = {m.id for m in recalled}
        #         for gm in group_recalled:
        #             if gm.id not in existing_ids:
        #                 recalled.append(gm)
        #
        #     recalled_memories_str = self.memory_manager.format_recalled_memories(recalled)
        # except Exception:
        #     logger.error("Long-term memory recall failed")

        # Get user profile
        user_profile_str = ""
        # try:
        #     user_profile_str = self.memory_manager.get_user_profile_prompt(user_key)
        #     # Update interaction stats
        #     await self.memory_manager.update_user_interaction(
        #         user_key,
        #         platform=event.adapter.platform,
        #         nickname=event.messages[-1].sender.nickname
        #     )
        # except Exception:
        #     logger.error("User profile retrieval skipped")

        # Get emoji_dict
        emoji_dict = getattr(get_adapter_by_name(event.adapter.name), "emoji_dict", {})

        # Generate agent prompt
        agent_prompt = self.prompt_manager.get_agent_prompt(
            chat_env, core_memory, event.message_types, emoji_dict,
            recalled_memories=recalled_memories_str,
            user_profile=user_profile_str
        )
        # messages = [{"role": "system", "content": agent_prompt}]

        # session_memory.append({"role": "user", "content": user_prompt})
        # new_memory_chunk = [{"role": "user", "content": user_prompt}]
        new_memory_chunk = []
        # messages.extend(session_memory)

        # New Logic Start
        llm_model = self.provider_mgr.get_default_llm()
        if not llm_model:
            logger.error(f"Default LLM model not set, please set it in Configuration")
            return

        request = LLMRequest(messages=session_memory[:], tools=self.llm_api.tools_definitions, tool_funcs=self.llm_api.tools_functions)
        request.system_prompt.append(Prompt(agent_prompt, name="system", source="system"))

        # Add received im messages
        for i, message in enumerate(event.messages):
            request.user_prompt.append(Prompt(message.message_str, name="message", source="system"))

        # EventType.ON_LLM_REQUEST
        llm_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_LLM_REQUEST)
        for handler in llm_handlers:
            await handler.exec_handler(event, request)
            if event.is_stopped:
                return

        # Assemble messages
        request.assemble_prompt()

        # Print user message info
        user_message = "".join(p.content for p in request.user_prompt if isinstance(p, Prompt))
        logger.info(f"processing message(s) from {sid}:\n{user_message}")

        # 把收到的消息放到新收到的消息内容中
        new_memory_chunk.append(request.messages[-1])

        provider_name = llm_model.model.provider_name
        model_id = llm_model.model.model_id
        logger.info(f"Running agent using {model_id} ({provider_name})")
        # resp = await llm_model.chat(request)
        # logger.debug(resp)
        # if resp:
        #     logger.info(
        #         f"Time consumed: {resp.time_consumed}s, Input tokens: {resp.input_tokens}, output tokens: {resp.output_tokens}")

        def append_msg(msg: dict):
            new_memory_chunk.append(msg)

        def extend_msg(msg: list):
            new_memory_chunk.extend(msg)

        # Get max tool loop config, defaults to 2 if not a valid integer
        max_tool_loop = self.kira_config.get_config("bot_config.agent.max_tool_loop")
        try:
            max_tool_loop = int(max_tool_loop)
        except ValueError:
            max_tool_loop = 2

        max_agent_steps = max_tool_loop + 1

        for _ in range(max_agent_steps):
            llm_resp = await llm_model.chat(request)
            if llm_resp:

                # EventType.ON_LLM_RESPONSE
                llm_resp_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_LLM_RESPONSE)
                for handler in llm_resp_handlers:
                    await handler.exec_handler(event, llm_resp)
                    if event.is_stopped:
                        return

                if not llm_resp.tool_calls:
                    session_lock = self.get_session_lock(sid)
                    async with session_lock:
                        message_ids, actual_xml = await self.send_xml_messages(sid, llm_resp.text_response.strip())
                        response_with_ids = self._add_message_ids(actual_xml, message_ids)
                        logger.info(f"LLM: {response_with_ids}")
                    request.messages.append({"role": "assistant",
                                            "content": response_with_ids if llm_resp.text_response else ""})
                    append_msg({"role": "assistant",
                                "content": response_with_ids if llm_resp.text_response else ""})
                    break
                else:
                    if llm_resp.text_response:
                        session_lock = self.get_session_lock(sid)
                        async with session_lock:
                            message_ids, actual_xml = await self.send_xml_messages(sid, llm_resp.text_response.strip())
                            response_with_ids = self._add_message_ids(actual_xml, message_ids)
                            logger.info(f"LLM: {response_with_ids}")
                    await self.llm_api.execute_tool(llm_resp)
                    request.messages.append({"role": "assistant",
                                             "content": response_with_ids if llm_resp.text_response else "",
                                             "tool_calls": llm_resp.tool_calls})
                    append_msg({"role": "assistant",
                                "content": response_with_ids if llm_resp.text_response else "",
                                "tool_calls": llm_resp.tool_calls})
                    request.messages.extend(llm_resp.tool_results)
                    extend_msg(llm_resp.tool_results)
            else:
                request.messages.append({"role": "assistant", "content": ""})
                append_msg({"role": "assistant", "content": ""})
                break

        self.memory_manager.update_memory(sid, new_memory_chunk)
        if not self.memory_manager.get_session_info(sid).session_title:
            self.memory_manager.update_session_info(sid, event.session.session_title)

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

        llm_resp = await self.llm_api.chat([{"role": "user", "content": cmt_prompt}])

        response = llm_resp.text_response.strip()

        logger.info(f"LLM: {response}")

        if response:
            await get_adapter_by_name(msg.adapter_name).send_comment(
                text=response,
                root=msg.cmt_id,
                sub=msg.sub_cmt_id
            )
        else:
            logger.warning("Blank LLM response")

    async def send_xml_messages(self, target: str, xml: str) -> tuple[List[str], str]:
        """
        send message via session id & xml data
        :param target: adapter_name:session_type:session_id
        :param xml: xml string
        :return: (message_ids, actual_xml) - actual_xml 是实际使用的XML（可能是修复后的）
        """
        message_ids = []
        resp_list, actual_xml = await self._parse_and_generate_messages(xml)

        parts = target.split(":")
        if len(parts) != 3:
            raise ValueError("invalid target, must follow the form of <adapter>:<dm|gm>:<id>")
        adapter_name, chat_type, pid = parts[0], parts[1], parts[2]

        for message_list in resp_list:
            if message_list:
                message_obj = MessageChain(message_list)

                if chat_type == "dm":
                    message_id = await get_adapter_by_name(adapter_name).send_direct_message(pid, message_obj)
                elif chat_type == "gm":
                    message_id = await get_adapter_by_name(adapter_name).send_group_message(pid, message_obj)
                else:
                    message_id = None

                if not message_id:
                    message_id = ''
                message_ids.append(message_id)

                # add random message delay
                await asyncio.sleep(random.uniform(self.min_message_delay, self.max_message_delay))
            else:
                message_ids.append('')

        return message_ids, actual_xml

    async def _parse_xml_msg(self, xml_data):
        """Parse xml to list[list[BaseMessageElement]]"""
        root = ET.fromstring(f"<root>{xml_data}</root>")
        message_list = []

        for msg in root.findall("msg"):
            message_elements = []
            for child in msg:
                tag = child.tag
                value = child.text.strip() if child.text else ""

                # build MessageType object
                if tag == "text":
                    if value:
                        message_elements.append(Text(value))
                elif tag == "emoji":
                    message_elements.append(Emoji(value))
                elif tag == "sticker":
                    sticker_id = value
                    try:
                        sticker_path = self.prompt_manager.sticker_dict[sticker_id].get("path")
                        sticker_bs64 = await image_to_base64(f"{get_data_path()}/sticker/{sticker_path}")
                        message_elements.append(Sticker(sticker_id, sticker_bs64))
                    except Exception as e:
                        logger.error(f"error while parsing sticker: {str(e)}")
                elif tag == "at":
                    message_elements.append(At(value))
                elif tag == "img":
                    img_res = await self.llm_api.generate_img(value)
                    if img_res:
                        if img_res.url:
                            message_elements.append(Image(url=img_res.url))
                        elif img_res.base64:
                            message_elements.append(Image(base64=img_res.base64))
                        else:
                            pass
                elif tag == "reply":
                    message_elements.append(Reply(value))
                elif tag == "record":
                    try:
                        record_bs64 = await self.llm_api.text_to_speech(value)
                        message_elements.append(Record(record_bs64))
                    except Exception as e:
                        logger.error(f"an error occurred while generating voice message: {e}")
                        message_elements.append(Text(f"<record>{value}</record>"))
                elif tag == "poke":
                    message_elements.append(Poke(value))
                elif tag == "selfie":
                    try:
                        ref_img_path = self.kira_config.get('bot_config', {}).get('selfie', {}).get('path', '')
                        if os.path.exists(f"{get_data_path()}/{ref_img_path}"):
                            img_extension = ref_img_path.split(".")[-1]
                            bs64 = await image_to_base64(f"{get_data_path()}/{ref_img_path}")
                            img_res = await self.llm_api.image_to_image(value, bs64=f"data:image/{img_extension};base64,{bs64}")
                            if img_res:
                                if img_res.url:
                                    message_elements.append(Image(url=img_res.url))
                                elif img_res.base64:
                                    message_elements.append(Image(base64=img_res.base64))
                                else:
                                    logger.warning("Invalid selfie image result")
                        else:
                            logger.warning(f"Selfie reference image not found, skipped generation")
                    except Exception as e:
                        logger.error(f"Failed to generate selfie: {e}")
                elif tag == "file":
                    registered_file_path = get_data_path() / "files" / value

                    # Absolute path
                    if os.path.exists(value):
                        message_elements.append(File(value, Path(value).name))
                    # Relative path
                    elif os.path.exists(registered_file_path):
                        message_elements.append(File(str(registered_file_path), value))
                    # File URL
                    elif value.startswith(("http://", "https://")):
                        # TODO fetch filename from http headers
                        message_elements.append(File(value))
                else:
                    # TODO hand over to plugins to parse
                    pass

            if message_elements:
                message_list.append(message_elements)

        return message_list

    async def _parse_and_generate_messages(self, xml_data: str) -> tuple[List[List], str]:
        """
        parse xml generated by llm & generate MessageType list
        :return: (message_list, actual_xml) - actual_xml 是实际使用的XML（可能是修复后的）
        """
        try:
            message_list = await self._parse_xml_msg(xml_data)
            return message_list, xml_data
        except Exception as e:
            logger.error(f"Error parsing message: {str(e)}")
            logger.debug(f"previously wrong format: {xml_data}")

            # init fixed_xml
            fixed_xml = xml_data
            try:
                llm_resp = await self.llm_api.chat([
                    {"role": "system",
                     "content": "你是一个xml 格式检查器，请将下面解析失败的xml修改为正确的格式，但不要修改标签内的任何数据，需要符合如下xml tag结构（非标准xml，没有<root>标签）：\n<msg>\n    ...\n</msg>\n其中可以有多个<msg>，代表发送多条消息。每个msg标签中可以有多个子标签代表不同的消息元素，如<text>文本消息</text>。如果消息中存在未转义的特殊字符请转义。直接输出修改后的内容，不要解释，不要输出任何多余内容"},
                    {"role": "user", "content": xml_data}
                ])
                fixed_xml = llm_resp.text_response
                logger.debug(f"fixed xml data: {fixed_xml}")
                message_list = await self._parse_xml_msg(fixed_xml)

                return message_list, fixed_xml
            except Exception as e:
                logger.error(f"error after trying to fix xml error: {e}")
                return [[Text(fixed_xml)]], fixed_xml

    def _add_message_ids(self, xml_data: str, message_ids: List[str]) -> str:
        """为XML响应添加消息ID"""
        try:
            root = ET.fromstring(f"<root>{xml_data}</root>")

            for i, msg in enumerate(root.findall("msg")):
                if i < len(message_ids):
                    msg.set("message_id", message_ids[i])

            return ET.tostring(root, encoding='unicode', method='xml')[6:-7]

        except Exception as e:
            logger.error(f"Error adding message IDs: {str(e)}")
            return xml_data
