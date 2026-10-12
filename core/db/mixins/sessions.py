"""Database persistence for LLM session records and their legacy import."""

from copy import deepcopy
import time
from uuid import uuid4

from sqlalchemy import delete, select

from core.config import VERSION

from ..db_mgr import DatabaseManager
from ..models import ChatSessionRecord, DatabaseMigration

CHAT_MEMORY_MIGRATION = "chat_memory_json_to_sessions"
_FIELD_UNSET = object()


class ChatSessionMixin:
    db: DatabaseManager

    async def is_chat_memory_imported(self) -> bool:
        async with self.db.get_session() as session:
            return await session.get(DatabaseMigration, CHAT_MEMORY_MIGRATION) is not None

    async def import_chat_sessions(self, records: dict) -> None:
        """Import legacy fields once without overwriting or reviving sessions."""
        imported_at = int(time.time())
        async with self.db.transaction() as session:
            if await session.get(DatabaseMigration, CHAT_MEMORY_MIGRATION) is not None:
                return
            existing = set((await session.scalars(select(ChatSessionRecord.session_key))).all())
            for session_key, record in records.items():
                if session_key in existing:
                    continue
                data = deepcopy(record)
                if isinstance(data, list):
                    data = {"memory": data}
                title, description, content, updated_at = "", "", [], imported_at
                if isinstance(data, dict):
                    title = data.pop("title", "")
                    description = data.pop("description", "")
                    content = data.pop("memory", [])
                    timestamp = data.pop("timestamp", None)
                    if timestamp is not None:
                        updated_at = timestamp
                # Keep unrecognized fields and malformed records for manual repair.
                session.add(ChatSessionRecord(
                    id=f"sess_{uuid4().hex}", session_key=session_key,
                    title=title, description=description, content=content,
                    created_at=imported_at, updated_at=updated_at, data=data,
                ))
            await session.flush()
            session.add(DatabaseMigration(
                name=CHAT_MEMORY_MIGRATION,
                app_version=VERSION,
                executed_at=int(time.time()),
            ))

    @staticmethod
    def _chat_session_record(row: ChatSessionRecord) -> dict:
        return {
            "id": row.id, "session_key": row.session_key,
            "title": row.title, "description": row.description,
            "content": deepcopy(row.content), "created_at": row.created_at,
            "updated_at": row.updated_at, "data": deepcopy(row.data),
        }

    async def get_chat_session_metadata(self, session_key: str) -> dict | None:
        """Read lightweight metadata without loading JSON context or extension data."""
        async with self.db.get_session() as session:
            result = await session.execute(select(
                ChatSessionRecord.id, ChatSessionRecord.title, ChatSessionRecord.description,
                ChatSessionRecord.created_at, ChatSessionRecord.updated_at,
            ).where(ChatSessionRecord.session_key == session_key))
            row = result.mappings().one_or_none()
            return dict(row) if row is not None else None

    async def get_chat_session(self, session_key: str) -> dict | None:
        async with self.db.get_session() as session:
            row = await session.scalar(select(ChatSessionRecord).where(
                ChatSessionRecord.session_key == session_key,
            ))
            return self._chat_session_record(row) if row is not None else None

    async def list_chat_sessions(self) -> list[dict]:
        async with self.db.get_session() as session:
            rows = (await session.scalars(select(ChatSessionRecord))).all()
            return [self._chat_session_record(row) for row in rows]

    async def save_chat_session(
        self, session_key: str, *, title=_FIELD_UNSET, description=_FIELD_UNSET,
        content=_FIELD_UNSET, data=_FIELD_UNSET,
    ) -> dict:
        """Save supplied fields while retaining omitted fields, ID and creation time."""
        updated_at = int(time.time())
        async with self.db.transaction() as session:
            row = await session.scalar(select(ChatSessionRecord).where(
                ChatSessionRecord.session_key == session_key,
            ))
            if row is None:
                row = ChatSessionRecord(
                    id=f"sess_{uuid4().hex}", session_key=session_key, created_at=updated_at,
                    title="", description="", content=[], data={},
                )
                session.add(row)
            for name, value in (("title", title), ("description", description),
                                ("content", content), ("data", data)):
                if value is not _FIELD_UNSET:
                    setattr(row, name, deepcopy(value))
            row.updated_at = updated_at
            record = self._chat_session_record(row)
        return record

    async def delete_chat_session(self, session_key: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(delete(ChatSessionRecord).where(
                ChatSessionRecord.session_key == session_key,
            ))
