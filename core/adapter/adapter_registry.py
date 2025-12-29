import asyncio
from typing import Union, Optional

from core.logging_manager import get_logger
from .adapter_utils import IMAdapter, SocialMediaAdapter
from .src.qq import QQAdapter
from .src.telegram import TelegramAdapter
from .src.bilibili import BiliBiliAdapter


logger = get_logger("adapter", "blue")

ada_mapping = {'QQ': QQAdapter,
               'Telegram': TelegramAdapter,
               'BiliBili': BiliBiliAdapter}


class AdapterManager:
    def __init__(self, adas_config: dict, loop: asyncio.AbstractEventLoop, event_queue: asyncio.Queue, llm_api):
        self._adapters: dict[str, Union[IMAdapter, SocialMediaAdapter]] = {}
        self.adas_config = adas_config
        self.loop = loop
        self.event_queue = event_queue
        self.llm_api = llm_api

    async def initialize(self):
        for ada_name in self.adas_config:
            ada_config = self.adas_config[ada_name]
            ada_platform = ada_config["platform"]
            await self.register_adapter(ada_platform, ada_name, ada_config)
        logger.info(f"Adapters set: {list(self._adapters.keys())}")

    async def register_adapter(self, platform, name, config: dict):
        if config.get("enabled", "false").lower() == "true":
            self._adapters[name] = ada_mapping[platform](config, self.loop, self.event_queue, self.llm_api)
            await self.start_adapter(name)

    async def start_adapter(self, name):
        """start an adapter by specified adapter name"""
        try:
            task = asyncio.create_task(self._adapters[name].start())
            task.add_done_callback(lambda t: logger.info(f"Started adapter {name}"))
        except Exception as e:
            logger.error(f"Failed to start adapter {name}: {e}")

    async def stop_adapter(self, name):
        """stop an adapter by specified adapter name"""
        if self._adapters.get(name):
            await self._adapters.get(name).stop()

    async def stop_adapters(self):
        """stop all running adapters"""
        for ada in self._adapters:
            await self._adapters[ada].stop()

    def get_adapters(self) -> dict[str, Union[IMAdapter, SocialMediaAdapter]]:
        """return the entire dict where adapters are registered"""
        return self._adapters

    def get_adapter(self, name: str) -> Union[IMAdapter, SocialMediaAdapter]:
        """get an adapter instance by specified adapter name"""
        return self._adapters.get(name)
