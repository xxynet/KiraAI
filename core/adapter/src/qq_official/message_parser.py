"""Parse QQ OpenAPI content while keeping identity evidence scoped to a conversation."""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Any

from core.chat.message_elements import At, File, Image, Record, Text, Video


AT_MARKUP = re.compile(r'<@!?([^<>\s]+)>|<qqbot-at-user\s+id=["\']([^"\']+)["\']\s*/>')
FACE_MARKUP = re.compile(r'<faceType=\d+,\s*faceId="\d+",\s*ext="([^"<>]{0,8192})">')
MAX_IDENTITIES = 4096


def field(value: Any, name: str, default: Any = None) -> Any:
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def scene_value(message: Any, name: str) -> str:
    values = field(field(message, "message_scene"), "ext", [])
    if isinstance(values, list):
        for value in values:
            if isinstance(value, str) and value.startswith(name + "="):
                return value.partition("=")[2]
    return ""


def message_timestamp(message: Any, fallback: int) -> int:
    value = field(message, "timestamp")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return int(parsed.timestamp())
        except (ValueError, OverflowError):
            pass
    return fallback


def _face_text(match: re.Match) -> str:
    try:
        encoded = match[1] + "=" * (-len(match[1]) % 4)
        data = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        if isinstance(data, dict):
            for key in ("text", "name", "desc", "description", "prompt", "summary", "title"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return f"[Emoji: {value.strip()[:128]}]"
    except (ValueError, UnicodeError, binascii.Error):
        pass
    return "[Emoji]"


class QQOfficialMessageParser:
    def __init__(self):
        self._names: OrderedDict[tuple[bool, str, str], str] = OrderedDict()
        self._self_ids: OrderedDict[tuple[bool, str], str] = OrderedDict()

    @staticmethod
    def _remember(cache: OrderedDict, key: Any, value: str) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > MAX_IDENTITIES:
            cache.popitem(last=False)

    def nickname(self, is_group: bool, target_id: str, author: Any, user_id: str) -> str:
        key = (is_group, target_id, user_id)
        name = field(author, "username")
        if isinstance(name, str) and name.strip():
            self._remember(self._names, key, name.strip())
        return self._names.get(key, user_id)

    def self_ids(self, message: Any, is_group: bool, target_id: str, robot_id: str) -> set[str]:
        key = (is_group, target_id)
        mentions = field(message, "mentions", [])
        if isinstance(mentions, list):
            for mention in mentions:
                uid = field(mention, "id") or field(mention, "member_openid")
                if field(mention, "is_you") is True and uid:
                    self._remember(self._self_ids, key, str(uid))
        return {uid for uid in (robot_id, self._self_ids.get(key)) if uid}

    def is_mentioned(self, message: Any, self_ids: set[str]) -> bool:
        mentions = field(message, "mentions", [])
        if isinstance(mentions, list):
            for mention in mentions:
                uid = str(field(mention, "id") or field(mention, "member_openid") or "")
                if field(mention, "is_you") is True or uid in self_ids:
                    return True
        content = field(message, "content", "")
        if isinstance(content, str) and any((m[1] or m[2]) in self_ids for m in AT_MARKUP.finditer(content)):
            return True
        if str(field(message, "message_type", "")) == "103":
            elements = field(message, "msg_elements", [])
            if isinstance(elements, list) and elements:
                author = field(elements[0], "author")
                uid = str(field(author, "id") or field(author, "member_openid") or "")
                return bool(uid and uid in self_ids)
        return False

    def content_elements(self, message: Any, is_group: bool, target_id: str) -> list[Any]:
        elements: list[Any] = []
        content = field(message, "content")
        mentions = field(message, "mentions", [])
        names = {}
        if isinstance(mentions, list):
            for mention in mentions:
                uid = str(field(mention, "id") or field(mention, "member_openid") or "")
                if uid:
                    names[uid] = self.nickname(is_group, target_id, mention, uid)
        if isinstance(content, str) and content:
            content = FACE_MARKUP.sub(_face_text, content)
            position = 0
            for match in AT_MARKUP.finditer(content):
                if match.start() > position:
                    elements.append(Text(content[position:match.start()]))
                uid = match[1] or match[2]
                name = names.get(uid) or self._names.get((is_group, target_id, uid))
                elements.append(At(uid, name))
                position = match.end()
            if position < len(content):
                elements.append(Text(content[position:]))
        ark = field(message, "ark_data")
        if isinstance(ark, dict):
            fields = ark.get("fields")
            fields = fields if isinstance(fields, dict) else {}
            parts = [ark.get("ark_name") or ark.get("ark_type")]
            parts.extend(fields.get(key) or ark.get(key) for key in ("title", "desc", "prompt", "jump_url", "address"))
            summary = " - ".join(dict.fromkeys(p.strip() for p in parts if isinstance(p, str) and p.strip()))
            elements.append(Text(f"[Card: {summary}]" if summary else "[Card]"))
        attachments = field(message, "attachments", [])
        for attachment in attachments if isinstance(attachments, list) else []:
            content_type = str(field(attachment, "content_type", "") or "").lower()
            if content_type == "voice":
                transcript = field(attachment, "asr_refer_text")
                if isinstance(transcript, str) and transcript.strip():
                    elements.append(Text(f"[Voice: {transcript.strip()}]"))
                    continue
            url = field(attachment, "voice_wav_url") if content_type == "voice" else None
            url = url or field(attachment, "url")
            if not isinstance(url, str) or not url:
                continue
            name = field(attachment, "filename")
            name = name if isinstance(name, str) else None
            guessed_mime = mimetypes.guess_type(name or "")[0] or ""
            mime = guessed_mime if content_type in {"", "application/octet-stream", "binary/octet-stream"} else content_type
            suffix = Path(name or "").suffix.lower()
            try:
                if content_type == "voice":
                    mime = "audio/wav" if field(attachment, "voice_wav_url") else "audio/silk"
                    elements.append(Record(url, name=name, mime=mime))
                elif mime.startswith("image/"):
                    elements.append(Image(url, name=name, mime=mime))
                elif mime.startswith("audio/") or suffix in {".amr", ".silk", ".ogg", ".mp3", ".wav", ".m4a", ".aac", ".flac"}:
                    elements.append(Record(url, name=name, mime=mime or None))
                elif mime.startswith("video/"):
                    elements.append(Video(url, name=name, mime=mime))
                else:
                    elements.append(File(url, name=name, size=str(field(attachment, "size", "") or "") or None, mime=mime or None))
            except ValueError:
                elements.append(Text("[Attachment]"))
        return elements
