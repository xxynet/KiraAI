import asyncio
import json
import psutil
import socket
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
            host = webui_config["host"]
            port = webui_config["port"]

            if host not in ("localhost", "127.0.0.1"):
                try:
                    addresses = self._get_ip_addresses()
                    self.logger.info(f"KiraAI WebUI started at:")
                    for address in addresses:
                        self.logger.info(f"{address[0]}: http://{address[1]}:{port}")
                except Exception as e:
                    self.logger.warning(f"Failed to get ip addresses: {e}")

            tasks = asyncio.gather(
                self.lifecycle.init_and_run_system(),
                self.webui.run(host, port)
            )
            await tasks
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.logger.info("✨ Exiting KiraAI...")
            await self.lifecycle.stop()
            self.logger.info("✔ Exited KiraAI")

    @staticmethod
    def _get_ip_addresses():
        ip_addresses = []
        for interface, interface_addresses in psutil.net_if_addrs().items():
            for address in interface_addresses:
                if not address.family == socket.AF_INET:
                    continue
                if address.address.startswith("127"):
                    ip_addresses.append(("Local", address.address))
                    continue
                ip_addresses.append((interface, address.address))
        return ip_addresses

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
