from __future__ import annotations

import asyncio
import base64
import hashlib
import mimetypes
import time
from collections import OrderedDict
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

try:
    from botpy.http import Route
except ImportError:
    Route = None

from core.adapter.capabilities import IMCapability
from core.chat import Group, User, KiraIMMessage, KiraIMSentResult, KiraMessageEvent, MessageChain
from core.chat.message_elements import At, Emoji, File, Image, Record, Reply, Text, Video
from core.logging_manager import get_logger

if TYPE_CHECKING:
    from .qq_official import QQOfficialAdapter


logger = get_logger("qq_official_adapter", "blue")

QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION = 100


class QQOfficialIMCapability(IMCapability["QQOfficialAdapter"]):
    """Receive and send QQ OpenAPI messages using the adapter's account."""

    def __init__(self, adapter: QQOfficialAdapter):
        super().__init__(adapter)
        self._group_reply_ids: dict[str, str] = {}
        self._direct_reply_ids: dict[str, str] = {}
        self._reply_msg_seqs: dict[tuple[bool, str, str], int] = {}
        self._send_locks: dict[tuple[bool, str, str], asyncio.Lock] = {}
        self._reply_id_aliases: dict[tuple[bool, str, str], str] = {}
        self._reply_alias_lrus: dict[
            tuple[bool, str], OrderedDict[str, str]
        ] = {}

    @staticmethod
    def _field_value(value: Any, field: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(field, default)
        return getattr(value, field, default)

    @classmethod
    def _content_elements(cls, content: Optional[str], attachments: list[Any]) -> list[Any]:
        elements: list[Any] = []
        if content:
            elements.append(Text(content))
        for attachment in attachments or []:
            url = cls._field_value(attachment, "url")
            if not url:
                continue
            name = cls._field_value(attachment, "filename")
            content_type = str(cls._field_value(attachment, "content_type", "") or "").lower()
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
                            size=str(cls._field_value(attachment, "size", "") or "") or None,
                            mime=mime or None,
                        )
                    )
            except ValueError:
                elements.append(Text("[Attachment]"))
        return elements

    @classmethod
    def _quoted_message_details(cls, message) -> tuple[str, Optional[str], list[Any]]:
        message_reference = cls._field_value(message, "message_reference")
        quoted_message_id = str(
            cls._field_value(message_reference, "message_id", "") or ""
        )
        quoted_content: Optional[str] = None
        quoted_attachments: list[Any] = []
        try:
            is_quoted_message = int(cls._field_value(message, "message_type", 0) or 0) == 103
        except (TypeError, ValueError):
            is_quoted_message = False
        message_elements = cls._field_value(message, "msg_elements", [])
        if is_quoted_message and isinstance(message_elements, list) and message_elements:
            quoted_element = message_elements[0]
            quoted_message_id = quoted_message_id or str(
                cls._field_value(quoted_element, "id")
                or cls._field_value(quoted_element, "message_id", "")
                or ""
            )
            quoted_content = cls._field_value(quoted_element, "content")
            quoted_attachments = cls._field_value(quoted_element, "attachments", []) or []
        return quoted_message_id, quoted_content, quoted_attachments

    def _message_chain(self, message, is_group: bool, target_id: str) -> MessageChain:
        elements: list[Any] = []
        quoted_message_id, quoted_content, quoted_attachments = self._quoted_message_details(message)
        if quoted_message_id or quoted_content or quoted_attachments:
            display_message_id = (
                self._remember_reply_id(is_group, target_id, quoted_message_id)
                if quoted_message_id
                else ""
            )
            quoted_chain = self._content_elements(quoted_content, quoted_attachments)
            elements.append(
                Reply(
                    display_message_id,
                    chain=MessageChain(quoted_chain) if quoted_chain else None,
                )
            )
        elements.extend(
            self._content_elements(
                self._field_value(message, "content"),
                self._field_value(message, "attachments", []) or [],
            )
        )
        return MessageChain(elements or [Text("[Unsupported message]")])

    async def _handle_group_message(self, message):
        group_id = str(getattr(message, "group_openid", "") or "")
        user_id = str(getattr(getattr(message, "author", None), "member_openid", "") or "")
        if not group_id or not user_id or not self.is_allowed(group_id, permission="im.group.receive"):
            return
        message_id = str(getattr(message, "id", "") or "")
        display_message_id = ""
        if message_id:
            self._group_reply_ids[group_id] = message_id
            display_message_id = self._remember_reply_id(True, group_id, message_id)
        self.publish(
            KiraMessageEvent(
                adapter=self.adapter.info,
                message_types=self.adapter.message_types,
                message=KiraIMMessage(
                    timestamp=int(time.time()),
                    group=Group(group_id=group_id, group_name=group_id),
                    sender=User(user_id=user_id, nickname=user_id),
                    is_mentioned=True,
                    message_id=display_message_id or message_id,
                    self_id=self.adapter.app_id,
                    chain=self._message_chain(message, is_group=True, target_id=group_id),
                ),
                timestamp=int(time.time()),
            )
        )

    async def _handle_direct_message(self, message):
        user_id = str(getattr(getattr(message, "author", None), "user_openid", "") or "")
        if not user_id or not self.is_allowed(user_id, permission="im.direct.receive"):
            return
        message_id = str(getattr(message, "id", "") or "")
        display_message_id = ""
        if message_id:
            self._direct_reply_ids[user_id] = message_id
            display_message_id = self._remember_reply_id(False, user_id, message_id)
        self.publish(
            KiraMessageEvent(
                adapter=self.adapter.info,
                message_types=self.adapter.message_types,
                message=KiraIMMessage(
                    timestamp=int(time.time()),
                    sender=User(user_id=user_id, nickname=user_id),
                    is_mentioned=True,
                    message_id=display_message_id or message_id,
                    self_id=self.adapter.app_id,
                    chain=self._message_chain(message, is_group=False, target_id=user_id),
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
            elif isinstance(element, (File, Image)):
                continue
            else:
                parts.append("[Unsupported message element]")
        return "".join(parts).strip()

    @staticmethod
    def _media_payload(upload_result: Any) -> Optional[dict[str, str]]:
        """Build the rich-media payload expected by QQ's message API."""
        if isinstance(upload_result, dict):
            file_info = upload_result.get("file_info")
        else:
            file_info = getattr(upload_result, "file_info", None)
        if not isinstance(file_info, str) or not file_info:
            return None
        return {"file_info": file_info}

    @staticmethod
    def _result_message_id(result: Any) -> Optional[str]:
        if isinstance(result, dict):
            value = result.get("id") or result.get("message_id")
        else:
            value = getattr(result, "id", None) or getattr(result, "message_id", None)
        return str(value) if value is not None else None

    async def _upload_file(
        self, target_id: str, media_element: File | Image, is_group: bool
    ) -> Optional[Any]:
        """Upload a file or image and return the QQ media payload."""
        if not self.adapter.client:
            return None
        file_type = 1 if isinstance(media_element, Image) else 4
        if media_element.file_type == "url":
            if is_group:
                return await self.adapter.client.api.post_group_file(
                    group_openid=target_id,
                    file_type=file_type,
                    url=media_element.file,
                    srv_send_msg=False,
                )
            return await self.adapter.client.api.post_c2c_file(
                openid=target_id,
                file_type=file_type,
                url=media_element.file,
                srv_send_msg=False,
            )

        if Route is None:
            raise RuntimeError("qq-botpy is required to upload local files")
        file_path = await media_element.to_path()
        file_data = await asyncio.to_thread(Path(file_path).read_bytes)
        payload: dict[str, Any] = {
            "file_type": file_type,
            "file_data": base64.b64encode(file_data).decode("ascii"),
            "srv_send_msg": False,
        }
        file_name = media_element.guess_name()
        if file_name:
            payload["file_name"] = file_name
        if is_group:
            payload["group_openid"] = target_id
            route = Route(
                "POST", "/v2/groups/{group_openid}/files", group_openid=target_id
            )
        else:
            payload["openid"] = target_id
            route = Route("POST", "/v2/users/{openid}/files", openid=target_id)
        return await self.adapter.client.api._http.request(route, json=payload)

    @staticmethod
    def _display_message_id(message_id: str) -> str:
        """Return a short stable ID suitable for the LLM context."""
        digest = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:10]
        return f"qqo-{digest}"

    def _remember_reply_id(self, is_group: bool, target_id: str, message_id: str) -> str:
        display_message_id = self._display_message_id(message_id)
        reply_key = (is_group, target_id, message_id)
        conversation_key = (is_group, target_id)
        aliases = self._reply_alias_lrus.setdefault(conversation_key, OrderedDict())
        previous_message_id = aliases.pop(display_message_id, None)
        if previous_message_id and previous_message_id != message_id:
            previous_key = (is_group, target_id, previous_message_id)
            self._reply_msg_seqs.pop(previous_key, None)
            self._send_locks.pop(previous_key, None)
        aliases[display_message_id] = message_id
        self._reply_id_aliases[(is_group, target_id, display_message_id)] = message_id
        self._reply_msg_seqs[reply_key] = 0
        while len(aliases) > QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION:
            expired_display_id, expired_message_id = aliases.popitem(last=False)
            self._reply_id_aliases.pop(
                (is_group, target_id, expired_display_id), None
            )
            expired_key = (is_group, target_id, expired_message_id)
            self._reply_msg_seqs.pop(expired_key, None)
            self._send_locks.pop(expired_key, None)
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
        if not self.adapter.client or not self.adapter._client_task or self.adapter._client_task.done():
            return KiraIMSentResult(ok=False, err="QQ official bot is not connected")
        content = self._text_content(send_message_obj)
        media_elements = [
            element for element in send_message_obj if isinstance(element, (File, Image))
        ]
        if len(media_elements) > 1:
            return KiraIMSentResult(
                ok=False, err="QQ official bot can send only one media item per message"
            )
        if not content and not media_elements:
            return KiraIMSentResult(ok=False, err="QQ official bot cannot send an empty message")
        reply_id = self._resolve_reply_id(is_group, target_id, send_message_obj)
        if not reply_id:
            return KiraIMSentResult(
                ok=False,
                err="QQ official bot needs a received message before replying to this conversation",
            )
        media = None
        if media_elements:
            try:
                upload_result = await self._upload_file(target_id, media_elements[0], is_group)
                media = self._media_payload(upload_result)
            except Exception as exc:
                logger.error(f"Failed to upload QQ official media: {exc}")
                return KiraIMSentResult(
                    ok=False, err=f"Failed to upload QQ official media: {exc}"
                )
            if not media:
                return KiraIMSentResult(
                    ok=False, err="QQ official media upload returned no file_info"
                )
        send_key = (is_group, target_id, reply_id)
        lock = self._send_locks.setdefault(send_key, asyncio.Lock())
        async with lock:
            msg_seq = self._reply_msg_seqs.get(send_key, 0) + 1
            try:
                if is_group:
                    payload: dict[str, Any] = {
                        "msg_type": 7 if media else 0,
                        "msg_id": reply_id,
                        "msg_seq": msg_seq,
                        "content": content or None,
                    }
                    if media:
                        payload["media"] = media
                    else:
                        payload["msg_id"] = reply_id
                    result = await self.adapter.client.api.post_group_message(
                        group_openid=target_id, **payload
                    )
                else:
                    payload = {
                        "msg_type": 7 if media else 0,
                        "msg_id": reply_id,
                        "msg_seq": msg_seq,
                        "content": content or None,
                    }
                    if media:
                        payload["media"] = media
                    result = await self.adapter.client.api.post_c2c_message(openid=target_id, **payload)
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
