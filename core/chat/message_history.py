"""Structured message history and links to retained conversation memory."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
import os
import re
import time
import uuid
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field, fields
from pathlib import Path

from core.chat.message_elements import (
    At,
    BaseMediaElement,
    BaseMessageElement,
    ElementType,
    Emoji,
    File,
    Forward,
    Image,
    Json,
    Notice,
    Poke,
    Record,
    Reply,
    Sticker,
    Text,
    Video,
)
from core.chat.message_utils import MessageChain
from core.db.service import DatabaseService
from core.logging_manager import get_logger
from core.utils.media_refs import MEDIA_ROOT_NAME
from core.utils.network import download_file
from core.utils.path_utils import get_data_path, is_within_directory

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


@dataclass
class ArchivedMessagePlaceholder(BaseMessageElement):
    """Retain the type and metadata of an element whose payload is unavailable."""

    type: ElementType | None
    data: dict

    @property
    def repr(self) -> str:
        return f"[{self.type.name}]" if self.type is not None else "[Unsupported message]"


def _deserialize_message_chain(data: list[dict], *, depth: int = 0) -> MessageChain:
    """Restore declared element fields without fetching media or forward contents."""
    if depth > 2:
        return MessageChain([ArchivedMessagePlaceholder(None, {"reason": "nesting_limit"})])
    elements = []
    media_types = {
        "image": (Image, "image"), "sticker": (Sticker, "sticker"),
        "record": (Record, "record"), "video": (Video, "file"), "file": (File, "file"),
    }
    for item in data:
        element_type = item.get("type")
        if element_type == "text":
            element = Text(item.get("text"))
        elif element_type == "at":
            element = At(item.get("pid"), item.get("nickname"))
        elif element_type == "emoji":
            element = Emoji(item.get("emoji_id"), item.get("emoji_desc"))
        elif element_type == "notice":
            element = Notice(item.get("text"))
        elif element_type == "poke":
            element = Poke(item.get("pid"))
        elif element_type == "json":
            element = Json(copy.deepcopy(item.get("data", {})))
        elif element_type == "reply":
            nested = item.get("chain")
            element = Reply(
                item.get("message_id"), item.get("message_content"),
                _deserialize_message_chain(nested, depth=depth + 1) if nested is not None else None,
            )
        elif element_type == "forward":
            # Forward archives deliberately contain only a display placeholder.
            element = Forward()
        elif element_type in media_types:
            element = ArchivedMessagePlaceholder(ElementType(element_type), copy.deepcopy(item))
            file = item.get("file")
            if (item.get("file_type") == "archive" and isinstance(file, str)
                    and re.fullmatch(rf"{MEDIA_ROOT_NAME}/archive/[0-9a-f]{{64}}", file)):
                try:
                    root = get_data_path() / MEDIA_ROOT_NAME / "archive"
                    target = (get_data_path() / file).resolve()
                    if is_within_directory(root, target) and target.is_file():
                        element_class, argument = media_types[element_type]
                        element = element_class(**{argument: str(target)}, mime=item.get("mime"))
                        for key in ("name", "mime", "size", "caption", "transcript", "description", "sticker_id"):
                            if key in item:
                                setattr(element, key, copy.deepcopy(item[key]))
                except (OSError, ValueError):
                    pass
        else:
            element = ArchivedMessagePlaceholder(None, copy.deepcopy(item))
        elements.append(element)
    return MessageChain(elements)


@dataclass
class MessageHistoryRecord:
    """An archived message with runtime elements and its original JSON snapshot."""

    id: str
    session_id: str
    self_id: str | None
    platform: str
    platform_message_id: str | None
    is_notice: bool
    is_mentioned: bool | None
    direction: str
    sender_id: str | None
    sender_name: str | None
    timestamp: int
    created_at: int
    chain: MessageChain
    status: str
    error_type: str | None
    llm_message_id: str | None
    schema_version: int
    _serialized_chain: list[dict] = field(repr=False, compare=False)

    @classmethod
    def from_dict(cls, record: dict) -> MessageHistoryRecord:
        """Restore an archive record; callers should move filesystem checks off-loop."""
        values = copy.deepcopy(record)
        serialized = values.pop("chain")
        return cls(
            **values, chain=_deserialize_message_chain(serialized), _serialized_chain=serialized,
        )

    def to_dict(self) -> dict:
        """Export the archive snapshot, preserving stored media paths and placeholders.

        Runtime chain edits do not rewrite the original serialized chain.
        """
        return {
            item.name: copy.deepcopy(self._serialized_chain if item.name == "chain"
                                     else getattr(self, item.name))
            for item in fields(self) if not item.name.startswith("_")
        }


@dataclass
class MessageHistoryPage:
    """A page of typed message history records and its continuation cursor."""

    messages: list[MessageHistoryRecord] = field(default_factory=list)
    next_cursor: str | None = None

    def to_dict(self) -> dict:
        """Export JSON-safe archive snapshots using the existing pagination format."""
        return {
            "messages": [record.to_dict() for record in self.messages],
            "next_cursor": self.next_cursor,
        }


@dataclass
class MessageHistorySession:
    """The retained message count for one routed session."""

    session_id: str
    message_count: int

    def to_dict(self) -> dict:
        return {"session_id": self.session_id, "message_count": self.message_count}


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
                              self_id: str | None, llm_message_id: str | None = None,
                              sender_name: str | None = None) -> str:
        snapshot = copy.deepcopy(chain)
        return await self._persist_chain(snapshot,
            session_id=session_id, self_id=self_id, platform=platform,
            direction="outgoing", sender_id=self_id, sender_name=sender_name,
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

    async def get_message(
        self, internal_message_id: str | None = None, *, session_id: str | None = None,
        platform_message_id: str | int | None = None, self_id: str | None = None,
        direction: str | None = None,
    ) -> MessageHistoryRecord | None:
        """Look up a locally archived message matching all supplied filters.

        internal_message_id is the internal history record ID, while platform_message_id
        is the adapter's message ID. Supply session_id to scope platform IDs.
        At least one filter is required; None means that filter is omitted.
        Return a MessageHistoryRecord whose chain is a MessageChain,
        or None if no retained record matches. This does not fetch the platform.
        If multiple records match, return the most recently archived one, using
        the internal record ID to break ties in archive time.
        """
        record = await self.db.get_message_record(
            internal_message_id=internal_message_id, session_id=session_id,
            platform_message_id=platform_message_id,
            self_id=self_id, direction=direction,
        )
        if record is None:
            return None
        return await asyncio.to_thread(MessageHistoryRecord.from_dict, record)

    async def get_messages(
        self, internal_message_id: str | None = None, *, session_id: str | None = None,
        platform_message_id: str | int | None = None, self_id: str | None = None,
        direction: str | None = None, cursor: str | None = None, limit: int = 50,
        keyword: str | None = None,
    ) -> MessageHistoryPage:
        """Return a page of local history records matching all supplied filters.

        Filters have the same meaning as get_message; at least one is required.
        messages contains MessageHistoryRecord objects ordered by archive time, then
        internal ID, newest first. Return a page with an empty messages list
        when no records match. limit must be between 1 and 200.
        Pass next_cursor as cursor with the same filters to fetch the next page.
        The cursor must identify a retained record matching the supplied filters.
        keyword optionally matches visible text by case-insensitive literal substring
        before pagination; it never matches storage paths or routing metadata.
        """
        page = await self.db.list_message_records(
            session_id, internal_message_id=internal_message_id, platform_message_id=platform_message_id,
            self_id=self_id, direction=direction, cursor=cursor, limit=limit, keyword=keyword,
        )
        return await self._restore_page(page)

    async def _restore_page(self, page: dict) -> MessageHistoryPage:
        if page["messages"]:
            records = await asyncio.to_thread(
                lambda: [MessageHistoryRecord.from_dict(record) for record in page["messages"]],
            )
        else:
            records = []
        return MessageHistoryPage(messages=records, next_cursor=page["next_cursor"])

    async def list_messages(self, session_id: str, *, cursor: str | None = None,
                            limit: int = 50, llm_message_id: str | None = None) -> MessageHistoryPage:
        """Return typed history records for one session, optionally linked to memory."""
        page = await self.db.list_message_records(
            session_id, cursor=cursor, limit=limit, llm_message_id=llm_message_id,
        )
        return await self._restore_page(page)

    async def get_messages_by_llm_message_id(self, session_id: str, llm_message_id: str,
                                        *, cursor: str | None = None, limit: int = 50) -> MessageHistoryPage:
        return await self.list_messages(session_id, llm_message_id=llm_message_id, cursor=cursor, limit=limit)

    async def get_linked_memory(self, record: MessageHistoryRecord) -> dict | None:
        identity, session_id = record.llm_message_id, record.session_id
        if not identity:
            return None
        session = await self.session_manager.get_session(session_id)
        memory = session.content if session is not None else []
        for chunk in memory:
            for message in chunk:
                if message.get("_extra", {}).get("llm_message_id") == identity:
                    return message
        return None

    async def get_session_stats(self, session_id: str) -> dict:
        """Return retained message counts and first/last message times in Unix seconds."""
        return await self.db.get_message_session_stats(session_id)

    async def list_sessions(self) -> list[MessageHistorySession]:
        """Return typed retained-message statistics for each session."""
        return [MessageHistorySession(**row) for row in await self.db.list_message_sessions()]

    async def link_incoming_messages(self, session_id: str, llm_message_id: str,
                                     message_ids: list[str]) -> None:
        """Persist source links in the database without adding reverse links to memory."""
        await self.db.link_message_records(session_id, llm_message_id, message_ids)

    async def initialize(self):
        await self.db.mark_pending_messages_unknown()
