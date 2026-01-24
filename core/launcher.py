import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Union, Optional
import uvicorn

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path

from .lifecycle import KiraLifecycle
from .statistics import Statistics
from webui.app import KiraWebUI


class KiraLauncher:
    """KiraAI Launcher"""
    def __init__(self):
        self.lifecycle: Optional[KiraLifecycle] = None
        self.stats: Optional[Statistics] = None
        self.webui = None
        self.logger = get_logger("launcher", "blue")

    async def start(self):
        self.stats = Statistics()

        self.lifecycle = KiraLifecycle(stats=self.stats)

        # ====== init WebUI ======
        webui_config = self._load_webui_config()

        self.webui = KiraWebUI(lifecycle=self.lifecycle)

        self.logger.info(f"WebUI server started at http://{webui_config['host']}:{webui_config['port']}")

        try:
            tasks = asyncio.gather(
                self.lifecycle.init_and_run_system(),
                self.webui.run(webui_config["host"],
                               webui_config["port"])
            )
            await tasks
        except asyncio.CancelledError:
            self.logger.info("✨ Exiting KiraAI...")
            await self.lifecycle.stop()
            self.logger.info("✔ Exited KiraAI")

    @staticmethod
    def _load_webui_config() -> dict:
        """Load WebUI configuration from data/webui.json"""
        config_path = get_data_path() / "webui.json"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps({
                    "host": "0.0.0.0",
                    "port": 5267
                }))
            return {"host": "0.0.0.0", "port": 5267}
