from __future__ import annotations

import asyncio
from threading import Lock
from typing import Any

from core.adapter.access import ListAccessPolicy
from core.adapter.base import AdapterTargetId, BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.logging_manager import get_logger
from core.chat import MessageChain, KiraIMSentResult

from .im import WeixinOCIMCapability
from .qr_login import WeixinOCQRCodeLoginHandler
from .weixin_oc_client import WeixinOCClient


_account_state_lock = Lock()


class TypingSessionState:
    """Reserved state for a typing session."""
    def __init__(self):
        self.ticket = None
        self.ticket_context_token = None
        self.refresh_after = 0.0
        self.keepalive_task = None
        self.cancel_task = None
        self.owners = set()
        self.lock = asyncio.Lock()


class WeixinOCAdapter(BaseAdapter):
    """Own the account, client and lifecycle of one personal WeChat connection."""

    @classmethod
    def create_qrcode_login_handler(
        cls,
        config: dict[str, Any],
    ) -> WeixinOCQRCodeLoginHandler:
        return WeixinOCQRCodeLoginHandler(config)

    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)
        self.logger = get_logger(self.info.name, "green")

        self.base_url = str(
            self.config.get("weixin_oc_base_url", "https://ilinkai.weixin.qq.com")
        ).rstrip("/")
        self.cdn_base_url = str(
            self.config.get(
                "weixin_oc_cdn_base_url",
                "https://novac2c.cdn.weixin.qq.com/c2c",
            )
        ).rstrip("/")
        self.api_timeout_ms = int(self.config.get("weixin_oc_api_timeout_ms", 15000))
        self.long_poll_timeout_ms = int(
            self.config.get("weixin_oc_long_poll_timeout_ms", 35000)
        )

        self._shutdown_event = asyncio.Event()
        self._run_task: asyncio.Task | None = None
        self._close_task: asyncio.Task | None = None
        self._stop_task: asyncio.Task | None = None
        self._sync_buf = ""
        self._context_tokens: dict[str, str] = {}
        self._typing_states: dict[str, TypingSessionState] = {}
        self._last_inbound_error = ""
        self._typing_keepalive_interval_s = max(
            1, int(self.config.get("weixin_oc_typing_keepalive_interval", 5))
        )
        self._typing_ticket_ttl_s = max(
            5, int(self.config.get("weixin_oc_typing_ticket_ttl", 60))
        )

        self.token = str(self.config.get("weixin_oc_token", "")).strip() or None
        self.account_id = str(self.config.get("weixin_oc_account_id", "")).strip() or None
        self._sync_buf = str(self.config.get("weixin_oc_sync_buf", "")).strip()

        self.client = WeixinOCClient(
            adapter_id=self.info.name,
            base_url=self.base_url,
            cdn_base_url=self.cdn_base_url,
            api_timeout_ms=self.api_timeout_ms,
            token=self.token,
        )

        self.im = self.register_capability(IMCapability, WeixinOCIMCapability(self))
        self._configure_access()

        if self.token:
            self.logger.info("weixin_oc adapter loaded with existing token")
        else:
            self.logger.warning("weixin_oc adapter initialized without a bot token")

    def _sync_client_state(self) -> None:
        self.client.base_url = self.base_url
        self.client.cdn_base_url = self.cdn_base_url
        self.client.api_timeout_ms = self.api_timeout_ms
        self.client.token = self.token

    def _configure_access(self) -> None:
        mode = self.config.get("permission_mode", "allow_list")
        valid_mode = mode in ("allow_list", "deny_list")
        allow_list = self.config.get("user_allow_list", [])
        deny_list = self.config.get("user_deny_list", [])
        self.access.set_policy(
            capability_type=IMCapability,
            permission="im.direct.receive",
            policy=ListAccessPolicy.from_lists(
                mode if valid_mode else "allow_list",
                allow_list=allow_list if valid_mode and isinstance(allow_list, list) else [],
                deny_list=deny_list if valid_mode and isinstance(deny_list, list) else [],
            ),
        )

    async def _poll_inbound_updates(self) -> None:
        data = await self.client.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {
                    "channel_version": "kiraai",
                },
                "get_updates_buf": self._sync_buf,
            },
            token_required=True,
            timeout_ms=self.long_poll_timeout_ms,
        )
        ret = int(data.get("ret") or 0)
        errcode = int(data.get("errcode") or 0)
        if ret != 0:
            # Keep server diagnostics free of response bodies and credentials.
            self._last_inbound_error = f"ret={ret}, errcode={errcode}"
            self.logger.warning(
                "weixin_oc(%s): getupdates error: %s",
                self.info.name,
                self._last_inbound_error,
            )
            return
        if errcode != 0:
            # Keep server diagnostics free of response bodies and credentials.
            self._last_inbound_error = f"ret={ret}, errcode={errcode}"
            # Expired sessions require a new QR-code login.
            if errcode == -14:
                self.logger.warning(
                    "weixin_oc(%s): session timeout, clearing invalid token",
                    self.info.name,
                )
                self.token = None
                self._sync_buf = ""
                self._context_tokens.clear()
                await self._save_account_state()
                return
            self.logger.warning(
                "weixin_oc(%s): getupdates error: %s",
                self.info.name,
                self._last_inbound_error,
            )
            return

        if data.get("get_updates_buf"):
            self._sync_buf = str(data.get("get_updates_buf"))
            # Keep the cursor in memory between account-state saves.

        for msg in data.get("msgs", []) if isinstance(data.get("msgs"), list) else []:
            if self._shutdown_event.is_set():
                return
            if not isinstance(msg, dict):
                continue
            await self.im._handle_inbound_message(msg)

    async def _save_account_state(self) -> None:
        """Persist account state without blocking the event loop."""
        self.info.config["weixin_oc_token"] = self.token or ""
        self.info.config["weixin_oc_account_id"] = self.account_id or ""
        self.info.config["weixin_oc_sync_buf"] = self._sync_buf
        self.info.config["weixin_oc_base_url"] = self.base_url
        self._sync_client_state()
        try:
            await asyncio.to_thread(self._persist_account_state, dict(self.info.config))
        except Exception as exc:
            self.logger.error(
                "weixin_oc(%s): failed to save account state: %s",
                self.info.name, type(exc).__name__,
            )

    def _persist_account_state(self, config: dict[str, Any]) -> None:
        from core.config.config_loader import KiraConfig

        # Serialize account updates across this platform's worker threads.
        with _account_state_lock:
            kira_config = KiraConfig()
            adapters = kira_config.get("adapters", {})
            if self.info.adapter_id in adapters:
                adapters[self.info.adapter_id]["config"] = config
                kira_config.save_config()
                self.logger.info("weixin_oc(%s): account state saved", self.info.name)
            else:
                self.logger.warning("weixin_oc(%s): adapter not found in config", self.info.name)

    async def start(self) -> None:
        if self._stop_task and not self._stop_task.done():
            return
        if self._run_task and not self._run_task.done():
            return
        if self._close_task and not self._close_task.done():
            return
        if not self.token:
            self.logger.error(
                "weixin_oc(%s): bot token is required; use QR-code login in "
                "WebUI before enabling the adapter",
                self.info.name,
            )
            return
        self._shutdown_event.clear()
        self._sync_client_state()
        self._close_task = None
        self._stop_task = None
        self._run_task = asyncio.create_task(
            self._run_loop(), name=f"weixin-oc:{self.info.name}",
        )
        self._run_task.add_done_callback(self._on_run_done)

    def _on_run_done(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self.logger.error(
                    "weixin_oc(%s): run loop failed: %s",
                    self.info.name, type(exc).__name__,
                )

    async def _run_loop(self) -> None:
        try:
            while not self._shutdown_event.is_set():
                if not self.token:
                    self.logger.error(
                        "weixin_oc(%s): bot token is no longer valid; update "
                        "credentials in WebUI before enabling the adapter again",
                        self.info.name,
                    )
                    return
                try:
                    await self._poll_inbound_updates()
                except asyncio.TimeoutError:
                    self.logger.debug(
                        "weixin_oc(%s): inbound long-poll timeout", self.info.name,
                    )
                except Exception as exc:
                    self.logger.error(
                        "weixin_oc(%s): poll inbound failed, retry in 5s: %s",
                        self.info.name, type(exc).__name__,
                    )
                    await asyncio.sleep(5)
        finally:
            await self._close_client()

    async def _close_client(self) -> None:
        # The runner and stop operation share one client close task.
        if self._close_task is None:
            self._close_task = asyncio.create_task(self.client.close())
        await asyncio.shield(self._close_task)

    async def stop(self) -> None:
        self._shutdown_event.set()
        if self._stop_task is None:
            self._stop_task = asyncio.create_task(self._stop())
        await asyncio.shield(self._stop_task)

    async def _stop(self) -> None:
        task = self._run_task
        try:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        finally:
            try:
                await self._close_client()
            finally:
                self._run_task = None
        self.logger.info("weixin_oc(%s): adapter stopped", self.info.name)

    def get_client(self) -> WeixinOCClient:
        return self.client

    async def send_group_message(
        self, group_id: AdapterTargetId, send_message_obj: MessageChain,
    ) -> KiraIMSentResult:
        return await self.im.send_group_message(group_id, send_message_obj)

    async def send_direct_message(
        self, user_id: AdapterTargetId, send_message_obj: MessageChain,
    ) -> KiraIMSentResult:
        return await self.im.send_direct_message(user_id, send_message_obj)
