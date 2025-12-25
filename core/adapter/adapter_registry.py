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
    def __init__(self, adas_config: dict, loop: asyncio.AbstractEventLoop, event_queue: asyncio.Queue, llm_api):
        self._adapters: dict[str, Any] = {}
        self.adas_config = adas_config
        self.loop = loop
        self.event_queue = event_queue
        self.llm_api = llm_api

    async def initialize(self):
        for ada_name in self.adas_config:
            ada_config = self.adas_config[ada_name]
            ada_platform = ada_config["platform"]
            await self.register_adapter(ada_platform, ada_name, ada_config)

    async def register_adapter(self, platform, name, config: dict):
        if config.get("enabled", "false").lower() == "true":
            self._adapters[name] = ada_mapping[platform](config, self.loop, self.event_queue, self.llm_api)
            await self.start_adapter(name)

    async def start_adapter(self, name):
        try:
            task = asyncio.create_task(self._adapters[name].start())
            task.add_done_callback(lambda t: logger.info(f"Started adapter {name}"))
        except Exception as e:
            logger.error(f"Failed to start adapter {name}: {e}")

    async def stop_adapter(self, name):
        pass

    def get_adapters(self):
        return self._adapters

    def get_adapter_by_name(self, name: str):
        return self._adapters.get(name)
