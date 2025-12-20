import asyncio
from asyncio import Lock
import xml.etree.ElementTree as ET
from typing import Union, Dict, Any, List
from asyncio import Semaphore
import random
import re
import xml.sax.saxutils

from core.llm_manager import llm_api
from core.logging_manager import get_logger
from core.config_loader import global_config
from core.memory_manager import MemoryManager
from core.prompt_manager import PromptManager
from core.services.runtime import get_adapter_by_name
from utils.common_utils import image_to_base64
from utils.message_utils import KiraMessageEvent, KiraCommentEvent, MessageSending, MessageType
from .memory_manager import MemoryManager
from .prompt_manager import PromptManager
from .chat import Session

logger = get_logger("message_processor", "cyan")

bot_config = global_config["bot_config"].get("bot")

config_max_message_interval = float(bot_config.get("max_message_interval"))
config_max_buffer_messages = int(bot_config.get("max_buffer_messages"))

config_min_message_delay = float(bot_config.get("min_message_delay", "0.8"))
config_max_message_delay = float(bot_config.get("max_message_delay", "1.5"))


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""
    
    def __init__(self,
                 memory_manager: MemoryManager,
                 prompt_manager: PromptManager,
                 max_message_interval: int = config_max_message_interval,
                 max_buffer_messages: int = config_max_buffer_messages,
                 max_concurrent_messages: int = 3):
        self.message_processing_semaphore = Semaphore(max_concurrent_messages)
        self.max_message_interval = max_message_interval
        self.max_buffer_messages = max_buffer_messages
        
        # init managers
        self.memory_manager = memory_manager
        self.prompt_manager = prompt_manager

        # message buffer
        self.message_buffer: dict[str, Any] = {}
        self.buffer_locks: dict[str, asyncio.Lock] = {}
        self.session_locks: dict[str, asyncio.Lock] = {}
        
        logger.info("MessageProcessor initialized")

    def get_buffer_lock(self, session_identifier: str) -> Lock:
        """get buffer lock"""
        if session_identifier not in self.buffer_locks:
            self.buffer_locks[session_identifier] = asyncio.Lock()
        return self.buffer_locks[session_identifier]

    def get_session_lock(self, session_identifier: str) -> Lock:
        """get session lock to avoid sending message simultaneously"""
        if session_identifier not in self.session_locks:
            self.session_locks[session_identifier] = asyncio.Lock()
        return self.session_locks[session_identifier]

    def get_session_list_prompt(self) -> str:
        session_list_prompt = ""
        _chat_memory = self.memory_manager.chat_memory
        for session_id in _chat_memory:
            session_list_prompt += f"{session_id}\n"
        return session_list_prompt

    @staticmethod
    async def message_format_to_text(message_list: list[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]):
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
                img_desc = await llm_api.desc_img(ele.url)
                message_str += f"[Image {img_desc}]"
            elif isinstance(ele, MessageType.Reply):
                if ele.message_content:
                    message_str += f"[Reply {ele.message_content}]"
                else:
                    message_str += f"[Reply {ele.message_id}]"
            elif isinstance(ele, MessageType.Record):
                record_text = await llm_api.speech_to_text(ele.bs64)
                message_str += f"[Record {record_text}]"
            elif isinstance(ele, MessageType.Notice):
                message_str += f"{ele.text}"
            else:
                pass
        return message_str
    
    async def handle_message(self, msg: Union[KiraMessageEvent]):
        """处理消息，带并发控制"""
        async with self.message_processing_semaphore:
            if isinstance(msg, KiraMessageEvent):
                await self._handle_im_message(msg)
            elif isinstance(msg, KiraCommentEvent):
                await self._handle_cmt_message(msg)
            else:
                logger.warning(f"Unknown message type: {type(msg)}")

    async def _handle_im_message(self, msg: KiraMessageEvent):
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

        session_identifier = session.session_identifier

        # get buffer lock
        buffer_lock = self.get_buffer_lock(session_identifier)

        async with buffer_lock:
            if session_identifier not in self.message_buffer:
                self.message_buffer[session_identifier] = []
            self.message_buffer[session_identifier].append(msg)
            msg_amount = len(self.message_buffer[session_identifier])

        if msg_amount < self.max_buffer_messages:
            await asyncio.sleep(self.max_message_interval)
        if len(self.message_buffer[session_identifier]) == msg_amount:
            # print("no new message coming, processing")
            async with buffer_lock:
                message_processing: list[KiraMessageEvent] = self.message_buffer[session_identifier][:msg_amount]
                self.message_buffer[session_identifier] = self.message_buffer[session_identifier][msg_amount:]
            logger.info(f"deleted {msg_amount} message(s) from buffer")
        else:
            # print("new message coming")
            return None

        # start processing
        formatted_messages_str = ""
        for message in message_processing:
            message_list = message.content
            message.message_str = await self.message_format_to_text(message_list)
            formatted_message = self.prompt_manager.format_user_message(message)
            formatted_messages_str += f"{formatted_message}\n"
        logger.info(f"processing message(s) from {msg.adapter_name}:\n{formatted_messages_str}")

        # get existing session
        session_list = self.get_session_list_prompt()

        # build chat environment
        chat_env = {
            "platform": msg.platform,
            "chat_type": 'GroupMessage' if msg.is_group_message() else 'DirectMessage',
            "self_id": msg.self_id,
            "session_list": session_list
        }

        # 获取历史记忆
        session_memory = self.memory_manager.fetch_memory(session_identifier)
        # 获取核心记忆
        core_memory = self.memory_manager.get_core_memory()

        # emoji_dict
        emoji_dict = get_adapter_by_name(msg.adapter_name).emoji_dict

        # 生成系统提示词
        system_prompt = self.prompt_manager.get_system_prompt(chat_env, core_memory, msg.message_types, emoji_dict)
        messages = [{"role": "system", "content": system_prompt}]

        # 生成工具提示词
        tool_prompt = self.prompt_manager.get_tool_prompt(chat_env, core_memory, msg.message_types, emoji_dict)

        session_memory.append({"role": "user", "content": formatted_messages_str})
        new_memory_chunk = [{"role": "user", "content": formatted_messages_str}]
        messages.extend(session_memory)

        # 按会话加锁，防止同会话并发
        session_lock = self.get_session_lock(session_identifier)

        llm_resp = await llm_api.chat_with_tools(messages, tool_prompt)
        if llm_resp:
            response = llm_resp.text_response
            tool_messages = llm_resp.tool_results
            # logger.info(f"LLM响应: {response}")

            async with session_lock:
                message_ids, actual_xml = await self.send_xml_messages(session_identifier, response)
                response_with_ids = self._add_message_ids(actual_xml, message_ids)
                logger.info(f"LLM: {response_with_ids}")

                # 更新记忆
                if tool_messages:
                    new_memory_chunk.extend(tool_messages)

                new_memory_chunk.append({"role": "assistant", "content": response_with_ids})
                self.memory_manager.update_memory(session_identifier, new_memory_chunk)

    async def _handle_cmt_message(self, msg: KiraCommentEvent):
        """process comment message"""

        print(msg)

        if msg.sub_cmt_id:
            logger.info(f"[{msg.adapter_name} | {msg.sub_cmt_id}] [{msg.commenter_nickname}]: {msg.sub_cmt_content[0].text}")
            cmt_content = f"""You: {msg.cmt_content[0].text}
            {msg.commenter_nickname}: {msg.sub_cmt_content[0].text}
            """
        else:
            logger.info(f"[{msg.adapter_name} | {msg.cmt_id}] [{msg.commenter_nickname}]: {msg.cmt_content[0].text}")
            cmt_content = f"""{msg.commenter_nickname}: {msg.cmt_content[0].text}"""

        cmt_prompt = self.prompt_manager.get_comment_prompt(cmt_content)

        llm_resp = await llm_api.chat([{"role": "user", "content": cmt_prompt}])

        response = llm_resp.text_response

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
            raise ValueError("target 必须是 <adapter>:<dm|gm>:<id> 格式")
        adapter_name, chat_type, pid = parts[0], parts[1], parts[2]

        for message_list in resp_list:
            message_obj = MessageSending(message_list)

            # 根据消息类型选择发送方法
            if chat_type == "dm":
                message_id = await get_adapter_by_name(adapter_name).send_direct_message(pid, message_obj)
            elif chat_type == "gm":
                message_id = await get_adapter_by_name(adapter_name).send_group_message(pid, message_obj)
            else:
                message_id = None

            if not message_id:
                message_id = ''
            message_ids.append(message_id)

            # 添加随机延迟避免频率限制
            await asyncio.sleep(random.uniform(config_min_message_delay, config_max_message_delay))

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
                    message_elements.append(MessageType.Text(value))
                elif tag == "emoji":
                    message_elements.append(MessageType.Emoji(value))
                elif tag == "sticker":
                    sticker_id = value
                    try:
                        sticker_path = self.prompt_manager.sticker_dict[sticker_id].get("path")
                        sticker_bs64 = image_to_base64(f"data/sticker/{sticker_path}")
                        message_elements.append(MessageType.Sticker(sticker_id, sticker_bs64))
                    except Exception as e:
                        logger.error(f"error while parsing sticker: {str(e)}")
                elif tag == "at":
                    message_elements.append(MessageType.At(value))
                elif tag == "img":
                    img_res = await llm_api.generate_img(value)
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
                        record_bs64 = await llm_api.text_to_speech(value)
                        message_elements.append(MessageType.Record(record_bs64))
                    except Exception as e:
                        logger.error(f"an error occurred while generating voice message: {e}")
                        message_elements.append(MessageType.Text(f"<record>{value}</record>"))
                elif tag == "poke":
                    message_elements.append(MessageType.Poke(value))

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
            logger.info(f"previously wrong format: {xml_data}")

            # init fixed_xml
            fixed_xml = xml_data
            try:
                llm_resp = await llm_api.chat([{"role": "system", "content": "你是一个xml 格式检查器，请将下面解析失败的xml修改为正确的格式，但不要修改标签内的任何数据，需要符合如下xml tag结构（非标准xml，没有<root>标签）：\n<msg>\n    ...\n</msg>\n其中可以有多个<msg>，代表发送多条消息。每个msg标签中可以有多个子标签代表不同的消息元素，如<text>文本消息</text>。如果消息中存在未转义的特殊字符请转义。直接输出修改后的内容，不要输出任何多余内容"}, {"role": "user", "content": xml_data}])
                fixed_xml = llm_resp.text_response
                logger.info(f"fixed xml data: {fixed_xml}")
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


# global message processor
# message_processor = MessageProcessor()
