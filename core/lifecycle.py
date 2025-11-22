import asyncio
from typing import Any, Dict, Union, Optional

from core.logging_manager import get_logger
from core.config_loader import global_config

from adapters.qq.qq_reply import QQAdapter
from adapters.telegram.tg import TelegramAdapter

from utils.message_utils import BotPrivateMessage, BotGroupMessage
from core.sticker_manager import sticker_manager


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self):
        pass

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
        event_bus: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # ====== init adapter mapping ======
        ada_mapping = {'QQ': QQAdapter, 'Telegram': TelegramAdapter}
        adapters: Dict[str, Any] = {}

        # ====== load adapter config ======
        adas_config = global_config["ada_config"]
        for ada_name in adas_config:
            ada_config = adas_config[ada_name]
            ada_platform = ada_config["platform"]
            adapters[ada_name] = ada_mapping[ada_platform](ada_config, loop, event_bus)

        # ====== init message processor ======
        # message_processor = MessageProcessor()
        from core.message_manager import message_processor

        # expose adapters and loop globally for runtime usage everywhere
        from core.services.runtime import set_adapters as rt_set_adapters, set_loop as rt_set_loop
        rt_set_adapters(adapters)
        rt_set_loop(loop)

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
            msg: Union[BotPrivateMessage, BotGroupMessage] = await event_bus.get()
            asyncio.create_task(message_processor.handle_message(msg))
