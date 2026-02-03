import asyncio
from asyncio import Lock
import xml.etree.ElementTree as ET
from typing import Union, Any, List
from asyncio import Semaphore
import random
import os

from core.logging_manager import get_logger
from core.services.runtime import get_adapter_by_name
from core.utils.common_utils import image_to_base64
from core.utils.path_utils import get_data_path
from core.chat.message_utils import KiraMessageEvent, KiraCommentEvent, MessageChain, MessageType
from core.llm_client import LLMClient
from .memory_manager import MemoryManager
from .prompt_manager import PromptManager
from .chat import Session

logger = get_logger("message_processor", "cyan")


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""
    
    def __init__(self,
                 kira_config,
                 llm_api: LLMClient,
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

        self.message_processing_semaphore = Semaphore(max_concurrent_messages)
        
        # managers
        self.memory_manager = memory_manager
        self.prompt_manager = prompt_manager

        # message buffer
        self.message_buffer: dict[str, Any] = {}
        self.buffer_locks: dict[str, asyncio.Lock] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        
        logger.info("MessageProcessor initialized")

    def get_buffer_lock(self, sid: str) -> Lock:
        """get buffer lock"""
        if sid not in self.buffer_locks:
            self.buffer_locks[sid] = asyncio.Lock()
        return self.buffer_locks[sid]

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

    async def message_format_to_text(self, message_list: list[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]):
        """将平台使用标准消息格式封装的消息转换为LLM可以接收的字符串"""
        message_str = ""
        for ele in message_list:
            if isinstance(ele, MessageType.Text):
                message_str += ele.text
            elif isinstance(ele, MessageType.Emoji):
                message_str += f"[Emoji {ele.emoji_id}]"
            elif isinstance(ele, MessageType.At):
                if ele.nickname:
                    message_str += f"[At {ele.pid}(nickname: {ele.nickname})]"
                else:
                    message_str += f"[At {ele.pid}]"
            elif isinstance(ele, MessageType.Image):
                img_desc = await self.llm_api.desc_img(ele.url)
                message_str += f"[Image {img_desc}]"
            elif isinstance(ele, MessageType.Sticker):
                sticker_desc = await self.llm_api.desc_img(ele.sticker_bs64, is_base64=True)
                message_str += f"[Sticker {sticker_desc}]"
            elif isinstance(ele, MessageType.Reply):
                if ele.message_content:
                    message_str += f"[Reply {ele.message_content}]"
                else:
                    message_str += f"[Reply {ele.message_id}]"
            elif isinstance(ele, MessageType.Record):
                record_text = await self.llm_api.speech_to_text(ele.bs64)
                message_str += f"[Record {record_text}]"
            elif isinstance(ele, MessageType.Notice):
                message_str += f"{ele.text}"
            else:
                pass
        return message_str
    
    async def handle_message(self, msg: Union[KiraMessageEvent, KiraCommentEvent]):
        """处理消息，带并发控制"""
        async with self.message_processing_semaphore:
            if isinstance(msg, KiraMessageEvent):
                await self.handle_im_message(msg)
            elif isinstance(msg, KiraCommentEvent):
                await self.handle_cmt_message(msg)
            else:
                logger.warning(f"Unknown message type: {type(msg)}")

    async def handle_im_message(self, msg: KiraMessageEvent):
        """process im message"""
        if msg.is_group_message():
            logger.info(f"[{msg.adapter_name} | {msg.message_id}] [{msg.group_name} | {msg.user_nickname}]: {msg.message_repr}")
        else:
            logger.info(f"[{msg.adapter_name} | {msg.message_id}] [{msg.user_nickname}]: {msg.message_repr}")

        session = Session(
            adapter_name=msg.adapter_name,
            session_type="gm" if msg.is_group_message() else "dm",
            session_id=msg.group_id if msg.is_group_message() else msg.user_id,
        )

        sid = session.sid

        # acquire buffer lock
        buffer_lock = self.get_buffer_lock(sid)

        async with buffer_lock:
            if sid not in self.message_buffer:
                self.message_buffer[sid] = []
            self.message_buffer[sid].append(msg)
            msg_amount = len(self.message_buffer[sid])

        if msg_amount < self.max_buffer_messages:
            await asyncio.sleep(self.max_message_interval)
        if len(self.message_buffer[sid]) == msg_amount:
            # print("no new message coming, processing")
            async with buffer_lock:
                message_processing: list[KiraMessageEvent] = self.message_buffer[sid][:msg_amount]
                self.message_buffer[sid] = self.message_buffer[sid][msg_amount:]
            logger.info(f"deleted {msg_amount} message(s) from buffer")
        else:
            # print("new message coming")
            return None

        # Start processing
        formatted_messages_str = ""
        for message in message_processing:
            message_list = message.content
            message.message_str = await self.message_format_to_text(message_list)
            formatted_message = self.prompt_manager.format_user_message(message)
            formatted_messages_str += f"{formatted_message}\n"
        logger.info(f"processing message(s) from {msg.adapter_name}:\n{formatted_messages_str}")

        # Get existing session
        session_list = self.get_session_list_prompt()

        # Build chat environment
        chat_env = {
            "platform": msg.platform,
            "chat_type": 'GroupMessage' if msg.is_group_message() else 'DirectMessage',
            "self_id": msg.self_id,
            "session_list": session_list
        }

        # Get chat history memory
        session_memory = self.memory_manager.fetch_memory(sid)
        # Get core memory
        core_memory = self.memory_manager.get_core_memory()

        # Get emoji_dict
        emoji_dict = getattr(get_adapter_by_name(msg.adapter_name), "emoji_dict", {})

        # Generate agent prompt
        agent_prompt = self.prompt_manager.get_agent_prompt(chat_env, core_memory, msg.message_types, emoji_dict)
        messages = [{"role": "system", "content": agent_prompt}]

        session_memory.append({"role": "user", "content": formatted_messages_str})
        new_memory_chunk = [{"role": "user", "content": formatted_messages_str}]
        messages.extend(session_memory)

        def append_msg(msg: dict):
            messages.append(msg)
            new_memory_chunk.append(msg)

        def extend_msg(msg: list):
            messages.extend(msg)
            new_memory_chunk.extend(msg)

        # Get max tool loop config, defaults to 2 if not a valid integer
        max_tool_loop = self.kira_config.get_config("bot_config.agent.max_tool_loop")
        try:
            max_tool_loop = int(max_tool_loop)
        except ValueError:
            max_tool_loop = 2

        max_agent_steps = max_tool_loop+1

        for _ in range(max_agent_steps):
            llm_resp = await self.llm_api.agent_run(messages)
            if llm_resp:
                if not llm_resp.tool_calls:
                    session_lock = self.get_session_lock(sid)
                    async with session_lock:
                        message_ids, actual_xml = await self.send_xml_messages(sid, llm_resp.text_response.strip())
                        response_with_ids = self._add_message_ids(actual_xml, message_ids)
                        logger.info(f"LLM: {response_with_ids}")
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
                    append_msg({"role": "assistant",
                                "content": response_with_ids if llm_resp.text_response else "",
                                "tool_calls": llm_resp.tool_calls})
                    extend_msg(llm_resp.tool_results)
            else:
                append_msg({"role": "assistant",
                            "content": ""})
                break

        self.memory_manager.update_memory(sid, new_memory_chunk)

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
                        message_elements.append(MessageType.Text(value))
                elif tag == "emoji":
                    message_elements.append(MessageType.Emoji(value))
                elif tag == "sticker":
                    sticker_id = value
                    try:
                        sticker_path = self.prompt_manager.sticker_dict[sticker_id].get("path")
                        sticker_bs64 = image_to_base64(f"{get_data_path()}/sticker/{sticker_path}")
                        message_elements.append(MessageType.Sticker(sticker_id, sticker_bs64))
                    except Exception as e:
                        logger.error(f"error while parsing sticker: {str(e)}")
                elif tag == "at":
                    message_elements.append(MessageType.At(value))
                elif tag == "img":
                    img_res = await self.llm_api.generate_img(value)
                    if img_res:
                        if img_res.url:
                            message_elements.append(MessageType.Image(url=img_res.url))
                        elif img_res.base64:
                            message_elements.append(MessageType.Image(base64=img_res.base64))
                        else:
                            pass
                elif tag == "reply":
                    message_elements.append(MessageType.Reply(value))
                elif tag == "record":
                    try:
                        record_bs64 = await self.llm_api.text_to_speech(value)
                        message_elements.append(MessageType.Record(record_bs64))
                    except Exception as e:
                        logger.error(f"an error occurred while generating voice message: {e}")
                        message_elements.append(MessageType.Text(f"<record>{value}</record>"))
                elif tag == "poke":
                    message_elements.append(MessageType.Poke(value))
                elif tag == "selfie":
                    try:
                        ref_img_path = self.kira_config.get('bot_config', {}).get('selfie', {}).get('path', '')
                        if os.path.exists(f"{get_data_path()}/{ref_img_path}"):
                            img_extension = ref_img_path.split(".")[-1]
                            bs64 = image_to_base64(f"{get_data_path()}/{ref_img_path}")
                            img_res = await self.llm_api.image_to_image(value, bs64=f"data:image/{img_extension};base64,{bs64}")
                            if img_res:
                                if img_res.url:
                                    message_elements.append(MessageType.Image(url=img_res.url))
                                elif img_res.base64:
                                    message_elements.append(MessageType.Image(base64=img_res.base64))
                                else:
                                    logger.warning("Invalid selfie image result")
                        else:
                            logger.warning(f"Selfie reference image not found, skipped generation")
                    except Exception as e:
                        logger.error(f"Failed to generate selfie: {e}")

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
                return [[MessageType.Text(fixed_xml)]], fixed_xml

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
