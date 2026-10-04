import asyncio
import base64
import secrets
from typing import Any, Optional, Union

import httpx
from Crypto.Cipher import AES

try:
    import botpy
    from botpy.gateway import BotWebSocket
except ImportError:
    botpy = None
    BotWebSocket = None

from core.adapter.access import ListAccessPolicy
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.chat import KiraIMSentResult, MessageChain
from core.logging_manager import get_logger

from .im import QQOfficialIMCapability
from .qr_login import QQOfficialQRCodeLoginHandler


logger = get_logger("qq_official_adapter", "blue")

QQ_OFFICIAL_BIND_HOST = "q.qq.com"


class _QQOfficialWebSocket(BotWebSocket if botpy else object):
    """Keep SDK heartbeat tasks within the owning client's lifecycle."""

    def __init__(self, session, connection, client):
        super().__init__(session, connection)
        self._client = client

    async def _send_heart(self, interval):
        self._client._track_task(asyncio.current_task())
        if self._client._closing:
            return
        await super()._send_heart(interval)


class _QQOfficialClient(botpy.Client if botpy else object):
    """Bridge QQ OpenAPI events to the adapter instance."""

    def __init__(self, adapter: "QQOfficialAdapter"):
        self.adapter = adapter
        self._closing = False
        self._tasks: set[asyncio.Task] = set()
        intents = botpy.Intents(public_messages=True)
        super().__init__(
            intents=intents,
            is_sandbox=adapter.sandbox,
            bot_log=False,
        )

    def _track_task(self, task: asyncio.Task) -> asyncio.Task:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    async def bot_connect(self, session):
        """Own the SDK's independent gateway runner until the entire task exits."""
        self._track_task(asyncio.current_task())
        if self._closing:
            raise asyncio.CancelledError
        gateway = _QQOfficialWebSocket(session, self._connection, self)
        try:
            await gateway.ws_connect()
        except (Exception, KeyboardInterrupt, SystemExit) as exc:
            if not self._closing:
                await gateway.on_error(exc)

    def _schedule_event(self, coro, event_name, *args, **kwargs):
        return self._track_task(super()._schedule_event(coro, event_name, *args, **kwargs))

    def ws_dispatch(self, event, *args, **kwargs):
        if not self._closing:
            super().ws_dispatch(event, *args, **kwargs)

    async def close(self):
        """Stop gateway, heartbeat and callback tasks as well as the SDK HTTP client."""
        self._closing = True
        try:
            await super().close()
        finally:
            current = asyncio.current_task()
            pending = [task for task in self._tasks if task is not current and not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

    async def on_group_at_message_create(self, message):
        if not self._closing and self.adapter.client is self:
            await self.adapter.im._handle_group_message(message)

    async def on_c2c_message_create(self, message):
        if not self._closing and self.adapter.client is self:
            await self.adapter.im._handle_direct_message(message)

    async def on_ready(self):
        if self._closing or self.adapter.client is not self:
            return
        robot_name = getattr(getattr(self, "robot", None), "name", "QQ official bot")
        logger.info(f"QQ official bot connected: {robot_name}")


class QQOfficialAdapter(BaseAdapter):
    """QQ official bot adapter backed by the QQ Bot Open Platform Gateway."""

    @classmethod
    def create_qrcode_login_handler(
        cls,
        config: dict[str, Any],
    ) -> QQOfficialQRCodeLoginHandler:
        return QQOfficialQRCodeLoginHandler(
            config,
            bind_host=QQ_OFFICIAL_BIND_HOST,
            generate_bind_key=cls._generate_bind_key,
            post_binding_json=cls._post_binding_json,
            decrypt_secret=cls._decrypt_bound_secret,
        )

    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)
        self.app_id = str(self.config.get("app_id", "")).strip()
        self.app_secret = str(self.config.get("app_secret", "")).strip()
        self.sandbox = bool(self.config.get("sandbox", False))
        self._client_task: Optional[asyncio.Task] = None
        self.client = None
        self.im = self.register_capability(IMCapability, QQOfficialIMCapability(self))
        self._configure_access()

    def _configure_access(self) -> None:
        mode = self.config.get("permission_mode", "allow_list")
        valid_mode = mode in ("allow_list", "deny_list")
        for scope in ("group", "user"):
            allow_list = self.config.get(f"{scope}_allow_list", [])
            deny_list = self.config.get(f"{scope}_deny_list", [])
            policy = ListAccessPolicy.from_lists(
                mode if valid_mode else "allow_list",
                allow_list=allow_list if valid_mode and isinstance(allow_list, list) else [],
                deny_list=deny_list if valid_mode and isinstance(deny_list, list) else [],
            )
            permission = "im.group.receive" if scope == "group" else "im.direct.receive"
            self.access.set_policy(
                capability_type=IMCapability, permission=permission, policy=policy,
            )

    async def start(self):
        if botpy is None:
            logger.error("QQ official bot requires qq-botpy. Install project dependencies first.")
            return
        if not self.app_id or not self.app_secret:
            logger.error(
                "QQ official bot AppID and AppSecret must both be configured; "
                "use QR-code login in WebUI before enabling the adapter"
            )
            return
        if self._client_task and not self._client_task.done():
            return
        if self.client is None:
            self.client = _QQOfficialClient(self)
        self._client_task = asyncio.create_task(
            self._run_client(), name=f"qq-official:{self.info.name}"
        )

    async def _run_client(self):
        try:
            await self.client.start(appid=self.app_id, secret=self.app_secret)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"QQ official bot connection stopped: {exc}")

    @staticmethod
    def _generate_bind_key() -> str:
        return base64.b64encode(secrets.token_bytes(32)).decode("ascii")

    @staticmethod
    def _decrypt_bound_secret(encrypted_secret: str, bind_key: str) -> str:
        """Decrypt the AES-GCM AppSecret returned by QQ's binding API."""
        try:
            key = base64.b64decode(bind_key, validate=True)
            payload = base64.b64decode(encrypted_secret, validate=True)
        except Exception as exc:
            raise ValueError("QQ official bot binding response is not valid base64") from exc
        if len(key) != 32 or len(payload) <= 28:
            raise ValueError("QQ official bot binding response has an invalid encrypted secret")
        nonce, ciphertext, tag = payload[:12], payload[12:-16], payload[-16:]
        try:
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception as exc:
            raise ValueError("QQ official bot binding secret could not be decrypted") from exc

    @staticmethod
    async def _post_binding_json(path: str, payload: dict[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            response = await client.post(
                f"https://{QQ_OFFICIAL_BIND_HOST}{path}",
                json=payload,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        if not isinstance(data, dict) or int(data.get("retcode", -1)) != 0:
            message = data.get("msg", "Unknown QQ official bot binding error") if isinstance(data, dict) else "Invalid binding response"
            raise RuntimeError(f"QQ official bot binding request failed: {message}")
        result = data.get("data")
        if not isinstance(result, dict):
            raise RuntimeError("QQ official bot binding response is missing data")
        return result

    async def stop(self):
        if self.client:
            try:
                await self.client.close()
            except Exception as exc:
                logger.warning(f"Failed to close QQ official bot client: {exc}")
        if self._client_task and not self._client_task.done():
            self._client_task.cancel()
            try:
                await self._client_task
            except asyncio.CancelledError:
                pass
        self._client_task = None
        self.client = None

    def get_client(self):
        return self.client

    async def send_group_message(
        self, group_id: Union[int, str], send_message_obj: MessageChain,
    ) -> Optional[KiraIMSentResult]:
        return await self.im.send_group_message(group_id, send_message_obj)

    async def send_direct_message(
        self, user_id: Union[int, str], send_message_obj: MessageChain,
    ) -> Optional[KiraIMSentResult]:
        return await self.im.send_direct_message(user_id, send_message_obj)
