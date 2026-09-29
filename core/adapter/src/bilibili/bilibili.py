from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from bilibili_api import Credential, user

from core.adapter.base import BaseAdapter
from core.adapter.capabilities import FeedCapability
from core.adapter.context import AdapterContext
from core.logging_manager import get_logger

from .client import get_bilibili_client
from .feed import BiliBiliFeedCapability
from .qr_login import BiliBiliQRCodeLoginHandler


class BiliBiliAdapter(BaseAdapter):
    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)
        self.logger = get_logger(self.info.name, "blue")
        self.bot_uid = self.config.get("bot_uid") or self.config.get("dedeuserid")
        self.credential = Credential(
            sessdata=self.config.get("sessdata") or None,
            bili_jct=self.config.get("bili_jct") or None,
            buvid3=self.config.get("buvid3") or None,
            dedeuserid=self.config.get("dedeuserid") or None,
            ac_time_value=self.config.get("ac_time_value") or None,
        )
        self._client = None
        self.listening_task: asyncio.Task | None = None
        self.feed = self.register_capability(FeedCapability, BiliBiliFeedCapability(self))

    @classmethod
    def create_qrcode_login_handler(
        cls, config: dict[str, Any],
    ) -> BiliBiliQRCodeLoginHandler:
        return BiliBiliQRCodeLoginHandler()

    async def start(self) -> None:
        self._client = get_bilibili_client()
        await self._log_login_status()
        if self.config.get("listening_bvid"):
            self.listening_task = asyncio.create_task(self._start_listening())
            try:
                await self.listening_task
            finally:
                self.listening_task = None

    async def _log_login_status(self) -> None:
        if not self.credential.sessdata:
            self.logger.info("Bilibili login status: not logged in")
            return
        try:
            account = await user.get_self_info(self.credential)
        except Exception as exc:
            self.logger.warning(
                f"Bilibili login status verification failed: {type(exc).__name__}: {str(exc)[:100]}"
            )
            return
        if account.get("mid"):
            self.bot_uid = str(account["mid"])
        self.logger.info(
            f"Bilibili login status: logged in, nickname={account.get('name', 'unknown')}, "
            f"uid={account.get('mid', 'unknown')}"
        )

    async def _start_listening(self) -> None:
        interval = max(1.0, float(self.config.get("listening_interval") or 20.0))
        while True:
            try:
                await self.feed.check_new_comments()
            except Exception as exc:
                self.logger.error(f"Bilibili 监听出错: {exc}")
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        task = self.listening_task
        if task and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.listening_task = None
        # bilibili-api owns the shared per-event-loop client used by other accounts.
        self._client = None

    def get_client(self) -> Any:
        return self._client
