import asyncio
from abc import ABC, abstractmethod
from typing import Union, Optional, List, Dict, Any

from core.chat.message_utils import KiraMessageEvent, MessageSending

from core.llm_client import LLMClient


class IMAdapter(ABC):
    def __init__(self, config: Dict[str, Any], loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue, llm_api: LLMClient):
        self.name: Optional[str] = None
        self.config = config
        self.emoji_dict: Optional[dict] = None
        self.message_types: list = []
        self.loop = loop
        self.event_bus = event_bus
        self.llm_api = llm_api

        self.permission_mode = None

        self.group_list: List[Union[int, str]] = []
        self.user_list: List[Union[int, str]] = []

        self._init_permission_lists()

    def _init_permission_lists(self):
        """init permission lists"""

        _permission_mode = self.config.get("permission_mode", "allow_list")

        self.permission_mode = _permission_mode

        if _permission_mode == "allow_list":
            group_allow_list_str = self.config.get("group_allow_list", "")
            user_allow_list_str = self.config.get("user_allow_list", "")

            if group_allow_list_str:
                self.group_list = self._parse_id_list(group_allow_list_str)
            if user_allow_list_str:
                self.user_list = self._parse_id_list(user_allow_list_str)
        elif _permission_mode == "deny_list":
            group_deny_list_str = self.config.get("group_deny_list", "")
            user_deny_list_str = self.config.get("user_deny_list", "")

            if group_deny_list_str:
                self.group_list = self._parse_id_list(group_deny_list_str)
            if user_deny_list_str:
                self.user_list = self._parse_id_list(user_deny_list_str)
        else:
            self.permission_mode = "allow_list"

    @staticmethod
    def _parse_id_list(csv: str) -> List[Union[int, str]]:
        try:
            return [int(item.strip()) for item in csv.split(",") if item.strip()]
        except Exception as e:
            print(f"error occurred while parsing id list: {str(e)}")
            return []

    @abstractmethod
    async def start(self):
        """Start adapter, sub classes must implement this method"""
        pass

    @abstractmethod
    async def stop(self):
        """Stop adapter, sub classes must implement this method"""

    @abstractmethod
    def get_client(self):
        """return a client instance"""
        pass

    def publish(self, message: Union[KiraMessageEvent]):
        """把消息放到事件总线"""
        asyncio.run_coroutine_threadsafe(self.event_bus.put(message), self.loop)

    @abstractmethod
    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageSending) -> Optional[str]:
        """
        发送群消息
        参数:
            group_id: 群组ID
            send_message_obj: 要发送的消息对象
        返回:
            消息ID（字符串），发送失败返回None
        """
        pass

    @abstractmethod
    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageSending) -> Optional[str]:
        """
        发送私聊消息
        参数:
            user_id: 用户ID
            send_message_obj: 要发送的消息对象
        返回:
            消息ID（字符串），发送失败返回None
        """
        pass


class SocialMediaAdapter(ABC):
    def __init__(self, config: Dict[str, Any], loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        self.name: Optional[str] = None
        self.config = config
        self.emoji_dict: Optional[dict] = None
        self.loop = loop
        self.event_bus = event_bus

    @abstractmethod
    async def start(self):
        pass

    async def get_feed(self, count: int):
        pass

    async def search(self, keyword: str, count: int):
        pass

    @abstractmethod
    async def send_comment(self, text: str, root: Union[int, str], sub: Union[int, str] = None):
        pass


class LiveStreamAdapter(ABC):
    pass
