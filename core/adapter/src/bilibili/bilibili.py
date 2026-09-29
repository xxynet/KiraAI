from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from bilibili_api import Credential, user
from bilibili_api.session import EventType, Session

from core.adapter.access import ListAccessPolicy
from core.adapter.base import AdapterTargetId, BaseAdapter
from core.adapter.capabilities import FeedCapability, IMCapability
from core.adapter.context import AdapterContext
from core.chat import KiraIMSentResult, MessageChain
from core.logging_manager import get_logger

from .client import get_bilibili_client
from .feed import BiliBiliFeedCapability
from .im import BiliBiliIMCapability
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
        self._dm_session: Session | None = None
        self._dm_task: asyncio.Task | None = None
        self._user_info_cache: dict[int, dict] = {}
        if self.config.get("enable_im", True):
            self.message_types = ["text", "img", "at", "reply", "emoji", "share_video"]

            self.im = self.register_capability(IMCapability, BiliBiliIMCapability(self))
            policy = ListAccessPolicy.from_lists(
                self.config.get("permission_mode", "allow_list"),
                allow_list=self.config.get("user_allow_list", []),
                deny_list=self.config.get("user_deny_list", []),
            )
            self.access.set_policy(
                capability_type=IMCapability, permission="im.direct.receive", policy=policy,
            )

    @classmethod
    def create_qrcode_login_handler(
        cls, config: dict[str, Any],
    ) -> BiliBiliQRCodeLoginHandler:
        return BiliBiliQRCodeLoginHandler()

    async def _load_emoji_dict(self) -> None:
        """Load common native tokens from Bilibili's default emote package.

        Source: https://api.bilibili.com/x/emote/package?ids=1&business=reply
        Snapshot retrieved on 2026-09-29, excluding game and franchise emotes; retained IDs and text are unchanged.
        """
        if self.emoji_dict is None:
            contents = await asyncio.to_thread(Path(__file__).with_name("emoji.json").read_text, encoding="utf-8")
            self.emoji_dict = json.loads(contents)

    async def start(self) -> None:
        if self.get_capabilities(IMCapability):
            await self._load_emoji_dict()
        self._client = get_bilibili_client()
        await self._log_login_status()
        tasks = []
        if self.config.get("listening_bvid"):
            self.listening_task = asyncio.create_task(self._start_listening())
            tasks.append(self.listening_task)
        if self.get_capabilities(IMCapability):
            self._dm_task = asyncio.create_task(self._start_im())
            tasks.append(self._dm_task)
        if tasks:
            try:
                await asyncio.gather(*tasks)
            finally:
                await self._stop_listeners()

    async def _start_im(self) -> None:
        if not self.credential.sessdata:
            self.logger.error("BiliBili credential (sessdata) is not set")
            return
        session = Session(self.credential, debug=False)
        self._dm_session = session
        handlers: set[asyncio.Task] = set()
        # The SDK logs raw messages; use adapter lifecycle logs without message bodies.
        session.logger = logging.Logger(f"{__name__}.session", level=logging.CRITICAL)
        session.logger.addHandler(logging.NullHandler())
        for event_type, kind in (
            (EventType.TEXT, "text"),
            (EventType.PICTURE, "picture"),
            (EventType.SHARE_VIDEO, "share_video"),
        ):
            async def handle(event, msg_kind=kind):
                if self._dm_session is not session:
                    return
                task = asyncio.current_task()
                handlers.add(task)
                try:
                    await self.im._handle_incoming_event(event, msg_kind)
                finally:
                    handlers.discard(task)
            session.on(event_type)(handle)
        try:
            self.logger.info(f"Start listening DM for BiliBili user {self.bot_uid}")
            await session.start(exclude_self=True)
        except Exception as exc:
            self.logger.error(f"Failed to start BiliBili DM adapter: {type(exc).__name__}")
        finally:
            self._dm_session = None
            pending = list(handlers)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            if session.get_status() == 1:
                session.close()
            if session.sched.running:
                session.sched.shutdown(wait=False)
            self.logger.info(f"Stopped BiliBili DM adapter for {self.bot_uid}")

    async def _stop_listeners(self) -> None:
        tasks = [task for task in (self.listening_task, self._dm_task) if task is not None]
        self.listening_task = None
        self._dm_task = None
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

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
        await self._stop_listeners()
        # bilibili-api owns the shared per-event-loop client used by other accounts.
        self._client = None

    def get_client(self) -> Any:
        return self._client

    async def send_direct_message(
        self, user_id: AdapterTargetId, send_message_obj: MessageChain,
    ) -> KiraIMSentResult | None:
        """Preserve the legacy adapter-level sending API."""
        return await self.get_capability(IMCapability).send_direct_message(user_id, send_message_obj)
