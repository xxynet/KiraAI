import asyncio
from typing import Any, Dict, Union, Optional

from .lifecycle import KiraLifecycle
from .statistics import Statistics


class KiraLauncher:
    """KiraAI Launcher"""
    def __init__(self):
        self.lifecycle: Optional[KiraLifecycle] = None
        self.stats: Optional[Statistics] = None

    async def start(self):
        self.stats = Statistics()

        self.lifecycle = KiraLifecycle(stats=self.stats)
        await asyncio.gather(
            self.lifecycle.init_and_run_system(),
            self.lifecycle.schedule_tasks(),
        )
