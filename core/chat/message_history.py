"""Structured message history and links to retained conversation memory."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import os
import time
import uuid
import weakref
from contextlib import asynccontextmanager
from pathlib import Path

from core.chat.message_elements import BaseMediaElement, Json, Reply
from core.db.service import DatabaseService
from core.logging_manager import get_logger
from core.utils.media_refs import MEDIA_ROOT_NAME
from core.utils.path_utils import get_data_path
from core.utils.network import download_file

logger = get_logger("message_history", "cyan")


def _archive_media(file: str, file_type: str, archive_root: Path | None = None) -> str:
    """Archive media outside memory cleanup; never persist credential-bearing URLs."""
    # Memory cleanup only visits hashed session directories, leaving archives intact.
    root = archive_root if archive_root is not None else get_data_path() / MEDIA_ROOT_NAME / "archive"
    root.mkdir(parents=True, exist_ok=True)
    if file_type == "url":
        downloaded = root / (uuid.uuid4().hex + ".download")
        try:
            # This function runs in a worker thread, including the helper's file IO.
            asyncio.run(asyncio.wait_for(download_file(
                file, str(downloaded), timeout=10.0, max_bytes=20 * 1024 * 1024,
            ), timeout=12.0))
            return _archive_media(str(downloaded), "path", archive_root)
        finally:
            downloaded.unlink(missing_ok=True)
    temporary = root / (uuid.uuid4().hex + ".tmp")
    digest = hashlib.sha256()
    try:
        with temporary.open("wb") as output:
            if file_type == "path":
                with Path(file).open("rb") as source:
                    while data := source.read(1024 * 1024):
                        digest.update(data)
                        output.write(data)
            else:
                encoded = file.split(",", 1)[1] if file_type == "data_url" else file.removeprefix("base64://")
                data = base64.b64decode(encoded, validate=True)
                digest.update(data)
                output.write(data)
        target = root / digest.hexdigest()
        os.replace(temporary, target)
        return target.name if archive_root is not None else target.relative_to(get_data_path()).as_posix()
    finally:
        temporary.unlink(missing_ok=True)


async def serialize_message_chain(chain, *, depth: int = 0, archive_root: Path | None = None) -> list[dict]:
    """Serialize declared element fields; never persist runtime objects or payloads."""
    if depth > 2:
        return [{"type": "unsupported", "reason": "nesting_limit"}]
    result = []
    fields = {
        "text": ("text",), "at": ("pid", "nickname"),
        "emoji": ("emoji_id", "emoji_desc"), "notice": ("text",), "poke": ("pid",),
    }
    for element in chain:
        element_type = getattr(element.type, "value", "unsupported")
        item = {"type": element_type}
        if isinstance(element, BaseMediaElement):
            for key in ("name", "mime", "size", "caption", "transcript", "description", "sticker_id"):
                value = getattr(element, key, None)
                if value is not None:
                    item[key] = value
            file = element.file
            if file and element.file_type in {"path", "base64", "data_url", "url"}:
                try:
                    item["file"] = await asyncio.to_thread(_archive_media, file, element.file_type, archive_root)
                    item["file_type"] = "archive"
                except Exception as exc:
                    item["file_type"] = "unavailable"
                    logger.warning("Unable to archive message media (%s)", type(exc).__name__)
            elif file:
                item["file_type"] = "unavailable"
        elif isinstance(element, Reply):
            item.update(message_id=element.message_id, message_content=element.message_content)
            if element.chain:
                item["chain"] = await serialize_message_chain(element.chain, depth=depth + 1, archive_root=archive_root)
        elif isinstance(element, Json):
            item["data"] = copy.deepcopy(element.data)
        else:
            for key in fields.get(element_type, ()):
                item[key] = getattr(element, key, None)
        result.append(item)
    return result


class MessageHistoryService:
    def __init__(self, db: DatabaseService, session_manager):
        self.db = db
        self.session_manager = session_manager
        self._archive_gate = asyncio.Lock()
        self._archive_tasks: set[asyncio.Task] = set()
        self._incoming_records: dict[int, tuple[weakref.ReferenceType, str]] = {}

    async def record_incoming_safely(self, message, session_id, platform):
        """Preserve message processing when incoming archival fails."""
        try:
            return await self.record_incoming(message, session_id, platform)
        except Exception as exc:
            get_logger("message", "cyan").error(
                "Unable to store incoming message (%s)", type(exc).__name__)

    async def _persist_chain(self, chain, **values) -> str:
        async def persist():
            return await self.db.add_message_record(chain=await serialize_message_chain(chain), **values)

        # Publish files and their database references as one protected operation.
        # Concurrent archives remain allowed; maintenance waits for a quiet point.
        async with self._archive_gate:
            task = asyncio.create_task(persist())
            self._archive_tasks.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # A worker thread cannot be cancelled halfway through a file write.
            try:
                await task
            finally:
                raise
        finally:
            self._archive_tasks.discard(task)

    @asynccontextmanager
    async def maintenance(self):
        """Exclude new archives and protect messages still held by receive processing."""
        async with self._archive_gate:
            if self._archive_tasks:
                yield None
                return
            yield {record_id for reference, record_id in self._incoming_records.values()
                   if reference() is not None}

    async def record_incoming(self, message, session_id: str, platform: str) -> str:
        cached = self._incoming_records.get(id(message))
        if cached is not None and cached[0]() is message:
            return cached[1]
        platform_id = str(message.message_id) if message.message_id is not None else None
        dedup_key = None
        if platform_id and platform_id.lower() not in {"none", "null", "system_message"}:
            identity = [session_id, message.self_id, platform_id, "incoming"]
            dedup_key = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        # Freeze before the first await, so later processing cannot rewrite the snapshot.
        snapshot = copy.deepcopy(message.chain)
        record_id = await self._persist_chain(snapshot,
            session_id=session_id, self_id=message.self_id, platform=platform,
            platform_message_id=platform_id, dedup_key=dedup_key,
            direction="incoming", is_notice=message.is_notice, is_mentioned=message.is_mentioned,
            sender_id=message.sender.user_id if message.sender else None,
            sender_name=message.sender.nickname if message.sender else None,
            timestamp=message.timestamp, status="received",
        )
        # Track the single-message to batch lifecycle without modifying message fields.
        # Weak references release entries when buffered or discarded messages are freed.
        key = id(message)
        records = self._incoming_records
        records[key] = (weakref.ref(message, lambda _: records.pop(key, None)), record_id)
        return record_id

    async def record_outgoing(self, session_id: str, chain, *, platform: str,
                              self_id: str | None, llm_message_id: str | None = None) -> str:
        snapshot = copy.deepcopy(chain)
        return await self._persist_chain(snapshot,
            session_id=session_id, self_id=self_id, platform=platform,
            direction="outgoing", sender_id=self_id, sender_name=None,
            llm_message_id=llm_message_id,
            timestamp=int(time.time()), status="pending",
        )

    async def finish_outgoing(self, record_id: str, *, status: str,
                              platform_message_id: str | None = None, error_type: str | None = None):
        await self.db.update_message_delivery(
            record_id, status=status, platform_message_id=platform_message_id, error_type=error_type,
        )

    async def on_session_deleted(self, event) -> None:
        await self.delete_session_messages(event.payload["session"])

    async def delete_session_messages(self, session_id: str) -> None:
        """Delete a session's archive after its outstanding archive writes finish."""
        async def remove():
            async with self._archive_gate:
                if self._archive_tasks:
                    await asyncio.gather(*tuple(self._archive_tasks), return_exceptions=True)
                await self.db.delete_session_message_records(session_id)
                # Keep live receive identities so a buffered message cannot be re-archived.

        task = asyncio.create_task(remove())
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def get_message(self, message_id: str) -> dict | None:
        return await self.db.get_message_record(message_id)

    async def list_messages(self, session_id: str, *, cursor: str | None = None,
                            limit: int = 50, llm_message_id: str | None = None) -> dict:
        return await self.db.list_message_records(
            session_id, cursor=cursor, limit=limit, llm_message_id=llm_message_id,
        )

    async def get_messages_by_llm_message_id(self, session_id: str, llm_message_id: str,
                                        *, cursor: str | None = None, limit: int = 50) -> dict:
        return await self.list_messages(session_id, llm_message_id=llm_message_id, cursor=cursor, limit=limit)

    def get_linked_memory(self, record: dict) -> dict | None:
        identity = record.get("llm_message_id")
        if not identity:
            return None
        memory = self.session_manager.get_existing_memory_snapshot(record["session_id"]) or []
        for chunk in memory:
            for message in chunk:
                if message.get("_extra", {}).get("llm_message_id") == identity:
                    return message
        return None

    async def list_sessions(self) -> list[dict]:
        return await self.db.list_message_sessions()

    async def link_incoming_messages(self, session_id: str, llm_message_id: str,
                                     message_ids: list[str]) -> None:
        """Persist source links in the database without adding reverse links to memory."""
        await self.db.link_message_records(session_id, llm_message_id, message_ids)

    async def initialize(self):
        await self.db.mark_pending_messages_unknown()
