import asyncio
import base64
import hashlib
import io
import mimetypes
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union
from urllib.parse import quote

import httpx
from Crypto.Cipher import AES

try:
    import botpy
except ImportError:
    botpy = None

try:
    import qrcode as qrcode_lib
except ImportError:
    qrcode_lib = None

from core.adapter.adapter_utils import IMAdapter
from core.chat import KiraIMMessage, KiraIMSentResult, KiraMessageEvent, MessageChain
from core.chat import Group, User
from core.chat.message_elements import At, Emoji, File, Image, Record, Reply, Text, Video
from core.logging_manager import get_logger


logger = get_logger("qq_official_adapter", "blue")

QQ_OFFICIAL_BIND_HOST = "q.qq.com"
QQ_OFFICIAL_QR_TIMEOUT_SECONDS = 300
QQ_OFFICIAL_QR_POLL_INTERVAL_SECONDS = 2


@dataclass
class QQOfficialLoginSession:
    """In-memory state for one QQ official bot QR binding task."""

    task_id: str
    bind_key: str


class _QQOfficialClient(botpy.Client if botpy else object):
    """Bridge QQ OpenAPI events to the adapter instance."""

    def __init__(self, adapter: "QQOfficialAdapter"):
        self.adapter = adapter
        intents = botpy.Intents(public_messages=True)
        super().__init__(
            intents=intents,
            is_sandbox=adapter.sandbox,
            bot_log=None,
        )

    async def on_group_at_message_create(self, message):
        await self.adapter._handle_group_message(message)

    async def on_c2c_message_create(self, message):
        await self.adapter._handle_direct_message(message)

    async def on_ready(self):
        robot_name = getattr(getattr(self, "robot", None), "name", "QQ official bot")
        logger.info(f"QQ official bot connected: {robot_name}")


class QQOfficialAdapter(IMAdapter):
    """QQ official bot adapter backed by the QQ Bot Open Platform Gateway."""

    def __init__(self, info, event_bus: asyncio.Queue):
        super().__init__(info, event_bus)
        self.app_id = str(self.config.get("app_id", "")).strip()
        self.app_secret = str(self.config.get("app_secret", "")).strip()
        self.sandbox = bool(self.config.get("sandbox", False))
        self.message_types = ["text", "img", "at", "reply", "record", "file", "video", "emoji"]
        self._group_reply_ids: dict[str, str] = {}
        self._direct_reply_ids: dict[str, str] = {}
        self._reply_msg_seqs: dict[tuple[bool, str, str], int] = {}
        self._send_locks: dict[tuple[bool, str, str], asyncio.Lock] = {}
        self._reply_id_aliases: dict[tuple[bool, str, str], str] = {}
        self._client_task: Optional[asyncio.Task] = None
        self._login_task: Optional[asyncio.Task] = None
        self._login_session: Optional[QQOfficialLoginSession] = None
        self._shutdown_event = asyncio.Event()
        self.client = _QQOfficialClient(self) if botpy else None

    async def start(self):
        if botpy is None:
            logger.error("QQ official bot requires qq-botpy. Install project dependencies first.")
            return
        if not self.app_id and not self.app_secret:
            if not self._login_task or self._login_task.done():
                self._login_task = asyncio.create_task(
                    self._run_qr_login(), name=f"qq-official-login:{self.info.name}"
                )
            return
        if not self.app_id or not self.app_secret:
            logger.error("QQ official bot AppID and AppSecret must both be configured")
            return
        if self._client_task and not self._client_task.done():
            return
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

    async def _start_qr_login_session(self) -> QQOfficialLoginSession:
        bind_key = self._generate_bind_key()
        result = await self._post_binding_json(
            "/lite/create_bind_task", {"key": bind_key}
        )
        task_id = str(result.get("task_id", "")).strip()
        if not task_id:
            raise RuntimeError("QQ official bot binding response is missing task_id")
        login_session = QQOfficialLoginSession(task_id=task_id, bind_key=bind_key)
        self._login_session = login_session
        self._display_qr_code(
            f"https://{QQ_OFFICIAL_BIND_HOST}/qqbot/openclaw/connect.html?"
            f"task_id={quote(task_id, safe='')}&_wv=2"
        )
        return login_session

    async def _poll_qr_login_session(
        self, login_session: QQOfficialLoginSession
    ) -> dict[str, Any]:
        return await self._post_binding_json(
            "/lite/poll_bind_result", {"task_id": login_session.task_id}
        )

    def _display_qr_code(self, url: str) -> None:
        """Render the official binding URL in the application log."""
        logger.info(
            "QQ official bot QR code is ready. Scan this URL with mobile QQ: %s", url
        )
        if qrcode_lib is None:
            return
        try:
            qr = qrcode_lib.QRCode(border=1)
            qr.add_data(url)
            qr.make(fit=True)
            buffer = io.StringIO()
            qr.print_ascii(out=buffer, tty=False)
            logger.info("QQ official bot terminal QR code:\n%s", buffer.getvalue())
        except Exception as exc:
            logger.warning(f"Failed to render QQ official bot QR code: {exc}")

    async def _run_qr_login(self) -> None:
        while not self._shutdown_event.is_set() and not self.app_id and not self.app_secret:
            try:
                login_session = await self._start_qr_login_session()
                started_at = time.monotonic()
                while not self._shutdown_event.is_set():
                    if time.monotonic() - started_at >= QQ_OFFICIAL_QR_TIMEOUT_SECONDS:
                        logger.warning("QQ official bot QR code expired; generating a new one")
                        break
                    result = await self._poll_qr_login_session(login_session)
                    try:
                        status = int(result.get("status", 0))
                    except (TypeError, ValueError):
                        status = 0
                    if status == 2:
                        self.app_id = str(result.get("bot_appid", "")).strip()
                        encrypted_secret = str(result.get("bot_encrypt_secret", "")).strip()
                        self.app_secret = self._decrypt_bound_secret(
                            encrypted_secret, login_session.bind_key
                        )
                        if not self.app_id or not self.app_secret:
                            raise RuntimeError("QQ official bot QR login returned incomplete credentials")
                        scanner_openid = str(result.get("user_openid", "")).strip()
                        if (
                            scanner_openid
                            and self.permission_mode == "allow_list"
                            and scanner_openid not in {str(entry) for entry in self.user_list}
                        ):
                            self.user_list.append(scanner_openid)
                            self.info.config["user_allow_list"] = list(self.user_list)
                        await self._save_credentials()
                        logger.info("QQ official bot QR login completed and credentials were saved")
                        await self.start()
                        return
                    if status == 3:
                        logger.warning("QQ official bot QR code expired; generating a new one")
                        break
                    await asyncio.sleep(QQ_OFFICIAL_QR_POLL_INTERVAL_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(f"QQ official bot QR login failed: {exc}")
                await asyncio.sleep(5)

    async def _save_credentials(self) -> None:
        """Persist scanned credentials using the same adapter config flow as Weixin."""
        try:
            self.info.config["app_id"] = self.app_id
            self.info.config["app_secret"] = self.app_secret
            from core.config.config_loader import KiraConfig

            kira_config = KiraConfig()
            adapters = kira_config.get("adapters", {})
            entry = adapters.get(self.info.adapter_id)
            if not entry:
                logger.warning("QQ official bot adapter was not found in configuration")
                return
            entry["config"] = dict(self.info.config)
            kira_config.save_config()
        except Exception as exc:
            logger.error(f"Failed to save QQ official bot credentials: {exc}")

    async def stop(self):
        self._shutdown_event.set()
        if self._login_task and not self._login_task.done():
            self._login_task.cancel()
            try:
                await self._login_task
            except asyncio.CancelledError:
                pass
        self._login_task = None
        self._login_session = None
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

    def get_client(self):
        return self.client

    def _is_allowed(self, target_id: str, is_group: bool) -> bool:
        entries = self.group_list if is_group else self.user_list
        is_listed = str(target_id) in {str(entry) for entry in entries}
        return is_listed if self.permission_mode == "allow_list" else not is_listed

    @staticmethod
    def _message_chain(message) -> MessageChain:
        elements: list[Any] = []
        content = getattr(message, "content", None)
        if content:
            elements.append(Text(content))
        for attachment in getattr(message, "attachments", []) or []:
            url = getattr(attachment, "url", None)
            if not url:
                continue
            name = getattr(attachment, "filename", None)
            content_type = str(getattr(attachment, "content_type", "") or "").lower()
            guessed_type, _ = mimetypes.guess_type(name or "")
            guessed_mime = (guessed_type or "").lower()
            mime = (
                guessed_mime
                if content_type in {"", "application/octet-stream", "binary/octet-stream"}
                else content_type
            )
            suffix = Path(name or "").suffix.lower()
            try:
                if mime.startswith("image/"):
                    elements.append(Image(url, name=name, mime=mime))
                elif mime.startswith("audio/") or suffix in {".amr", ".silk", ".ogg", ".mp3", ".wav", ".m4a", ".aac", ".flac"}:
                    elements.append(Record(url, name=name, mime=mime or None))
                elif mime.startswith("video/"):
                    elements.append(Video(url, name=name, mime=mime))
                else:
                    elements.append(
                        File(
                            url,
                            name=name,
                            size=str(getattr(attachment, "size", "") or "") or None,
                            mime=mime or None,
                        )
                    )
            except ValueError:
                elements.append(Text("[Attachment]"))
        return MessageChain(elements or [Text("[Unsupported message]")])

    async def _handle_group_message(self, message):
        group_id = str(getattr(message, "group_openid", "") or "")
        user_id = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
        if not group_id or not user_id or not self._is_allowed(group_id, is_group=True):
            return
        message_id = str(getattr(message, "id", "") or "")
        display_message_id = ""
        if message_id:
            self._group_reply_ids[group_id] = message_id
            display_message_id = self._remember_reply_id(True, group_id, message_id)
        self.publish(
            KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                message=KiraIMMessage(
                    timestamp=int(time.time()),
                    group=Group(group_id=group_id, group_name=group_id),
                    sender=User(user_id=user_id, nickname=user_id),
                    is_mentioned=True,
                    message_id=display_message_id or message_id,
                    self_id=self.app_id,
                    chain=self._message_chain(message),
                ),
                timestamp=int(time.time()),
            )
        )

    async def _handle_direct_message(self, message):
        user_id = str(getattr(getattr(message, "author", None), "user_openid", "") or "")
        if not user_id or not self._is_allowed(user_id, is_group=False):
            return
        message_id = str(getattr(message, "id", "") or "")
        display_message_id = ""
        if message_id:
            self._direct_reply_ids[user_id] = message_id
            display_message_id = self._remember_reply_id(False, user_id, message_id)
        self.publish(
            KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                message=KiraIMMessage(
                    timestamp=int(time.time()),
                    sender=User(user_id=user_id, nickname=user_id),
                    is_mentioned=True,
                    message_id=display_message_id or message_id,
                    self_id=self.app_id,
                    chain=self._message_chain(message),
                ),
                timestamp=int(time.time()),
            )
        )

    @staticmethod
    def _text_content(send_message_obj: MessageChain) -> str:
        parts: list[str] = []
        for element in send_message_obj:
            if isinstance(element, Text):
                parts.append(element.text)
            elif isinstance(element, At):
                parts.append(f"@{element.nickname or element.pid}")
            elif isinstance(element, Emoji):
                parts.append(element.emoji_desc or "")
            elif isinstance(element, Reply):
                continue
            else:
                parts.append("[Unsupported message element]")
        return "".join(parts).strip()

    @staticmethod
    def _result_message_id(result: Any) -> Optional[str]:
        if isinstance(result, dict):
            value = result.get("id") or result.get("message_id")
        else:
            value = getattr(result, "id", None) or getattr(result, "message_id", None)
        return str(value) if value is not None else None

    @staticmethod
    def _display_message_id(message_id: str) -> str:
        """Return a short stable ID suitable for the LLM context."""
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:10]
        return f"qqo-{digest}"

    def _remember_reply_id(self, is_group: bool, target_id: str, message_id: str) -> str:
        display_message_id = self._display_message_id(message_id)
        reply_key = (is_group, target_id, message_id)
        self._reply_id_aliases[(is_group, target_id, display_message_id)] = message_id
        self._reply_msg_seqs[reply_key] = 0
        return display_message_id

    def _resolve_reply_id(
        self, is_group: bool, target_id: str, send_message_obj: MessageChain
    ) -> Optional[str]:
        for element in send_message_obj:
            if isinstance(element, Reply):
                return self._reply_id_aliases.get(
                    (is_group, target_id, element.message_id), element.message_id
                )
        reply_ids = self._group_reply_ids if is_group else self._direct_reply_ids
        return reply_ids.get(target_id)

    async def send_group_message(
        self, group_id: Union[int, str], send_message_obj: MessageChain
    ) -> Optional[KiraIMSentResult]:
        return await self._send_message(str(group_id), send_message_obj, is_group=True)

    async def send_direct_message(
        self, user_id: Union[int, str], send_message_obj: MessageChain
    ) -> Optional[KiraIMSentResult]:
        return await self._send_message(str(user_id), send_message_obj, is_group=False)

    async def _send_message(
        self, target_id: str, send_message_obj: MessageChain, is_group: bool
    ) -> KiraIMSentResult:
        if not self.client or not self._client_task or self._client_task.done():
            return KiraIMSentResult(ok=False, err="QQ official bot is not connected")
        content = self._text_content(send_message_obj)
        if not content:
            return KiraIMSentResult(ok=False, err="QQ official bot cannot send an empty message")
        reply_id = self._resolve_reply_id(is_group, target_id, send_message_obj)
        if not reply_id:
            return KiraIMSentResult(
                ok=False,
                err="QQ official bot needs a received message before replying to this conversation",
            )
        send_key = (is_group, target_id, reply_id)
        lock = self._send_locks.setdefault(send_key, asyncio.Lock())
        async with lock:
            msg_seq = self._reply_msg_seqs.get(send_key, 0) + 1
            try:
                if is_group:
                    result = await self.client.api.post_group_message(
                        group_openid=target_id,
                        msg_type=0,
                        msg_id=reply_id,
                        msg_seq=msg_seq,
                        content=content,
                    )
                else:
                    result = await self.client.api.post_c2c_message(
                        openid=target_id,
                        msg_type=0,
                        msg_id=reply_id,
                        msg_seq=msg_seq,
                        content=content,
                    )
                self._reply_msg_seqs[send_key] = msg_seq
                message_id = self._result_message_id(result)
                display_message_id = (
                    self._remember_reply_id(is_group, target_id, message_id)
                    if message_id
                    else None
                )
                return KiraIMSentResult(message_id=display_message_id)
            except Exception as exc:
                scope = "group" if is_group else "direct"
                logger.error(f"Failed to send QQ official {scope} message: {exc}")
                return KiraIMSentResult(ok=False, err=f"Failed to send QQ official message: {exc}")
