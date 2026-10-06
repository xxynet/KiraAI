from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import time
from collections import OrderedDict
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

try:
    from botpy.http import Route
except ImportError:
    Route = None

from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata
from core.chat import Group, User, KiraIMMessage, KiraIMSentResult, KiraMessageEvent, MessageChain
from core.chat.message_elements import At, Emoji, File, Image, Reply, Text
from core.logging_manager import get_logger

from .message_parser import AT_MARKUP, QQOfficialMessageParser, field, message_timestamp, scene_value

if TYPE_CHECKING:
    from .qq_official import QQOfficialAdapter


logger = get_logger("qq_official_adapter", "blue")

QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION = 100
QQ_OFFICIAL_DEDUP_TTL = 180
QQ_OFFICIAL_MAX_RECEIVED_MESSAGES = 4096


class QQOfficialIMCapability(IMCapability["QQOfficialAdapter"]):
    """Receive and send QQ OpenAPI messages using the adapter's account."""

    _SUPPORTED_ELEMENTS = ["text", "img", "at", "reply", "record", "file", "video", "emoji"]

    async def get_message_metadata(self) -> MessageFormatMetadata:
        return MessageFormatMetadata(self._supported_elements, emojis={})

    def __init__(self, adapter: QQOfficialAdapter):
        super().__init__(adapter)
        self._parser = QQOfficialMessageParser()
        self._received_messages: OrderedDict[tuple[bool, str, str, str], float] = OrderedDict()
        self._reply_received_at: dict[tuple[bool, str, str], float] = {}
        self._message_references: dict[tuple[bool, str, str], str] = {}
        self._sent_message_ids: set[tuple[bool, str, str]] = set()
        self._proactive_enabled = bool(adapter.config.get("proactive_enabled", True))
        self._group_reply_ids: dict[str, str] = {}
        self._direct_reply_ids: dict[str, str] = {}
        self._reply_msg_seqs: dict[tuple[bool, str, str], int] = {}
        self._send_locks: dict[tuple[bool, str, str], asyncio.Lock] = {}
        self._reply_id_aliases: dict[tuple[bool, str, str], str] = {}
        self._reply_alias_lrus: dict[
            tuple[bool, str], OrderedDict[str, str]
        ] = {}

    def _remember_reference(self, message, is_group: bool, target_id: str, message_id: str):
        reference = scene_value(message, "msg_idx")
        if message_id and reference:
            self._message_references[(is_group, target_id, message_id)] = reference

    def _quoted_message(self, message, is_group: bool, target_id: str) -> tuple[str, Any]:
        reference = field(message, "message_reference")
        quoted_id = str(field(reference, "message_id", "") or "")
        quoted = None
        if str(field(message, "message_type", "")) == "103":
            quoted_elements = field(message, "msg_elements", [])
            if isinstance(quoted_elements, list) and quoted_elements:
                quoted = quoted_elements[0]
                quoted_id = quoted_id or str(field(quoted, "id") or field(quoted, "message_id", "") or "")
        quoted_reference = scene_value(message, "ref_msg_idx")
        if not quoted_id and quoted_reference:
            aliases = self._reply_alias_lrus.get((is_group, target_id), {})
            quoted_id = next((raw_id for raw_id in aliases.values()
                              if self._message_references.get((is_group, target_id, raw_id)) == quoted_reference), "")
        return quoted_id, quoted

    def _is_self_quote(self, message, is_group: bool, target_id: str) -> bool:
        if str(field(message, "message_type", "")) != "103" and not field(message, "message_reference"):
            return False
        quoted_id, _ = self._quoted_message(message, is_group, target_id)
        return bool(quoted_id and (is_group, target_id, quoted_id) in self._sent_message_ids)

    def _message_chain(self, message, is_group: bool, target_id: str) -> MessageChain:
        elements: list[Any] = []
        quoted_id, quoted = self._quoted_message(message, is_group, target_id)
        if quoted_id or quoted is not None:
            display_id = self._remember_reply_id(is_group, target_id, quoted_id) if quoted_id else ""
            quoted_chain = self._parser.content_elements(quoted, is_group, target_id) if quoted is not None else []
            elements.append(Reply(display_id, chain=MessageChain(quoted_chain) if quoted_chain else None))
        elements.extend(self._parser.content_elements(message, is_group, target_id))
        return MessageChain(elements or [Text("[Unsupported message]")])

    def _accept_message(self, message, is_group: bool, target_id: str) -> bool:
        message_id = str(field(message, "id", "") or "")
        if not message_id:
            return True
        now = time.monotonic()
        while self._received_messages:
            key, seen_at = next(iter(self._received_messages.items()))
            if now - seen_at < QQ_OFFICIAL_DEDUP_TTL:
                break
            self._received_messages.popitem(last=False)
        key = (is_group, target_id, message_id, str(field(message, "msg_seq", "")))
        if key in self._received_messages:
            return False
        self._received_messages[key] = now
        while len(self._received_messages) > QQ_OFFICIAL_MAX_RECEIVED_MESSAGES:
            self._received_messages.popitem(last=False)
        return True

    async def _handle_group_message(self, message, force_mention: bool = True):
        await self._handle_message(message, is_group=True, force_mention=force_mention)

    async def _handle_direct_message(self, message):
        await self._handle_message(message, is_group=False, force_mention=True)

    async def _handle_message(self, message, is_group: bool, force_mention: bool):
        author = field(message, "author")
        user_id = str(field(author, "member_openid" if is_group else "user_openid") or field(author, "id", "") or "")
        target_id = str(field(message, "group_openid", "") or "") if is_group else user_id
        permission = "im.group.receive" if is_group else "im.direct.receive"
        if not target_id or not user_id or not self.is_allowed(target_id, permission=permission):
            return
        if not self._accept_message(message, is_group, target_id):
            return
        robot = getattr(self.adapter.client, "robot", None)
        robot_id = str(getattr(robot, "id", "") or "")
        self_ids = self._parser.self_ids(message, is_group, target_id, robot_id)
        is_self_quote = self._is_self_quote(message, is_group, target_id)
        message_id = str(field(message, "id", "") or "")
        display_id = ""
        timestamp = message_timestamp(message, int(time.time()))
        if message_id:
            reply_ids = self._group_reply_ids if is_group else self._direct_reply_ids
            reply_ids[target_id] = message_id
            display_id = self._remember_reply_id(is_group, target_id, message_id)
            age = max(0, time.time() - timestamp)
            self._reply_received_at[(is_group, target_id, message_id)] = time.monotonic() - age
            self._remember_reference(message, is_group, target_id, message_id)
        self.publish(KiraMessageEvent(
            adapter=self.adapter.info,
            supported_elements=list((await self.get_message_metadata()).supported_elements),
            message=KiraIMMessage(
                timestamp=timestamp,
                group=Group(group_id=target_id, group_name=target_id) if is_group else None,
                sender=User(user_id=user_id, nickname=self._parser.nickname(is_group, target_id, author, user_id)),
                is_mentioned=force_mention or is_self_quote or self._parser.is_mentioned(message, self_ids),
                message_id=display_id or message_id,
                self_id=robot_id or self.adapter.app_id,
                chain=self._message_chain(message, is_group, target_id),
            ),
            timestamp=int(time.time()),
        ))

    @staticmethod
    def _text_content(send_message_obj: MessageChain) -> str:
        parts: list[str] = []
        for element in send_message_obj:
            if isinstance(element, Text):
                parts.append(element.text)
            elif isinstance(element, At):
                if element.pid == "all":
                    parts.append("@all")
                else:
                    parts.append(f'<qqbot-at-user id="{escape(element.pid, quote=True)}" />')
            elif isinstance(element, Emoji):
                parts.append(element.emoji_desc or "")
            elif isinstance(element, (Reply, File, Image)):
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
            self._forget_reply_id(is_group, target_id, previous_message_id)
        aliases[display_message_id] = message_id
        self._reply_id_aliases[(is_group, target_id, display_message_id)] = message_id
        self._reply_msg_seqs.setdefault(reply_key, 0)
        while len(aliases) > QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION:
            expired_display_id, expired_message_id = aliases.popitem(last=False)
            self._reply_id_aliases.pop(
                (is_group, target_id, expired_display_id), None
            )
            self._forget_reply_id(is_group, target_id, expired_message_id)
        return display_message_id

    def _forget_reply_id(self, is_group: bool, target_id: str, message_id: str) -> None:
        key = (is_group, target_id, message_id)
        self._reply_msg_seqs.pop(key, None)
        self._send_locks.pop(key, None)
        self._reply_received_at.pop(key, None)
        self._message_references.pop(key, None)
        self._sent_message_ids.discard(key)
        reply_ids = self._group_reply_ids if is_group else self._direct_reply_ids
        if reply_ids.get(target_id) == message_id:
            reply_ids.pop(target_id, None)

    def _reply_is_valid(self, is_group: bool, target_id: str, message_id: str) -> bool:
        key = (is_group, target_id, message_id)
        received_at = self._reply_received_at.get(key)
        max_age, max_replies = (300, 5) if is_group else (3600, 4)
        return ((received_at is None or time.monotonic() - received_at < max_age)
                and self._reply_msg_seqs.get(key, 0) < max_replies)

    def _resolve_reply_id(
        self, is_group: bool, target_id: str, send_message_obj: MessageChain
    ) -> Optional[str]:
        reply_ids = self._group_reply_ids if is_group else self._direct_reply_ids
        latest_id = reply_ids.get(target_id)
        for element in send_message_obj:
            if isinstance(element, Reply):
                raw_id = self._reply_id_aliases.get((is_group, target_id, element.message_id))
                if ((is_group, target_id, raw_id) in self._reply_received_at
                        and self._reply_is_valid(is_group, target_id, raw_id)):
                    return raw_id
        if latest_id and not self._reply_is_valid(is_group, target_id, latest_id):
            self._invalidate_reply_id(is_group, target_id, latest_id)
            return None
        return latest_id

    def _resolve_reference(self, is_group: bool, target_id: str, chain: MessageChain) -> Optional[str]:
        for element in chain:
            if isinstance(element, Reply):
                raw_id = self._reply_id_aliases.get((is_group, target_id, element.message_id))
                return self._message_references.get((is_group, target_id, raw_id))
        return None

    def _invalidate_reply_id(self, is_group: bool, target_id: str, reply_id: str):
        key = (is_group, target_id, reply_id)
        if key in self._reply_received_at:
            self._reply_received_at[key] = float("-inf")
        reply_ids = self._group_reply_ids if is_group else self._direct_reply_ids
        if reply_ids.get(target_id) == reply_id:
            reply_ids.pop(target_id, None)

    @staticmethod
    def _send_error_code(exc: Exception) -> Optional[str]:
        match = re.search(r"\b(?:304103|40034005|40034128|40034100|40034105|40034006|40034024)\b", str(exc))
        return match[0] if match else None

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
        client = self.adapter.client
        if not client or not self.adapter._client_task or self.adapter._client_task.done():
            return KiraIMSentResult(ok=False, err="QQ official bot is not connected")
        content = self._text_content(send_message_obj)
        media_elements = [element for element in send_message_obj if isinstance(element, (File, Image))]
        if len(media_elements) > 1:
            return KiraIMSentResult(ok=False, err="QQ official bot can send only one media item per message")
        if not content and not media_elements:
            return KiraIMSentResult(ok=False, err="QQ official bot cannot send an empty message")
        lock = self._send_locks.setdefault((is_group, target_id, ""), asyncio.Lock())
        async with lock:
            if (self.adapter.client is not client or not self.adapter._client_task
                    or self.adapter._client_task.done()):
                return KiraIMSentResult(ok=False, err="QQ official bot disconnected before sending")
            reply_id = self._resolve_reply_id(is_group, target_id, send_message_obj)
            if not reply_id and not self._proactive_enabled:
                return KiraIMSentResult(ok=False, err="QQ official bot needs a valid received message before replying; proactive messages are disabled")
            media = None
            if media_elements:
                try:
                    media = self._media_payload(await self._upload_file(target_id, media_elements[0], is_group))
                except Exception as exc:
                    logger.error("Failed to upload QQ official media (%s)", type(exc).__name__)
                    return KiraIMSentResult(ok=False, err=f"Failed to upload QQ official media ({type(exc).__name__})")
                if not media:
                    return KiraIMSentResult(ok=False, err="QQ official media upload returned no file_info")
            if (self.adapter.client is not client or not self.adapter._client_task
                    or self.adapter._client_task.done()):
                return KiraIMSentResult(ok=False, err="QQ official bot disconnected before sending")
            reply_id = self._resolve_reply_id(is_group, target_id, send_message_obj)
            if not reply_id and not self._proactive_enabled:
                return KiraIMSentResult(ok=False, err="QQ official passive reply expired before sending; proactive messages are disabled")
            payload: dict[str, Any] = {"msg_type": 7 if media else 0, "content": content or None}
            if is_group and not media and AT_MARKUP.search(content):
                markdown_content = AT_MARKUP.sub(
                    lambda match: f'<qqbot-at-user id="{escape(match[1], quote=True)}" />' if match[1] else match[0],
                    content,
                )
                payload = {"msg_type": 2, "markdown": {"content": markdown_content}}
            if media:
                payload["media"] = media
            reference = self._resolve_reference(is_group, target_id, send_message_obj)
            if reference:
                payload["message_reference"] = {"message_id": reference}
            send = client.api.post_group_message if is_group else client.api.post_c2c_message
            target = {"group_openid": target_id} if is_group else {"openid": target_id}
            if reply_id:
                send_key = (is_group, target_id, reply_id)
                payload["msg_id"] = reply_id
                payload["msg_seq"] = self._reply_msg_seqs.setdefault(send_key, 0) + 1
            try:
                try:
                    result = await send(**target, **payload)
                except Exception as exc:
                    if not reply_id or self._send_error_code(exc) not in {"304103", "40034005", "40034128"}:
                        raise
                    self._invalidate_reply_id(is_group, target_id, reply_id)
                    if (not self._proactive_enabled or self.adapter.client is not client
                            or not self.adapter._client_task or self.adapter._client_task.done()):
                        raise
                    payload.pop("msg_id", None)
                    payload.pop("msg_seq", None)
                    reply_id = None
                    result = await send(**target, **payload)
                if reply_id and send_key in self._reply_msg_seqs:
                    self._reply_msg_seqs[send_key] = payload["msg_seq"]
                message_id = self._result_message_id(result)
                display_id = self._remember_reply_id(is_group, target_id, message_id) if message_id else None
                if message_id:
                    self._sent_message_ids.add((is_group, target_id, message_id))
                sent_reference = field(field(result, "ext_info"), "ref_idx")
                if message_id and isinstance(sent_reference, str) and sent_reference:
                    self._message_references[(is_group, target_id, message_id)] = sent_reference
                return KiraIMSentResult(message_id=display_id)
            except Exception as exc:
                error = self._send_error_code(exc) or type(exc).__name__
                logger.error("Failed to send QQ official message (%s)", error)
                return KiraIMSentResult(ok=False, err=f"Failed to send QQ official message ({error})")
