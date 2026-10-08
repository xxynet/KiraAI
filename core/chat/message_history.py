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
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from core.chat.message_elements import BaseMediaElement, Forward, Json, Reply
from core.db.models import MessageRecord
from core.logging_manager import get_logger
from core.utils.media_refs import MEDIA_ROOT_NAME
from core.utils.path_utils import get_data_path
from core.utils.network import download_file

logger = get_logger("message_history", "cyan")


def _archive_media(file: str, file_type: str) -> str:
    """Archive media outside memory cleanup; never persist credential-bearing URLs."""
    # Memory cleanup only visits hashed session directories, leaving archives intact.
    root = get_data_path() / MEDIA_ROOT_NAME / "archive"
    root.mkdir(parents=True, exist_ok=True)
    if file_type == "url":
        downloaded = root / (uuid.uuid4().hex + ".download")
        try:
            # This function runs in a worker thread, including the helper's file IO.
            asyncio.run(asyncio.wait_for(download_file(
                file, str(downloaded), timeout=10.0, max_bytes=20 * 1024 * 1024,
            ), timeout=12.0))
            return _archive_media(str(downloaded), "path")
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
        return target.relative_to(get_data_path()).as_posix()
    finally:
        temporary.unlink(missing_ok=True)


async def serialize_message_chain(chain, *, depth: int = 0) -> list[dict]:
    """Serialize declared element fields; never persist runtime objects or payloads."""
    if depth > 32:
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
                    item["file"] = await asyncio.to_thread(_archive_media, file, element.file_type)
                    item["file_type"] = "archive"
                except Exception as exc:
                    item["file_type"] = "unavailable"
                    logger.warning("Unable to archive message media (%s)", type(exc).__name__)
            elif file:
                item["file_type"] = "unavailable"
        elif isinstance(element, Reply):
            item.update(message_id=element.message_id, message_content=element.message_content)
            if element.chain:
                item["chain"] = await serialize_message_chain(element.chain, depth=depth + 1)
        elif isinstance(element, Forward):
            item.update(message_id=copy.deepcopy(element.message_id), merge=element.merge)
            item["chains"] = [await serialize_message_chain(c, depth=depth + 1) for c in element.chains]
        elif isinstance(element, Json):
            item["data"] = copy.deepcopy(element.data)
        else:
            for key in fields.get(element_type, ()):
                item[key] = getattr(element, key, None)
        result.append(item)
    return result


class MessageHistoryService:
    def __init__(self, db, session_manager):
        self.db = db.db
        self.session_manager = session_manager
        self._incoming_records: dict[int, tuple[weakref.ReferenceType, str]] = {}

    @staticmethod
    def _record(row) -> dict:
        return {column.name: copy.deepcopy(getattr(row, column.name))
                for column in MessageRecord.__table__.columns if column.name != "dedup_key"}

    async def _insert(self, **values) -> str:
        values.update(id=uuid.uuid4().hex, created_at=time.time_ns() // 1_000_000, schema_version=1)
        try:
            async with self.db.transaction() as session:
                session.add(MessageRecord(**values))
        except IntegrityError:
            if not values.get("dedup_key"):
                raise
            async with self.db.get_session() as session:
                identity = await session.scalar(select(MessageRecord.id).where(
                    MessageRecord.dedup_key == values["dedup_key"]))
            if identity is None:
                raise
            return identity
        return values["id"]

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
        record_id = await self._insert(
            session_id=session_id, self_id=message.self_id, platform=platform,
            platform_message_id=platform_id, dedup_key=dedup_key,
            direction="incoming", is_notice=message.is_notice, is_mentioned=message.is_mentioned,
            sender_id=message.sender.user_id if message.sender else None,
            sender_name=message.sender.nickname if message.sender else None,
            timestamp=message.timestamp, chain=await serialize_message_chain(snapshot), status="received",
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
        return await self._insert(
            session_id=session_id, self_id=self_id, platform=platform,
            direction="outgoing", sender_id=self_id, sender_name=None,
            llm_message_id=llm_message_id,
            timestamp=int(time.time()), chain=await serialize_message_chain(snapshot), status="pending",
        )

    async def finish_outgoing(self, record_id: str, *, status: str,
                              platform_message_id: str | None = None, error_type: str | None = None):
        async with self.db.transaction() as session:
            await session.execute(update(MessageRecord).where(MessageRecord.id == record_id).values(
                status=status, platform_message_id=platform_message_id, error_type=error_type))

    async def get_message(self, message_id: str) -> dict | None:
        async with self.db.get_session() as session:
            row = await session.get(MessageRecord, message_id)
            return self._record(row) if row else None

    async def list_messages(self, session_id: str, *, cursor: str | None = None,
                            limit: int = 50, llm_message_id: str | None = None) -> dict:
        if not 1 <= limit <= 200:
            raise ValueError("limit must be between 1 and 200")
        query = select(MessageRecord).where(MessageRecord.session_id == session_id)
        if llm_message_id:
            query = query.where(MessageRecord.llm_message_id == llm_message_id)
        async with self.db.get_session() as session:
            if cursor:
                previous = await session.get(MessageRecord, cursor)
                if not previous or previous.session_id != session_id:
                    raise ValueError("Invalid message cursor")
                query = query.where(or_(
                    MessageRecord.created_at < previous.created_at,
                    and_(MessageRecord.created_at == previous.created_at, MessageRecord.id < previous.id)))
            rows = list((await session.scalars(query.order_by(
                MessageRecord.created_at.desc(), MessageRecord.id.desc()).limit(limit + 1))).all())
        return {"messages": [self._record(row) for row in rows[:limit]],
                "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

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
        async with self.db.get_session() as session:
            rows = (await session.execute(select(
                MessageRecord.session_id, func.count().label("message_count")
            ).group_by(MessageRecord.session_id))).all()
        return [{"session_id": row.session_id, "message_count": row.message_count} for row in rows]

    async def link_incoming_messages(self, session_id: str, llm_message_id: str,
                                     message_ids: list[str]) -> None:
        """Persist source links in the database without adding reverse links to memory."""
        if not message_ids:
            return
        async with self.db.transaction() as session:
            await session.execute(update(MessageRecord).where(
                MessageRecord.session_id == session_id,
                MessageRecord.direction == "incoming",
                MessageRecord.id.in_(message_ids),
            ).values(llm_message_id=llm_message_id))

    async def initialize(self):
        # A process crash after sending leaves delivery ambiguous; never resend automatically.
        async with self.db.transaction() as session:
            await session.execute(update(MessageRecord).where(
                MessageRecord.status == "pending").values(status="unknown"))
