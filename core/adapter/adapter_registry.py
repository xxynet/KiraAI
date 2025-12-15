import asyncio
from typing import Any

from core.logging_manager import get_logger
from adapters.qq.qq_reply import QQAdapter
from adapters.telegram.tg import TelegramAdapter
from adapters.bilibili.bilibili import BiliBiliAdapter


logger = get_logger("adapter", "blue")

ada_mapping = {'QQ': QQAdapter,
               'Telegram': TelegramAdapter,
               'BiliBili': BiliBiliAdapter}


class AdapterManager:
    def __init__(self, loop: asyncio.AbstractEventLoop, event_queue: asyncio.Queue):
        self._adapters: dict[str, Any] = {}
        self.loop = loop
        self.event_queue = event_queue

    def initialize(self):
        pass

    async def register_adapter(self, platform, name, config: dict):
        self._adapters[name] = ada_mapping[platform](config, self.loop, self.event_queue)

        try:
            task = asyncio.create_task(self._adapters[name].start())
            task.add_done_callback(lambda t: logger.info(f"Started adapter {name}"))
        except Exception as e:
            logger.error(f"Failed to start adapter {name}: {e}")

    def get_adapters(self):
        return self._adapters

    def get_adapter_by_name(self, name: str):
        return self._adapters.get(name)
