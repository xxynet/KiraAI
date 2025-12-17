import asyncio
import time
from typing import Any, Dict, Union, Optional

from core.logging_manager import get_logger
from core.config_loader import global_config

from adapters.qq.qq_reply import QQAdapter
from adapters.telegram.tg import TelegramAdapter
from adapters.bilibili.bilibili import BiliBiliAdapter

from utils.message_utils import KiraMessageEvent
from core.sticker_manager import sticker_manager
from core.message_manager import MessageProcessor

from .adapter import AdapterManager
from .statistics import Statistics


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self, stats: Statistics):
        self.stats = stats
        stats.set_stats("started_ts", int(time.time()))

        self.adapter_manager: Optional[AdapterManager] = None

        self.message_processor: Optional[MessageProcessor] = None

        self.tasks: list[asyncio.Task] = []

    async def schedule_tasks(self):
        self.tasks = [
            asyncio.create_task(sticker_manager.scan_and_register_sticker())
        ]
        await asyncio.gather(*self.tasks)

    async def init_and_run_system(self):
        """主函数：负责启动和初始化各个模块"""
        logger.info("✨ Starting KiraAI...")

        # ====== event bus ======
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # ====== load adapters ======
        adas_config = global_config["ada_config"]

        # init adapter manager
        self.adapter_manager = AdapterManager(loop, event_queue, adas_config)

        # init adapter manager & start adapter instances
        await self.adapter_manager.initialize()

        # ====== init message processor ======
        self.message_processor = MessageProcessor()

        # expose adapters and loop globally for runtime usage everywhere
        from core.services.runtime import set_adapters, set_event_bus
        set_adapters(self.adapter_manager.get_adapters())
        set_event_bus(event_queue)

        logger.info("All modules initialized, starting message processing loop...")

        # ====== message handling loop ======
        while True:
            msg: Union[KiraMessageEvent] = await event_queue.get()
            asyncio.create_task(self.message_processor.handle_message(msg))

    async def stop(self):
        for task in self.tasks:
            task.cancel()
