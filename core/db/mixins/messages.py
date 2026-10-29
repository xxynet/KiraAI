"""Persistence, queries and retention for structured message records."""

from __future__ import annotations

import asyncio
import copy
import json
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError

from ..db_mgr import DatabaseManager
from ..models import MessageRecord


def _message_chain_matches(chain: list[dict], keyword: str, *, depth: int = 0) -> bool:
    """Search visible text, including quoted text, without matching storage metadata."""
    if depth > 2:
        return False
    text_fields = {
        "text": ("text",), "notice": ("text",), "at": ("nickname",),
        "emoji": ("emoji_desc",), "reply": ("message_content",),
        **{kind: ("name", "caption", "description", "transcript")
           for kind in ("image", "sticker", "record", "video", "file")},
    }
    for element in chain:
        kind = element.get("type")
        for key in text_fields.get(kind, ()):
            value = element.get(key)
            if isinstance(value, str) and keyword in value.casefold():
                return True
        if kind == "json" and keyword in json.dumps(element.get("data", {}), ensure_ascii=False).casefold():
            return True
        if kind == "reply" and _message_chain_matches(element.get("chain") or [], keyword, depth=depth + 1):
            return True
    return False


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

    @staticmethod
    def _message_record_conditions(
        *, internal_message_id: str | None = None, session_id: str | None = None,
        platform_message_id: str | int | None = None, self_id: str | None = None,
        direction: str | None = None, llm_message_id: str | None = None,
    ) -> list:
        if direction not in {None, "incoming", "outgoing"}:
            raise ValueError("direction must be incoming or outgoing")
        filters = (
            (MessageRecord.id, internal_message_id),
            (MessageRecord.session_id, session_id),
            (MessageRecord.platform_message_id,
             str(platform_message_id) if platform_message_id is not None else None),
            (MessageRecord.self_id, self_id),
            (MessageRecord.direction, direction),
            (MessageRecord.llm_message_id, llm_message_id),
        )
        conditions = [column == value for column, value in filters if value is not None]
        if not conditions:
            raise ValueError("At least one message filter is required")
        return conditions

    async def get_message_record(
        self, internal_message_id: str | None = None, *, session_id: str | None = None,
        platform_message_id: str | int | None = None, self_id: str | None = None,
        direction: str | None = None,
    ) -> dict | None:
        """Return the most recently archived record matching all supplied filters."""
        conditions = self._message_record_conditions(
            internal_message_id=internal_message_id, session_id=session_id,
            platform_message_id=platform_message_id, self_id=self_id, direction=direction,
        )
        query = select(MessageRecord).where(*conditions).order_by(
            MessageRecord.created_at.desc(), MessageRecord.id.desc(),
        ).limit(1)
        async with self.db.get_session() as session:
            row = await session.scalar(query)
            return self._message_record(row) if row else None

    async def list_message_records(
        self, session_id: str | None = None, *, cursor: str | None = None,
        limit: int = 50, llm_message_id: str | None = None, internal_message_id: str | None = None,
        platform_message_id: str | int | None = None, self_id: str | None = None,
        direction: str | None = None, keyword: str | None = None,
    ) -> dict:
        """Page through retained records, applying literal text search before pagination."""
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise ValueError("limit must be an integer between 1 and 200")
        if keyword is not None and (not isinstance(keyword, str) or len(keyword) > 200):
            raise ValueError("keyword must be a string of at most 200 characters")
        keyword = keyword.casefold() if keyword else None
        conditions = self._message_record_conditions(
            internal_message_id=internal_message_id, session_id=session_id,
            platform_message_id=platform_message_id, self_id=self_id, direction=direction,
            llm_message_id=llm_message_id or None,
        )
        query = select(MessageRecord).where(*conditions)
        async with self.db.get_session() as session:
            if cursor:
                previous = await session.scalar(query.where(MessageRecord.id == cursor))
                if previous is None or (keyword and not await asyncio.to_thread(
                    _message_chain_matches, previous.chain, keyword,
                )):
                    raise ValueError("Invalid message cursor")
                query = query.where(or_(
                    MessageRecord.created_at < previous.created_at,
                    and_(MessageRecord.created_at == previous.created_at, MessageRecord.id < previous.id)))
            query = query.order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc())
            if keyword:
                # Stream bounded batches so text search does not load an entire session.
                stream = await session.stream_scalars(query.execution_options(yield_per=100))
                rows = []
                try:
                    async for batch in stream.partitions(100):
                        matches = await asyncio.to_thread(
                            lambda items: [row for row in items if _message_chain_matches(row.chain, keyword)], batch,
                        )
                        rows.extend(matches[:limit + 1 - len(rows)])
                        if len(rows) > limit:
                            break
                finally:
                    await stream.close()
            else:
                rows = list((await session.scalars(query.limit(limit + 1))).all())
        return {"messages": [self._message_record(row) for row in rows[:limit]],
                "next_cursor": rows[limit - 1].id if len(rows) > limit else None}

    async def get_message_session_stats(self, session_id: str) -> dict:
        """Return counts and platform message times without loading message bodies."""
        query = select(
            func.count().label("message_count"),
            func.sum(case((MessageRecord.direction == "incoming", 1), else_=0)).label("incoming_count"),
            func.sum(case((MessageRecord.direction == "outgoing", 1), else_=0)).label("outgoing_count"),
            func.min(MessageRecord.timestamp).label("first_message_at"),
            func.max(MessageRecord.timestamp).label("last_message_at"),
        ).where(MessageRecord.session_id == session_id)
        async with self.db.get_session() as session:
            row = (await session.execute(query)).mappings().one()
        return {**row, "incoming_count": row["incoming_count"] or 0, "outgoing_count": row["outgoing_count"] or 0}

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
