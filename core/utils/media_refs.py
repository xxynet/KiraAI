"""Persistent media references used by native multimodal chat requests."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import mimetypes
import os
from pathlib import Path
from typing import Iterable

from core.chat.message_elements import BaseMediaElement
from core.utils.path_utils import get_data_path, is_within_directory


MEDIA_REF_TYPE = "kira_image_ref"
MEDIA_ROOT_NAME = "session_media"


def _media_root() -> Path:
    return get_data_path() / MEDIA_ROOT_NAME


def _session_directory(session_id: str) -> Path:
    session_hash = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return _media_root() / session_hash


def _message_directory(session_id: str, message_id: str) -> Path:
    message_hash = hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()
    return _session_directory(session_id) / message_hash


def _extension_for_mime(mime_type: str | None) -> str:
    extension = mimetypes.guess_extension(mime_type or "")
    return extension or ".img"


async def store_session_media(
    media: BaseMediaElement,
    session_id: str,
    message_id: str,
    *,
    detail: str = "high",
) -> dict:
    """Persist one incoming image and return its JSON-safe internal reference."""
    mime_type = media.mime
    if media.file_type == "path":
        raw_data = await asyncio.to_thread(Path(media.file).read_bytes)
    elif media.file_type == "url":
        local_path = Path(await media.to_path())
        raw_data = await asyncio.to_thread(local_path.read_bytes)
    else:
        encoded_data = await media.to_base64()
        try:
            raw_data = base64.b64decode(encoded_data, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("Incoming media contains invalid base64") from exc

    content_hash = hashlib.sha256(raw_data).hexdigest()
    target = _message_directory(session_id, message_id) / (
        content_hash + _extension_for_mime(mime_type)
    )

    def write_media() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(raw_data)

    await asyncio.to_thread(write_media)
    return {
        "type": MEDIA_REF_TYPE,
        "path": target.relative_to(get_data_path()).as_posix(),
        "mime_type": mime_type or "image/jpeg",
        "detail": detail,
    }


async def resolve_media_reference(reference: dict) -> dict:
    """Convert an internal media reference into an OpenAI image_url content part."""
    relative_path = reference.get("path")
    if not isinstance(relative_path, str) or not relative_path:
        raise ValueError("Media reference has no path")

    root = _media_root().resolve()
    target = (get_data_path() / relative_path).resolve()
    if not is_within_directory(root, target) or not target.is_file():
        raise ValueError("Media reference points outside session media or no longer exists")

    raw_data = await asyncio.to_thread(target.read_bytes)
    mime_type = reference.get("mime_type") or mimetypes.guess_type(target.name)[0] or "image/jpeg"
    encoded_data = base64.b64encode(raw_data).decode("ascii")
    image_url = {"url": f"data:{mime_type};base64,{encoded_data}"}
    if reference.get("detail"):
        image_url["detail"] = reference["detail"]
    return {"type": "image_url", "image_url": image_url}


async def resolve_media_references(messages: Iterable[object]) -> list[dict]:
    """Return provider-ready message dictionaries without mutating stored history."""
    resolved_messages: list[dict] = []
    for raw_message in messages:
        message = raw_message if isinstance(raw_message, dict) else raw_message.to_dict()
        resolved_message = dict(message)
        content = message.get("content")
        if isinstance(content, list):
            resolved_content = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == MEDIA_REF_TYPE:
                    resolved_content.append(await resolve_media_reference(part))
                else:
                    resolved_content.append(part)
            resolved_message["content"] = resolved_content
        resolved_messages.append(resolved_message)
    return resolved_messages


def collect_media_reference_paths(memory: Iterable[object]) -> set[str]:
    """Collect media paths still referenced by the serialized session history."""
    paths: set[str] = set()
    for chunk in memory:
        messages = chunk if isinstance(chunk, list) else []
        for message in messages:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") == MEDIA_REF_TYPE
                    and isinstance(part.get("path"), str)
                ):
                    paths.add(part["path"])
    return paths


def cleanup_session_media(session_id: str, memory: Iterable[object]) -> None:
    """Delete media files no longer referenced by a retained session history."""
    session_dir = _session_directory(session_id)
    if not session_dir.is_dir():
        return
    retained = {
        (get_data_path() / path).resolve()
        for path in collect_media_reference_paths(memory)
    }
    for directory, _, filenames in os.walk(session_dir, topdown=False):
        directory_path = Path(directory)
        for filename in filenames:
            file_path = (directory_path / filename).resolve()
            if file_path not in retained:
                file_path.unlink(missing_ok=True)
        if directory_path != session_dir and not any(directory_path.iterdir()):
            directory_path.rmdir()
    if not any(session_dir.iterdir()):
        session_dir.rmdir()
