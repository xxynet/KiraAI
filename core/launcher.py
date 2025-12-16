import asyncio
from typing import Any, Dict, Union, Optional

from core.logging_manager import get_logger

from .lifecycle import KiraLifecycle
from .statistics import Statistics


class KiraLauncher:
    """KiraAI Launcher"""
    def __init__(self):
        self.lifecycle: Optional[KiraLifecycle] = None
        self.stats: Optional[Statistics] = None
        self.logger = get_logger("launcher", "blue")

    async def start(self):
        self.stats = Statistics()

        self.lifecycle = KiraLifecycle(stats=self.stats)
        try:
            await asyncio.gather(
                self.lifecycle.init_and_run_system(),
                self.lifecycle.schedule_tasks(),
            )
        except asyncio.CancelledError:
            self.logger.info("✨ Exiting KiraAI...")
            await self.lifecycle.stop()
            self.logger.info("✔ Exited KiraAI")
