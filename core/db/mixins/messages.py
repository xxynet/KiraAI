"""Persistence, queries and retention for structured message records."""

from __future__ import annotations

import copy
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..db_mgr import DatabaseManager
from ..models import MessageRecord


class MessageHistoryMixin:
    db: DatabaseManager

    @staticmethod
    def _message_record(row: MessageRecord) -> dict:
        return {column.name: copy.deepcopy(getattr(row, column.name))
                for column in MessageRecord.__table__.columns if column.name != "dedup_key"}

    async def add_message_record(self, **values) -> str:
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

    async def update_message_delivery(self, record_id: str, *, status: str,
                                      platform_message_id: str | None = None, error_type: str | None = None) -> None:
        async with self.db.transaction() as session:
            await session.execute(update(MessageRecord).where(MessageRecord.id == record_id).values(
                status=status, platform_message_id=platform_message_id, error_type=error_type))

    async def get_message_record(self, message_id: str) -> dict | None:
        async with self.db.get_session() as session:
            row = await session.get(MessageRecord, message_id)
            return self._message_record(row) if row else None

    async def list_message_records(self, session_id: str, *, cursor: str | None = None,
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
        return {"messages": [self._message_record(row) for row in rows[:limit]],
                "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

    async def list_message_sessions(self) -> list[dict]:
        async with self.db.get_session() as session:
            rows = (await session.execute(select(
                MessageRecord.session_id, func.count().label("message_count")
            ).group_by(MessageRecord.session_id))).all()
        return [{"session_id": row.session_id, "message_count": row.message_count} for row in rows]

    async def link_message_records(self, session_id: str, llm_message_id: str,
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

    async def mark_pending_messages_unknown(self) -> None:
        # A process crash after sending leaves delivery ambiguous; never resend automatically.
        async with self.db.transaction() as session:
            await session.execute(update(MessageRecord).where(
                MessageRecord.status == "pending").values(status="unknown"))

    async def delete_session_message_records(self, session_id: str) -> None:
        async with self.db.transaction() as session:
            await session.execute(delete(MessageRecord).where(MessageRecord.session_id == session_id))

    @asynccontextmanager
    async def stream_message_chains(self) -> AsyncIterator[AsyncIterator[list[dict]]]:
        """Stream stored chains while keeping the cursor lifetime explicit."""
        async with self.db.get_session() as session:
            chains = await session.stream_scalars(
                select(MessageRecord.chain).execution_options(yield_per=500)
            )
            try:
                yield chains
            finally:
                await chains.close()

    async def prune_message_records(
        self, *, cutoff: int | None, max_messages_per_session: int, protected: set[str],
    ) -> int:
        """Delete at most 5000 records, preserving pending and in-flight messages."""
        if max_messages_per_session < 0:
            raise ValueError("max_messages_per_session must not be negative")
        total = 0
        async with self.db.get_session() as session:
            sessions = (await session.scalars(select(MessageRecord.session_id).distinct())).all()
        for session_id in sessions:
            conditions = []
            if cutoff is not None:
                conditions.append(MessageRecord.created_at < cutoff)
            if max_messages_per_session:
                async with self.db.get_session() as session:
                    boundary = (await session.execute(select(MessageRecord.created_at, MessageRecord.id).where(
                        MessageRecord.session_id == session_id
                    ).order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc()).offset(
                        max_messages_per_session
                    ).limit(1))).first()
                if boundary:
                    conditions.append(or_(
                        MessageRecord.created_at < boundary.created_at,
                        and_(MessageRecord.created_at == boundary.created_at, MessageRecord.id <= boundary.id),
                    ))
            if not conditions:
                continue
            cursor = None
            while total < 5000:
                query = select(MessageRecord.id, MessageRecord.created_at).where(
                    MessageRecord.session_id == session_id,
                    MessageRecord.status != "pending",
                    or_(*conditions),
                )
                if cursor:
                    query = query.where(or_(
                        MessageRecord.created_at > cursor.created_at,
                        and_(MessageRecord.created_at == cursor.created_at, MessageRecord.id > cursor.id),
                    ))
                async with self.db.transaction() as session:
                    rows = (await session.execute(query.order_by(
                        MessageRecord.created_at, MessageRecord.id
                    ).limit(min(500, 5000 - total)))).all()
                    if not rows:
                        break
                    ids = [row.id for row in rows if row.id not in protected]
                    if ids:
                        await session.execute(delete(MessageRecord).where(MessageRecord.id.in_(ids)))
                        total += len(ids)
                    cursor = rows[-1]
            if total >= 5000:
                break
        return total
