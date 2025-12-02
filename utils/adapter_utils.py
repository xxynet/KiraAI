import asyncio
from abc import ABC, abstractmethod
from typing import Union, Type, Optional, List, Dict, Any

from utils.message_utils import MessageType
from utils.message_utils import KiraMessageEvent, MessageSending


class IMAdapter(ABC):
    def __init__(self, config: Dict[str, Any], loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        self.name: Optional[str] = None
        self.config = config
        self.emoji_dict: Optional[dict] = None
        self.message_types: list[Type[Union[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]]] = []
        self.loop = loop
        self.event_bus = event_bus
        
        # 白名单配置 - 子类可以覆盖 _parse_id_list 或 _init_config 来自定义解析逻辑
        self.group_list: List[Union[int, str]] = []
        self.user_list: List[Union[int, str]] = []
        self._init_whitelists()

    def _init_whitelists(self):
        """初始化白名单列表，从配置中解析 group_list 和 user_list"""
        group_list_str = self.config.get("group_list", "")
        user_list_str = self.config.get("user_list", "")
        
        if group_list_str:
            self.group_list = self._parse_id_list(group_list_str)
        if user_list_str:
            self.user_list = self._parse_id_list(user_list_str)

    @staticmethod
    def _parse_id_list(csv: str) -> List[Union[int, str]]:
        try:
            return [int(item.strip()) for item in csv.split(",") if item.strip()]
        except Exception as e:
            print(f"error occurred while parsing id list: {str(e)}")
            return []

    @abstractmethod
    async def start(self):
        """启动适配器，子类必须实现此方法"""
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
    async def send_comment(self, root: Union[int, str], sub: Union[int, str] = None):
        pass


class LiveStreamAdapter(ABC):
    pass
