from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Literal, Optional, TYPE_CHECKING, overload

from core.logging_manager import get_logger
from core.config import KiraConfig
from core.utils.path_utils import get_data_path
from core.db.service import DatabaseService

from .session import Session
from .memory_metadata import normalize_memory

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = get_logger("session", "green")
CHAT_MEMORY_PATH: str = f"{get_data_path()}/memory/chat_memory.json"
CORE_MEMORY_PATH: str = f"{get_data_path()}/memory/core.txt"
_FIELD_UNSET = object()


class SessionManager:
    """Read and persist sessions through the database without a resident content cache."""

    def __init__(
        self,
        db: DatabaseService,
        kira_config: KiraConfig,
        event_bus: Optional[EventBus] = None,
    ):
        self.db = db
        self.kira_config = kira_config
        self.event_bus = event_bus
        self.chat_memory_path = CHAT_MEMORY_PATH
        self._write_lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    async def initialize(self) -> None:
        """Import once, preserving the legacy file; later starts use only the database."""
        async with self._write_lock:
            if not await self.db.is_chat_memory_imported():
                records = await asyncio.to_thread(self._load_legacy_memory, self.chat_memory_path)
                await self.db.import_chat_sessions(records)

    @staticmethod
    def _load_legacy_memory(path: str) -> dict:
        """Normalize valid messages without dropping malformed records or rewriting the file."""
        try:
            content = Path(path).read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        try:
            records = json.loads(content) if content.strip() else {}
        except (ValueError, TypeError):
            raise ValueError("Unable to import legacy chat memory: invalid JSON") from None
        if not isinstance(records, dict):
            raise ValueError("Unable to import legacy chat memory: expected a session object")
        for index, (key, data) in enumerate(records.items(), start=1):
            if isinstance(data, list):
                data = {"title": "", "description": "", "timestamp": None, "memory": data}
                records[key] = data
            if not isinstance(data, dict):
                logger.warning("Skipping malformed session entry %d; preserving raw data", index)
                continue
            try:
                data["memory"] = normalize_memory(data.get("memory", []))
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Unable to normalize memory for session entry %d (%s); preserving raw memory",
                    index, type(exc).__name__,
                )
        return records

    async def get_sessions(self) -> list[Session]:
        """Query complete session snapshots without retaining them in the manager."""
        rows = await self.db.list_chat_sessions()
        return [Session.from_record(row) for row in rows
                if len(row["session_key"].split(":", 2)) == 3]

    @overload
    async def get_session(self, session: str, *, ensure_session: Literal[True]) -> Session: ...

    @overload
    async def get_session(self, session: str, *, ensure_session: Literal[False] = False) -> Session | None: ...

    @overload
    async def get_session(self, session: str, *, ensure_session: bool) -> Session | None: ...

    async def get_session(self, session: str, *, ensure_session: bool = False) -> Session | None:
        """Query a snapshot, optionally creating a missing session under the write lock."""
        if ensure_session:
            if len(session.split(":", 2)) != 3:
                raise ValueError("Invalid session routing key")
            async with self._write_lock:
                row = await self.db.get_chat_session(session)
                if row is None:
                    row = await self._save_session(session, {
                        "title": "", "description": "", "content": [], "data": {},
                    })
        else:
            row = await self.db.get_chat_session(session)
        if row is not None and not isinstance(row["data"], dict):
            raise ValueError("Session data must be an object")
        return Session.from_record(row) if row is not None else None

    async def _session_data(self, session: str) -> dict:
        row = await self.db.get_chat_session(session)
        if row is None:
            return {"title": "", "description": "", "content": [], "data": {}}
        if not isinstance(row["data"], dict):
            raise ValueError("Session data must be an object")
        return row

    @asynccontextmanager
    async def maintenance(self):
        """Exclude session writes until reference inspection and media deletion finish."""
        async with self._write_lock:
            yield

    async def _save_session(self, session: str, data: dict, event_type: str = None, payload: dict = None) -> dict:
        """Finish the transaction before publishing events, even if the caller is cancelled."""
        async def persist():
            record = await self.db.save_chat_session(
                session, **{key: data[key] for key in ("title", "description", "content", "data")
                            if key in data},
            )
            if event_type:
                self._publish_session_event(event_type, payload)
            return record

        task = asyncio.create_task(persist())
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise

    async def get_session_metadata(self, session: str, *, ensure_session: bool = False) -> dict:
        """Read event metadata without loading the session's content or extension data."""
        if ensure_session:
            if len(session.split(":", 2)) != 3:
                raise ValueError("Invalid session routing key")
            async with self._write_lock:
                row = await self.db.get_chat_session_metadata(session)
                if row is None:
                    row = await self._save_session(session, {
                        "title": "", "description": "", "content": [], "data": {},
                    })
        else:
            row = await self.db.get_chat_session_metadata(session)
        return {
            "internal_id": row["id"] if row else None,
            "description": row["description"] if row else None,
            "created_at": row["created_at"] if row else None,
            "updated_at": row["updated_at"] if row else None,
        }

    @overload
    async def get_session_info(self, session: None = None) -> List[Session]: ...

    @overload
    async def get_session_info(self, session: str) -> Session: ...

    async def get_session_info(self, session: Optional[str] = None):
        """Query complete sessions without creating a missing session."""
        if session is None:
            return [record for record in await self.get_sessions()
                    if isinstance(record.data, dict)]
        record = await self.get_session(session)
        if record is None:
            record = Session.from_record({
                "session_key": session, "title": "", "description": "", "data": {},
                "content": [], "id": None, "created_at": None, "updated_at": None,
            })
        return record

    async def update_session(
        self, session: str, *, title=_FIELD_UNSET, description=_FIELD_UNSET,
        content=_FIELD_UNSET, data=_FIELD_UNSET,
    ) -> None:
        """Update supplied fields; content and data replace their entire values."""
        changes = {name: value for name, value in (
            ("title", title), ("description", description), ("content", content), ("data", data),
        ) if value is not _FIELD_UNSET}
        if not changes:
            return
        for name in ("title", "description"):
            if name in changes and changes[name] is not None and not isinstance(changes[name], str):
                raise ValueError(f"Session {name} must be a string or null")
        if data is not _FIELD_UNSET and not isinstance(data, dict):
            raise ValueError("Session data must be an object")
        if content is not _FIELD_UNSET:
            normalize_memory(content)
        changes = copy.deepcopy(changes)
        async with self._write_lock:
            event_type, payload = None, None
            if content is not _FIELD_UNSET:
                old_memory = (await self._session_data(session))["content"]
                changes["content"] = normalize_memory(changes["content"], previous=old_memory)
                event_type = "session_memory_written"
                payload = {
                    "session": session, "old_memory": copy.deepcopy(old_memory),
                    "new_memory": copy.deepcopy(changes["content"]),
                }
            await self._save_session(session, changes, event_type, payload)

    @staticmethod
    def _merge_capabilities(global_capabilities: dict, overrides: dict) -> dict:
        merged = copy.deepcopy(global_capabilities)
        for key, value in overrides.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = SessionManager._merge_capabilities(merged[key], value)
            else:
                merged[key] = copy.deepcopy(value)
        return merged

    async def get_effective_capabilities(self, session: str, global_capabilities: dict) -> dict:
        global_config = copy.deepcopy(global_capabilities) if isinstance(global_capabilities, dict) else {}
        row = await self.db.get_chat_session(session)
        data = row["data"] if row else {}
        overrides = data.get("capabilities") if isinstance(data, dict) else None
        if not isinstance(overrides, dict):
            return global_config
        return self._merge_capabilities(global_config, overrides)

    async def update_session_capabilities(self, session: str, capabilities: Optional[dict]):
        if capabilities is not None and not isinstance(capabilities, dict):
            raise ValueError("Session capabilities must be an object or null")
        async with self._write_lock:
            data = await self._session_data(session)
            if capabilities is None:
                data["data"].pop("capabilities", None)
            else:
                data["data"]["capabilities"] = copy.deepcopy(capabilities)
            await self._save_session(session, data)

    async def get_memory_count(self, session: str) -> int:
        memory = await self.get_existing_memory_snapshot(session)
        return len(memory) if isinstance(memory, list) else 0

    async def fetch_memory(self, session: str):
        return [message for chunk in await self.read_memory(session) for message in chunk]

    async def read_memory(self, session: str):
        row = await self.db.get_chat_session(session)
        if row is None:
            return []
        return row["content"] if isinstance(row["data"], dict) else None

    async def get_existing_memory_snapshot(self, session: str) -> Optional[list[list[dict]]]:
        row = await self.db.get_chat_session(session)
        if row is None or not isinstance(row["data"], dict):
            return None
        return row["content"]

    async def write_memory(self, session: str, memory: list[list[dict]]):
        await self.update_session(session, content=memory)
        logger.info(f"Memory written for {session}")

    async def update_memory(self, session: str, new_chunk):
        from core.agent.message import OpenAIMessage

        new_chunk = normalize_memory([[m.to_memory_dict() if isinstance(m, OpenAIMessage) else m for m in new_chunk]])[0]
        async with self._write_lock:
            data = await self._session_data(session)
            data["content"].append(new_chunk)
            max_memory_length, overflow_discard_count = self._get_memory_limits()
            discarded_memory = []
            if len(data["content"]) > max_memory_length:
                overflow_count = len(data["content"]) - max_memory_length
                discard_count = overflow_count + overflow_discard_count - 1
                discarded_memory = copy.deepcopy(data["content"][:discard_count])
                data["content"] = data["content"][discard_count:]
            await self._save_session(session, data, "session_memory_updated", {
                "session": session, "new_chunk": copy.deepcopy(new_chunk), "discarded_memory": discarded_memory,
            })
        logger.info(f"Memory updated for {session}")
        return True

    def _get_memory_limits(self) -> tuple[int, int]:
        """Read the current memory-limit settings so WebUI updates apply immediately."""
        bot_config = self.kira_config["bot_config"].get("bot", {})
        max_memory_length = int(bot_config.get("max_memory_length"))
        configured_discard_count = int(bot_config.get("memory_overflow_discard_count", 1))
        overflow_discard_count = max(
            1, min(configured_discard_count, max_memory_length)
        )
        return max_memory_length, overflow_discard_count

    def _publish_session_event(self, event_type: str, payload: dict) -> None:
        """Queue a session lifecycle event after its state has been persisted."""
        if not getattr(self, "event_bus", None):
            return
        from core.event_bus import SystemEvent

        publish_coro = self.event_bus.publish(
            SystemEvent(event_type=event_type, payload=payload, source="session_manager")
        )
        try:
            task = asyncio.create_task(
                publish_coro,
                name=f"{event_type}_event",
            )
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)
        except RuntimeError:
            publish_coro.close()
            logger.warning("Unable to publish session lifecycle event outside a running event loop")

    async def delete_session(self, session: str):
        """Delete context and notify archive/media subscribers after committing."""
        async with self._write_lock:
            old_memory = await self.get_existing_memory_snapshot(session) or []

            async def remove():
                await self.db.delete_chat_session(session)
                self._publish_session_event("session_deleted", {"session": session, "old_memory": old_memory})

            task = asyncio.create_task(remove())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise
        logger.info(f"Memory deleted for {session}")
