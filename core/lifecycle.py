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

from .statistics import Statistics


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self, stats: Statistics):
        self.stats = stats
        stats.set_stats("started_ts", int(time.time()))

        self.message_processor: Optional[MessageProcessor] = None

    async def schedule_tasks(self):
        while True:
            tasks = [
                sticker_manager.scan_and_register_sticker()
            ]
            await asyncio.gather(*tasks)

    async def init_and_run_system(self):
        """主函数：负责启动和初始化各个模块"""
        logger.info("Starting bot...")

        # ====== event bus ======
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # ====== init adapter mapping ======
        ada_mapping = {'QQ': QQAdapter,
                       'Telegram': TelegramAdapter,
                       'BiliBili': BiliBiliAdapter}
        adapters: Dict[str, Any] = {}

        # ====== load adapter config ======
        adas_config = global_config["ada_config"]
        for ada_name in adas_config:
            ada_config = adas_config[ada_name]
            ada_platform = ada_config["platform"]
            adapters[ada_name] = ada_mapping[ada_platform](ada_config, loop, event_queue)

        # ====== init message processor ======
        self.message_processor = MessageProcessor()

        # expose adapters and loop globally for runtime usage everywhere
        from core.services.runtime import set_adapters, set_loop, set_event_bus
        set_adapters(adapters)
        set_loop(loop)
        set_event_bus(event_queue)

        # ====== load all adapters ======
        for adapter in adapters:
            try:
                task = asyncio.create_task(adapters[adapter].start())
                task.add_done_callback(lambda t, name=adapters[adapter].name: logger.info(f"Started adapter {name}"))
            except Exception as e:
                logger.error(f"Failed to start adapter {adapters[adapter].name}: {e}")

        logger.info("All modules initialized, starting message processing loop...")

        # ====== message handling loop ======
        while True:
            msg: Union[KiraMessageEvent] = await event_queue.get()
            asyncio.create_task(self.message_processor.handle_message(msg))
