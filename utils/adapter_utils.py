import asyncio
from abc import ABC, abstractmethod
from typing import Union, Type, Optional

from utils.message_utils import MessageType
from utils.message_utils import BotPrivateMessage, BotGroupMessage


class IMAdapter(ABC):
    def __init__(self, config, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        self.name = None
        self.config = config
        self.emoji_dict: Optional[dict] = None
        self.message_types: list[Type[Union[MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Notice]]] = []
        self.loop = loop
        self.event_bus = event_bus

    @abstractmethod
    def start(self):
        pass

    def publish(self, message: Union[BotPrivateMessage, BotGroupMessage]):
        """把消息放到事件总线"""
        asyncio.run_coroutine_threadsafe(self.event_bus.put(message), self.loop)


class SocialMediaAdapter(ABC):
    pass


class LiveStreamAdapter(ABC):
    pass
