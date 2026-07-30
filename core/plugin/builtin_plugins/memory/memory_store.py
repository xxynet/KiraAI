"""SQLAlchemy-backed long-term memory storage.

The store deliberately uses only Python's standard library for tokenization.
Exact lexical tokens are indexed together with low-weight character n-grams so
the same search path works for both whitespace-delimited and non-delimited
languages without a language-specific tokenizer.
"""

from __future__ import annotations

import asyncio
import math
import re
import time
import unicodedata
import uuid
from pathlib import Path
from typing import Iterable, Optional

from sqlalchemy import ForeignKey, Integer, String, Text, Float, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from core.db.db_mgr import DatabaseManager


class MemoryBase(DeclarativeBase):
    pass


class MemoryRecord(MemoryBase):
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, default="global")
    owner_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    importance: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    created_at: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[float] = mapped_column(Float, nullable=False)
    last_accessed_at: Mapped[float] = mapped_column(Float, nullable=False)
    access_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")


class MemoryTerm(MemoryBase):
    __tablename__ = "memory_terms"

    memory_id: Mapped[str] = mapped_column(
        ForeignKey("memory_records.id", ondelete="CASCADE"), primary_key=True
    )
    term: Mapped[str] = mapped_column(String(128), primary_key=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)


class MemoryMigration(MemoryBase):
    __tablename__ = "memory_migrations"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    migrated_at: Mapped[float] = mapped_column(Float, nullable=False)
    imported_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


_TOKEN_RE = re.compile(r"[\w]+", re.UNICODE)


def normalize_text(text: str) -> str:
    return unicodedata.normalize("NFKC", text or "").casefold().strip()


def tokenize(text: str) -> dict[str, float]:
    """Create language-neutral exact tokens and character n-grams."""
    terms: dict[str, float] = {}
    for token in _TOKEN_RE.findall(normalize_text(text)):
        if not token:
            continue
        terms[token] = max(terms.get(token, 0.0), 1.0)

        # Non-ASCII runs commonly represent scripts without whitespace word
        # boundaries. N-grams are deliberately lower-weight fallback signals.
        if not token.isascii():
            for size, weight in ((2, 0.25), (3, 0.35)):
                for index in range(len(token) - size + 1):
                    gram = token[index:index + size]
                    terms[gram] = max(terms.get(gram, 0.0), weight)
    return terms


def _scope_filter(scopes: Iterable[tuple[str, str]]):
    clauses = [
        (MemoryRecord.scope == scope) & (MemoryRecord.owner_id == owner_id)
        for scope, owner_id in scopes
    ]
    return or_(*clauses) if clauses else False


class MemoryStore:
    """Long-term memory database stored independently under ``data/memory``."""

    def __init__(self, db_path: Path, max_memories: int = 200):
        self.db_path = Path(db_path)
        self.max_memories = max(1, int(max_memories))
        self.db = DatabaseManager(f"sqlite+aiosqlite:///{self.db_path}")
        self.lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        await self.db.init()
        await self.db.create_all(MemoryBase.metadata)

    async def close(self) -> None:
        await self.db.dispose()

    @staticmethod
    def _as_dict(item: MemoryRecord, score: Optional[float] = None) -> dict:
        result = {
            "id": item.id,
            "text": item.text,
            "scope": item.scope,
            "owner_id": item.owner_id,
            "importance": item.importance,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
            "last_accessed_at": item.last_accessed_at,
            "access_count": item.access_count,
            "source": item.source,
        }
        if score is not None:
            result["score"] = score
        return result

    async def _insert(self, session: AsyncSession, text: str, scope: str,
                      owner_id: str, importance: float, source: str) -> dict:
        normalized = normalize_text(text)
        now = time.time()
        existing = await session.scalar(select(MemoryRecord).where(
            MemoryRecord.normalized_text == normalized,
            MemoryRecord.scope == scope,
            MemoryRecord.owner_id == owner_id,
            MemoryRecord.status == "active",
        ))
        if existing is not None:
            existing.importance = max(existing.importance, importance)
            existing.updated_at = now
            return self._as_dict(existing)

        item = MemoryRecord(
            id=f"mem_{uuid.uuid4().hex}", text=text.strip(),
            normalized_text=normalized, scope=scope, owner_id=owner_id,
            importance=max(0.0, min(1.0, float(importance))),
            created_at=now, updated_at=now, last_accessed_at=now,
            source=source, status="active",
        )
        session.add(item)
        await session.flush()
        session.add_all([
            MemoryTerm(memory_id=item.id, term=term, weight=weight)
            for term, weight in tokenize(text).items()
        ])
        return self._as_dict(item)

    async def add(self, text: str, scope: str = "global", owner_id: str = "",
                  importance: float = 0.5, source: str = "manual") -> dict:
        if not normalize_text(text):
            raise ValueError("Memory text must not be empty")
        async with self.lock:
            async with self.db.transaction() as session:
                result = await self._insert(session, text, scope, owner_id, importance, source)
                await self._prune(session)
                return result

    async def _prune(self, session: AsyncSession) -> None:
        count = await session.scalar(select(func.count()).select_from(MemoryRecord).where(
            MemoryRecord.status == "active"
        ))
        overflow = max(0, int(count or 0) - self.max_memories)
        if not overflow:
            return
        victims = (await session.scalars(
            select(MemoryRecord)
            .where(MemoryRecord.status == "active")
            .order_by(MemoryRecord.importance.asc(), MemoryRecord.last_accessed_at.asc())
            .limit(overflow)
        )).all()
        for item in victims:
            await session.execute(delete(MemoryTerm).where(MemoryTerm.memory_id == item.id))
            await session.delete(item)

    async def update(self, memory_id: str, text: str,
                     importance: Optional[float] = None) -> Optional[dict]:
        if not normalize_text(text):
            raise ValueError("Memory text must not be empty")
        async with self.lock:
            async with self.db.transaction() as session:
                item = await session.get(MemoryRecord, memory_id)
                if item is None or item.status != "active":
                    return None
                item.text = text.strip()
                item.normalized_text = normalize_text(text)
                item.updated_at = time.time()
                if importance is not None:
                    item.importance = max(0.0, min(1.0, float(importance)))
                await session.execute(delete(MemoryTerm).where(MemoryTerm.memory_id == memory_id))
                session.add_all([
                    MemoryTerm(memory_id=memory_id, term=term, weight=weight)
                    for term, weight in tokenize(text).items()
                ])
                return self._as_dict(item)

    async def remove(self, memory_id: str) -> bool:
        async with self.lock:
            async with self.db.transaction() as session:
                item = await session.get(MemoryRecord, memory_id)
                if item is None:
                    return False
                await session.execute(delete(MemoryTerm).where(MemoryTerm.memory_id == memory_id))
                await session.delete(item)
                return True

    async def list(self, scopes: Optional[list[tuple[str, str]]] = None) -> list[dict]:
        async with self.db.get_session() as session:
            stmt = select(MemoryRecord).where(MemoryRecord.status == "active")
            if scopes is not None:
                stmt = stmt.where(_scope_filter(scopes))
            items = (await session.scalars(
                stmt.order_by(MemoryRecord.importance.desc(), MemoryRecord.updated_at.desc())
            )).all()
            return [self._as_dict(item) for item in items]

    async def search(self, query: str, scopes: list[tuple[str, str]], limit: int = 8) -> list[dict]:
        query_terms = tokenize(query)
        if not query_terms or not scopes:
            return []
        async with self.lock:
            async with self.db.transaction() as session:
                stmt = (
                    select(MemoryRecord, MemoryTerm.term, MemoryTerm.weight)
                    .join(MemoryTerm, MemoryTerm.memory_id == MemoryRecord.id)
                    .where(
                        MemoryRecord.status == "active",
                        _scope_filter(scopes),
                        MemoryTerm.term.in_(list(query_terms)),
                    )
                )
                rows = (await session.execute(stmt)).all()
                if not rows:
                    return []

                total_docs = int(await session.scalar(select(func.count()).select_from(MemoryRecord).where(
                    MemoryRecord.status == "active", _scope_filter(scopes)
                )) or 1)
                doc_terms: dict[str, set[str]] = {}
                items: dict[str, MemoryRecord] = {}
                term_scores: dict[str, float] = {}
                for item, term, weight in rows:
                    items[item.id] = item
                    doc_terms.setdefault(term, set()).add(item.id)
                    term_scores[item.id] = term_scores.get(item.id, 0.0) + (
                        weight * query_terms[term]
                    )

                now = time.time()
                scored = []
                for memory_id, base_score in term_scores.items():
                    item = items[memory_id]
                    idf_score = 0.0
                    for term in query_terms:
                        if memory_id in doc_terms.get(term, set()):
                            df = len(doc_terms[term])
                            idf_score += math.log(1 + (total_docs + 1) / (df + 1))
                    age_days = max(0.0, (now - item.last_accessed_at) / 86400)
                    recency = math.exp(-age_days / 180.0)
                    score = (
                        base_score * 0.55
                        + idf_score * 0.25
                        + item.importance * 0.15
                        + recency * 0.05
                    )
                    item.access_count += 1
                    item.last_accessed_at = now
                    scored.append((score, item))

                scored.sort(key=lambda value: value[0], reverse=True)
                results = []
                seen_texts = set()
                for score, item in scored:
                    normalized = normalize_text(item.text)
                    if normalized in seen_texts:
                        continue
                    seen_texts.add(normalized)
                    results.append(self._as_dict(item, score))
                    if len(results) >= max(1, limit):
                        break
                return results

    async def migrate_legacy(self, legacy_path: Path) -> int:
        """Import non-empty lines from the old core.txt exactly once."""
        async with self.lock:
            async with self.db.transaction() as session:
                state = await session.get(MemoryMigration, "simple_memory_core_txt_v1")
                if state is not None:
                    return 0

                try:
                    content = await asyncio.to_thread(legacy_path.read_text, encoding="utf-8")
                except FileNotFoundError:
                    content = ""

                count = 0
                for line in content.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    await self._insert(
                        session, line, "global", "", 0.5, "simple_memory_core_txt"
                    )
                    count += 1
                session.add(MemoryMigration(
                    name="simple_memory_core_txt_v1",
                    migrated_at=time.time(), imported_count=count,
                ))
                return count
