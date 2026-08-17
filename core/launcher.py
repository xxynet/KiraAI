import asyncio
import json
import psutil
import socket
import sys
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
    def __init__(self, ignore_webui_version_check: bool = False, disable_webui_auth: bool = False):
        self.lifecycle: Optional[KiraLifecycle] = None
        self.stats: Optional[Statistics] = None
        self.webui = None
        self.ignore_webui_version_check = ignore_webui_version_check
        self.disable_webui_auth = disable_webui_auth
        self.logger = get_logger("launcher", "blue")

    async def start(self):
        # Silence harmless "ConnectionResetError [WinError 10054]" noise from the
        # Windows ProactorEventLoop when clients drop the TCP connection before
        # the server finishes draining the socket. The transport is already
        # being torn down, so the error is informational only. Gate strictly on
        # win32 + ProactorEventLoop so real ConnectionResetErrors on other
        # platforms still surface in logs.
        loop = asyncio.get_running_loop()
        default_handler = loop.get_exception_handler()
        proactor_cls = getattr(asyncio, "ProactorEventLoop", None)
        is_proactor = (
            sys.platform == "win32"
            and proactor_cls is not None
            and isinstance(loop, proactor_cls)
        )

        def _suppress_proactor_reset(lp, context):
            exc = context.get("exception")
            if is_proactor and isinstance(exc, ConnectionResetError):
                self.logger.debug("Suppressed Proactor ConnectionResetError: %s", exc)
                return
            if default_handler is not None:
                default_handler(lp, context)
            else:
                lp.default_exception_handler(context)

        loop.set_exception_handler(_suppress_proactor_reset)

        running_tasks: list[asyncio.Task] = []

        self.stats = Statistics()

        self.lifecycle = KiraLifecycle(stats=self.stats)

        # ====== init WebUI ======
        webui_config = self._load_webui_config()

        # ====== ensure frontend dist ======
        from core.utils.dist_checker import ensure_dist
        await ensure_dist(ignore_webui_version_check=self.ignore_webui_version_check)

        self.webui = KiraWebUI(lifecycle=self.lifecycle, disable_auth=self.disable_webui_auth)

        try:
            host = webui_config.get("host", "0.0.0.0")
            port = webui_config.get("port", 5267)

            if self.disable_webui_auth and host not in ("localhost", "127.0.0.1"):
                self.logger.warning("Auth disabled — forcing host to 127.0.0.1 for security")
                host = "127.0.0.1"

            self.logger.info(f"WebUI server started at http://{host}:{port}")
            access_token = self.webui.access_token

            if host not in ("localhost", "127.0.0.1"):
                try:
                    addresses = self._get_ip_addresses()
                    self.logger.info(f"KiraAI WebUI started at:")
                    for address in addresses:
                        self.logger.info(f"{address[0]}: http://{address[1]}:{port}")
                    self.logger.info(f"Access Token: {access_token}")
                except Exception as e:
                    self.logger.warning(f"Failed to get ip addresses: {e}")

            running_tasks = [
                asyncio.create_task(self.lifecycle.init_and_run_system(), name="kira_system"),
                asyncio.create_task(self.webui.run(host, port), name="kira_webui"),
            ]
            await asyncio.gather(*running_tasks)
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.logger.info("✨ Exiting KiraAI...")
        except Exception as e:
            self.logger.error(f"KiraAI stopped due to an unexpected error: {e}", exc_info=True)
        finally:
            if self.lifecycle is not None:
                try:
                    await self.lifecycle.stop()
                except Exception as e:
                    self.logger.error(f"Error during shutdown: {e}", exc_info=True)
            # asyncio.gather() leaves siblings running when one of them fails
            for task in running_tasks:
                task.cancel()
            if running_tasks:
                await asyncio.gather(*running_tasks, return_exceptions=True)
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

    def _load_webui_config(self) -> dict:
        """Load WebUI configuration from data/webui.json"""
        default_config = {"host": "0.0.0.0", "port": 5267}
        config_path = get_data_path() / "webui.json"
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                self.logger.warning(
                    f"Failed to read {config_path}, falling back to defaults "
                    f"(host={default_config['host']}, port={default_config['port']}): {e}"
                )
                return dict(default_config)
            if not isinstance(config, dict):
                self.logger.warning(
                    f"{config_path} must contain a JSON object, falling back to defaults"
                )
                return dict(default_config)
            return config
        else:
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write(json.dumps(default_config))
            return dict(default_config)
