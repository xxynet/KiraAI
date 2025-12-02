import asyncio
import xml.etree.ElementTree as ET
from typing import Union, Dict, Any, List
from asyncio import Semaphore
import random

from core.llm_manager import llm_api
from core.logging_manager import get_logger
from core.config_loader import global_config
from core.tts.siliconflow.sftts import generate_speech, speech_to_text
from core.memory_manager import MemoryManager
from core.prompt_manager import PromptManager
from core.services.runtime import get_adapter_by_name
from utils.common_utils import image_to_base64
from utils.message_utils import KiraMessageEvent, MessageSending, MessageType

logger = get_logger("message_processor", "cyan")

config_max_message_interval = int(global_config["bot_config"].get("bot").get("max_message_interval"))
config_max_buffer_messages = int(global_config["bot_config"].get("bot").get("max_buffer_messages"))


class MessageProcessor:
    """Core message processor, responsible for handling all message sending and receiving logic"""
    
    def __init__(self,
                 max_message_interval: int = config_max_message_interval,
                 max_buffer_messages: int = config_max_buffer_messages,
                 max_concurrent_messages: int = 3):
        self.message_processing_semaphore = Semaphore(max_concurrent_messages)
        self.max_message_interval = max_message_interval
        self.max_buffer_messages = max_buffer_messages
        
        # init managers
        self.memory_manager = MemoryManager()
        self.prompt_manager = PromptManager()

        # message buffer
        self.message_buffer: dict[str, Any] = {}
        self.buffer_locks: dict[str, asyncio.Lock] = {}
        
        logger.info("MessageProcessor initialized")

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
                record_text = speech_to_text(ele.bs64)
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
            else:
                logger.warning(f"Unknown message type: {type(msg)}")

    async def _handle_im_message(self, msg: KiraMessageEvent):
        """process im message"""
        if msg.is_group_message():
            logger.info(f"[{msg.adapter_name} | {msg.message_id}] [{msg.group_name} | {msg.user_nickname}]: {msg.message_repr}")
        else:
            logger.info(f"[{msg.adapter_name} | {msg.message_id}] [{msg.user_nickname}]: {msg.message_repr}")
        session_id_str = msg.group_id if msg.is_group_message() else msg.user_id
        dict_key = f"{msg.adapter_name}:{'gm' if msg.is_group_message() else 'dm'}:{session_id_str}"
        if dict_key not in self.buffer_locks:
            self.buffer_locks[dict_key] = asyncio.Lock()
        buffer_lock = self.buffer_locks[dict_key]

        async with buffer_lock:
            if dict_key not in self.message_buffer:
                self.message_buffer[dict_key] = []
            self.message_buffer[dict_key].append(msg)
            msg_amount = len(self.message_buffer[dict_key])

        if msg_amount < self.max_buffer_messages:
            await asyncio.sleep(self.max_message_interval)
        if len(self.message_buffer[dict_key]) == msg_amount:
            # print("no new message coming, processing")
            async with buffer_lock:
                message_processing: list[KiraMessageEvent] = self.message_buffer[dict_key][:msg_amount]
                self.message_buffer[dict_key] = self.message_buffer[dict_key][msg_amount:]
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
        session_memory = self.memory_manager.fetch_memory(dict_key)
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
        session_lock = self.memory_manager.get_session_lock(session_id_str)

        response, tool_messages = await llm_api.chat_with_tools(messages, tool_prompt)
        # logger.info(f"LLM响应: {response}")

        async with session_lock:
            message_ids = await self.send_xml_messages(dict_key, response)

            # 添加消息ID到响应中
            response_with_ids = self._add_message_ids(response, message_ids)
            # print(response_with_ids)
            logger.info(f"LLM: {response_with_ids}")

            # 更新记忆
            if tool_messages:
                for tool_message in tool_messages:
                    new_memory_chunk.append(tool_message)

            new_memory_chunk.append({"role": "assistant", "content": response_with_ids})
            self.memory_manager.update_memory(dict_key, new_memory_chunk)

    async def send_xml_messages(self, target: str, xml: str) -> List[str]:
        """
        send message via session id & xml data
        :param target: adapter_name:session_type:session_id
        :param xml: xml string
        :return: message id(s)
        """
        message_ids = []
        resp_list = await self._parse_and_generate_messages(xml)

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
            await asyncio.sleep(random.uniform(0.8, 1.5))

        return message_ids

    def _parse_xml_msg(self, xml_data):
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
                    img_url = llm_api.generate_img(value)
                    message_elements.append(MessageType.Image(img_url))
                elif tag == "reply":
                    message_elements.append(MessageType.Reply(value))
                elif tag == "record":
                    try:
                        record_bs64 = generate_speech(value)
                        message_elements.append(MessageType.Record(record_bs64))
                    except Exception as e:
                        logger.error(f"an error occurred while generating voice message: {e}")
                        message_elements.append(MessageType.Text(f"<record>{value}</record>"))
                elif tag == "poke":
                    message_elements.append(MessageType.Poke(value))

            if message_elements:
                message_list.append(message_elements)

        return message_list
    
    async def _parse_and_generate_messages(self, xml_data: str) -> List[List]:
        """parse xml generated by llm & generate MessageType list"""
        try:
            message_list = self._parse_xml_msg(xml_data)
            return message_list
        except Exception as e:
            logger.error(f"Error parsing message: {str(e)}")
            # 返回包含文本消息的列表
            logger.info(f"previously wrong format: {xml_data}")
            try:
                fixed_xml, _ = await llm_api.chat([{"role": "system", "content": "你是一个xml 格式检查器，请将下面解析失败的xml修改为正确的格式，但不要修改标签内的任何数据，需要符合如下xml tag结构（非标准xml，没有<root>标签）：\n<msg>\n    ...\n</msg>\n其中可以有多个<msg>，代表发送多条消息。直接输出修改后的内容，不要输出任何多余内容"}, {"role": "user", "content": xml_data}])
                logger.info(f"fixed xml data: {fixed_xml}")
                message_list = self._parse_xml_msg(xml_data)

                return message_list
            except Exception as e:
                logger.error(f"error after trying to fix xml error: {e}")
                return [[MessageType.Text(xml_data)]]

    @staticmethod
    def _add_message_ids(xml_data: str, message_ids: List[str]) -> str:
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
message_processor = MessageProcessor()
