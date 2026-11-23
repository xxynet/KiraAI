import asyncio
import socket
import sys

import psutil

from core.logging_manager import get_logger
from webui.app import KiraWebUI
from webui.utils import _load_webui_config

from .lifecycle import KiraLifecycle
from .statistics import Statistics


class KiraLauncher:
    """KiraAI Launcher"""
    def __init__(self, ignore_webui_version_check: bool = False, disable_webui_auth: bool = False):
        self.lifecycle: KiraLifecycle | None = None
        self.stats: Statistics | None = None
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

        self.stats = Statistics()

        self.lifecycle = KiraLifecycle(stats=self.stats)

        # ====== ensure frontend dist ======
        from core.utils.dist_checker import ensure_dist
        await ensure_dist(ignore_webui_version_check=self.ignore_webui_version_check)

        self.webui = KiraWebUI(lifecycle=self.lifecycle, disable_auth=self.disable_webui_auth)
        if self.webui.access_token_generated:
            print(f"Access Token: {self.webui.access_token}", flush=True)
        elif self.webui.access_token is None:
            self.logger.warning("WebUI access token unavailable. Reset it in data/webui.json and restart KiraAI.")

        webui_config = self._load_webui_config()

        try:
            host = webui_config.get("host", "0.0.0.0")
            port = webui_config.get("port", 5267)

            if self.disable_webui_auth and host not in ("localhost", "127.0.0.1"):
                self.logger.warning("Auth disabled — forcing host to 127.0.0.1 for security")
                host = "127.0.0.1"

            tasks = asyncio.gather(
                self.lifecycle.init_and_run_system(
                    on_initialized=lambda: self._log_webui_info(host, port),
                ),
                self.webui.run(host, port)
            )
            await tasks
        except (asyncio.CancelledError, KeyboardInterrupt):
            self.logger.info("✨ Exiting KiraAI...")
            await self.lifecycle.stop()
            self.logger.info("✔ Exited KiraAI")

    def _log_webui_info(self, host: str, port: int):
        self.logger.info(f"WebUI server started at http://{host}:{port}")
        if host not in ("localhost", "127.0.0.1"):
            try:
                addresses = sorted(self._get_ip_addresses(), key=lambda item: item[0] != "Local")
                self.logger.info("KiraAI WebUI started at:")
                for interface, address in addresses:
                    self.logger.info(f"{interface}: http://{address}:{port}")
            except Exception as e:
                self.logger.warning(f"Failed to get ip addresses: {e}")

    @staticmethod
    def _get_ip_addresses():
        ip_addresses = []
        for interface, interface_addresses in psutil.net_if_addrs().items():
            for address in interface_addresses:
                if address.family != socket.AF_INET:
                    continue
                if address.address.startswith("127"):
                    ip_addresses.append(("Local", address.address))
                    continue
                ip_addresses.append((interface, address.address))
        return ip_addresses

    @staticmethod
    def _load_webui_config() -> dict:
        """Load listener settings, falling back to defaults if config is damaged."""
        try:
            return _load_webui_config()
        except (OSError, ValueError, RecursionError):
            return {}
