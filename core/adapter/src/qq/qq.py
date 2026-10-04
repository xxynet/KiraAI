import asyncio
import json
from pathlib import Path
from typing import Any, Callable, Awaitable

from core.adapter.access import ListAccessPolicy
from core.adapter.base import AdapterTargetId, BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.chat import KiraIMSentResult, MessageChain
from core.logging_manager import get_logger

from .im import QQIMCapability
from .napcat_client import NapCatWebSocketClient


class QQAdapter(BaseAdapter):
    """Own the configuration, OneBot client and lifecycle of one QQ account."""

    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)
        self.emoji_dict = self._load_dict(Path(__file__).with_name("emoji.json"))
        self.message_types = ["text", "img", "at", "reply", "record", "emoji", "sticker", "poke", "file", "video", "forward"]
        self.logger = get_logger(self.info.name, "blue")
        self.debug_mode = self.config.get("debug_mode", False)
        self.debug_mode_list = self.config.get("debug_mode_list", [])
        self.permanently_disconnected = False
        self._client_task: asyncio.Task | None = None
        self._client_close_task: asyncio.Task | None = None
        self._event_tasks: set[asyncio.Task] = set()
        self._stopping = False
        self.im = self.register_capability(IMCapability, QQIMCapability(self))
        self._configure_access()
        self.bot = self._create_client()

    @staticmethod
    def _load_dict(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _configure_access(self) -> None:
        mode = self.config.get("permission_mode", "allow_list")
        valid_mode = mode in ("allow_list", "deny_list")
        for scope, permission in (
            ("group", "im.group.receive"),
            ("user", "im.direct.receive"),
        ):
            allow_list = self.config.get(f"{scope}_allow_list", [])
            deny_list = self.config.get(f"{scope}_deny_list", [])
            policy = ListAccessPolicy.from_lists(
                mode if valid_mode else "allow_list",
                allow_list=allow_list if valid_mode and isinstance(allow_list, list) else [],
                deny_list=deny_list if valid_mode and isinstance(deny_list, list) else [],
            )
            self.access.set_policy(
                capability_type=IMCapability, permission=permission, policy=policy,
            )

    def _create_client(self) -> NapCatWebSocketClient:
        client = NapCatWebSocketClient()
        client.on_permanent_disconnect = lambda: self._on_permanent_disconnect(client)

        @client.group_event()
        async def on_group_message(msg: dict):
            await self._handle_im_event(client, self.im._on_group_message, msg)

        @client.private_event()
        async def on_private_message(msg: dict):
            await self._handle_im_event(client, self.im._on_private_message, msg)

        @client.notice_event()
        async def on_notice_message(msg: dict):
            await self._handle_im_event(client, self.im._on_notice_message, msg)

        return client

    async def _handle_im_event(
        self,
        client: NapCatWebSocketClient,
        handler: Callable[[dict], Awaitable[None]],
        msg: dict,
    ) -> None:
        if self._stopping or client is not self.bot:
            return
        task = asyncio.current_task()
        if task is None:
            return
        self._event_tasks.add(task)
        try:
            await handler(msg)
        finally:
            self._event_tasks.discard(task)

    def _on_permanent_disconnect(self, client: NapCatWebSocketClient) -> None:
        if self._stopping or client is not self.bot:
            return
        self.permanently_disconnected = True
        self.logger.error(
            f"NapCat 连接永久失败（重连次数已达上限），适配器 {self.info.name} 已停止接收消息，"
            "请检查 NapCat 是否在运行、ws_uri / token 配置是否正确"
        )

    async def start(self) -> None:
        if self._client_task and not self._client_task.done():
            return
        if self.bot.shutdown_event.is_set():
            self.bot = self._create_client()
            self._client_close_task = None
        self._stopping = False
        self.permanently_disconnected = False
        self._client_task = asyncio.create_task(
            self._run_client(self.bot), name=f"qq:{self.info.name}",
        )
        self._client_task.add_done_callback(self._on_client_done)

    def _on_client_done(self, task: asyncio.Task) -> None:
        if not task.cancelled():
            exc = task.exception()
            if exc is not None:
                self.logger.error(f"QQ client stopped with an error ({type(exc).__name__})")

    async def _run_client(self, client: NapCatWebSocketClient) -> None:
        try:
            await client.run(
                bt_uin=self.config["bot_pid"],
                ws_uri=self.config["ws_uri"],
                ws_token=self.config["ws_token"],
            )
        finally:
            self._stopping = True
            try:
                await self._close_client(client)
            finally:
                await self._cancel_event_tasks()

    async def _close_client(self, client: NapCatWebSocketClient) -> None:
        # stop() and the runner's finally block join the same close operation.
        if self._client_close_task is None:
            self._client_close_task = asyncio.create_task(client.close())
        await asyncio.shield(self._client_close_task)

    async def _cancel_event_tasks(self) -> None:
        current = asyncio.current_task()
        tasks = [task for task in self._event_tasks if task is not current and not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def stop(self) -> None:
        self._stopping = True
        try:
            await self._close_client(self.bot)
        finally:
            task = self._client_task
            if task and task is not asyncio.current_task() and not task.done():
                task.cancel()
                await asyncio.wait({task})
            await self._cancel_event_tasks()
            self._client_task = None

    def get_client(self) -> NapCatWebSocketClient:
        return self.bot

    async def send_group_message(
        self, group_id: AdapterTargetId, send_message_obj: MessageChain,
    ) -> KiraIMSentResult:
        return await self.im.send_group_message(group_id, send_message_obj)

    async def send_direct_message(
        self, user_id: AdapterTargetId, send_message_obj: MessageChain,
    ) -> KiraIMSentResult:
        return await self.im.send_direct_message(user_id, send_message_obj)
