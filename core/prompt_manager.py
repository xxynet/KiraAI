import json
from datetime import datetime
from typing import Dict, Any, Union, Type, Optional

from core.config_loader import global_config
from core.logging_manager import get_logger
from core.sticker_manager import sticker_manager
from utils.message_utils import BotPrivateMessage, BotGroupMessage
from utils.message_utils import MessageType

logger = get_logger("prompt_manager", "yellow")


class PromptManager:
    """管理系统提示词和工具提示词的生成"""
    
    def __init__(self, 
                 persona_path: str = "prompts/persona.txt",
                 emoji_path: str = "adapters/qq/emoji.json",
                 format_path: str = "prompts/format.txt",
                 tool_path: str = "prompts/tool.txt",
                 system_path: str = "prompts/system.txt"):
        self.persona_path = persona_path
        self.emoji_path = emoji_path
        self.format_path = format_path
        self.tool_path = tool_path
        self.system_path = system_path
        
        # 加载基础提示词
        self.persona_prompt = self._load_file(persona_path)
        self.emoji_dict = self._load_dict(emoji_path)
        self.sticker_dict = sticker_manager.sticker_dict
        self.sticker_prompt = self._load_sticker_prompt(self.sticker_dict)
        self.ada_config_prompt = self.load_ada_config_prompt()
        
        logger.info("PromptManager initialized")

    @staticmethod
    def _load_file(path: str) -> str:
        """加载文本文件"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading file {path}: {e}")
            return ""

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """加载字典"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception as e:
            logger.error(f"Error loading emoji dict from {path}: {e}")
            return {}

    @staticmethod
    def _load_sticker_prompt(sticker_dict: dict) -> str:
        """加载表情包（贴纸）提示词"""
        sticker_prompt = ""
        try:
            for sticker_id in sticker_dict:
                sticker_prompt += f"[{sticker_id}] {sticker_dict[sticker_id].get('desc')}\n"
            return sticker_prompt
        except Exception as e:
            logger.error(f"Error loading sticker prompt: {e}")
            return ""

    @staticmethod
    def _load_supported_format_prompt(message_types: list[Type[Union[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]]]):
        supported_format_prompt = ""
        if MessageType.Text in message_types:
            supported_format_prompt += "<text>some text</text> # 纯文本消息\n"
        if MessageType.Image in message_types:
            supported_format_prompt += "<img>prompt for image generator</img> # 请勿滥用，仅在用户请求看照片时使用，需要详细的绘画提示词。\n"
        if MessageType.At in message_types:
            supported_format_prompt += "<at>user_id</at> # 通过用户id使用@功能，通常出现在消息的开头，有时也会在消息中间（如果聊天中需要提及其他人），特殊的，传入字符串all代表@全体成员。at功能仅在群聊中使用\n"
        if MessageType.Reply in message_types:
            supported_format_prompt += "<reply>message_id</reply> # 回复一条消息，如果使用这个标签，需要为一条消息的第一个元素，且不能单独出现\n"
        if MessageType.Record in message_types:
            supported_format_prompt += "<record>record_text</record> # 要发送的语音文本，不能和其他msg内标签混用，用户给你发语音或者用户要求你发语音时使用（收到语音消息类似这样：[Record voice_message]）\n"
        if MessageType.Emoji in message_types:
            # 需要传入 emoji_json 参数
            supported_format_prompt += "<emoji>emoji_id</emoji> # 发送一个emoji（中文一般叫做表情）消息，通常和文字在同一个msg标签中，可以使用的emoji如下：{emoji_json}\n"
        if MessageType.Sticker in message_types:
            # 需要传入 sticker_prompt 参数
            supported_format_prompt += "<sticker>sticker_id</sticker> # 发送一个sticker（中文一般叫做表情包）消息，通常单独在一条消息里，你需要在聊天中主动自然使用这些sticker，可以使用的sticker id和描述如下：{sticker_prompt}\n"
        if MessageType.Poke in message_types:
            supported_format_prompt += "<poke>user_id</poke> # 发送戳一戳消息（一个社交平台的小功能用于引起用户注意），只能单独一条消息，不能和其他元素出现在一条消息中。可以在别人对你戳一戳（捏一捏）时使用，也可以在日常交流中自然使用\n"
        return supported_format_prompt
    
    def _load_format_prompt(self, message_types: list[Type[Union[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]]], emoji_dict: Optional[dict] = None) -> str:
        """加载格式提示词"""
        if not message_types:
            message_types = [MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]
        message_type_prompt = self._load_supported_format_prompt(message_types)
        # 格式化小表情JSON
        emoji_json = json.dumps(emoji_dict, ensure_ascii=False)

        self.sticker_dict = sticker_manager.sticker_dict
        self.sticker_prompt = self._load_sticker_prompt(self.sticker_dict)

        message_type_prompt = message_type_prompt.format(emoji_json=emoji_json, sticker_prompt=self.sticker_prompt)
        try:
            with open(self.format_path, 'r', encoding="utf-8") as f:
                format_prompt = f.read()
            return format_prompt.format(message_types=message_type_prompt)
        except Exception as e:
            logger.error(f"Error loading format prompt from {self.format_path}: {e}")
            return ""

    @staticmethod
    def get_current_time_str() -> str:
        """获取当前时间字符串"""
        now = datetime.now()
        return now.strftime("%b %d %Y %H:%M %a")

    @staticmethod
    def load_ada_config_prompt():
        ada_config_prompt = ""
        ada_config = global_config["ada_config"]
        for ada in ada_config:
            ada_platform = ada_config[ada].get("platform")
            ada_desc = ada_config[ada].get("desc")
            bot_pid = ada_config[ada].get("bot_pid")
            ada_config_prompt += f"Platform: {ada_platform}, account_desc: {ada_desc}, account_id: {bot_pid}\n"

        return ada_config_prompt

    def get_system_prompt(self, chat_env: Dict[str, Any], core_memory: str, message_types: list, emoji_dict: Optional[dict] = None) -> str:
        """生成系统提示词"""
        formatted_time = self.get_current_time_str()
        
        try:
            with open(self.system_path, 'r', encoding="utf-8") as f:
                system_prompt = f.read()
            return system_prompt.format(
                persona=self.persona_prompt, 
                format=self._load_format_prompt(message_types, emoji_dict),
                time_str=formatted_time,
                chat_env=chat_env,
                core_memory=core_memory,
                accounts=self.ada_config_prompt
            )
        except Exception as e:
            logger.error(f"Error generating system prompt: {e}")
            return ""
    
    def get_tool_prompt(self, chat_env: Dict[str, Any], core_memory: str, message_types: list, emoji_dict: Optional[dict] = None) -> str:
        """生成工具提示词"""
        formatted_time = self.get_current_time_str()

        try:
            with open(self.tool_path, 'r', encoding="utf-8") as f:
                tool_prompt = f.read()
            return tool_prompt.format(
                persona=self.persona_prompt,
                format=self._load_format_prompt(message_types, emoji_dict),
                time_str=formatted_time,
                chat_env=chat_env,
                core_memory=core_memory,
                accounts=self.ada_config_prompt
            )
        except Exception as e:
            logger.error(f"Error generating tool prompt: {e}")
            return ""

    def format_user_message(self, msg: Union[BotPrivateMessage, BotGroupMessage]) -> str:
        """格式化用户消息"""
        date_str = self.get_current_time_str()
        
        if isinstance(msg, BotGroupMessage):
            # 群聊消息格式
            return f"[received_time: {date_str} message_id: {str(msg.message_id)}] [group_name: {msg.group_name} group_id: {msg.group_id} user_nickname: {msg.user_nickname}, user_id: {msg.user_id}] | {msg.message_str}"
        elif isinstance(msg, BotPrivateMessage):
            # 私聊消息格式
            return f"[received_time: {date_str} message_id: {str(msg.message_id)}] [user_nickname: {msg.user_nickname}, user_id: {msg.user_id}] | {msg.message_str}"
