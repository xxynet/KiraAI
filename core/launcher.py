import asyncio
from typing import Any, Dict, Union, Optional

from .lifecycle import KiraLifecycle


class KiraLauncher:
    """KiraAI Launcher"""
    def __init__(self):
        self.lifecycle: Optional[KiraLifecycle] = None

    async def start(self):
        self.lifecycle = KiraLifecycle()
        await asyncio.gather(
            self.lifecycle.init_and_run_system(),
            self.lifecycle.schedule_tasks(),
        )
