"""Transactional SQLite storage, scoped retrieval, and legacy text migration."""

import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
import math
from pathlib import Path
import time
import uuid

import aiosqlite

from .scope import MemoryInputError, MemoryScope
from .search import normalize, terms

KINDS = {"semantic", "episodic", "procedural"}
STATUSES = {"active", "completed", "cancelled", "superseded"}
MAX_TEXT = 4000


def validate(text, kind, importance, core, expires_at=None, status="active"):
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or "\x00" in text:
        raise MemoryInputError("invalid_text")
    if kind not in KINDS or status not in STATUSES:
        raise MemoryInputError("invalid_category")
    if type(importance) is not int or not 1 <= importance <= 5 or type(core) is not bool:
        raise MemoryInputError("invalid_priority")
    if expires_at is not None and (
        type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= 0
    ):
        raise MemoryInputError("invalid_expiry")


def _legacy_snapshot(path: Path):
    if not path.exists():
        return None
    raw = path.read_bytes()
    content = raw.decode("utf-8-sig")
    digest = hashlib.sha256(raw).hexdigest()
    backup = path.with_name(f"{path.name}.{digest[:16]}.bak")
    try:
        with backup.open("xb") as output:
            output.write(raw)
    except FileExistsError:
        if backup.read_bytes() != raw:
            raise OSError("Legacy backup does not match")
    return content, digest


class MemoryStore:
    def __init__(self, path: Path):
        self.path = Path(path)

    @asynccontextmanager
    async def connection(self, *, write=False):
        async with aiosqlite.connect(self.path, timeout=10) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("PRAGMA foreign_keys = ON")
            if write:
                await db.execute("BEGIN IMMEDIATE")
            try:
                yield db
                if write:
                    await db.commit()
            except BaseException:
                if write:
                    await db.rollback()
                raise

    async def initialize(self, legacy_path: Path) -> int:
        await asyncio.to_thread(self.path.parent.mkdir, parents=True, exist_ok=True)
        async with self.connection() as db:
            async with db.execute("PRAGMA user_version") as cursor:
                version = (await cursor.fetchone())[0]
            if version not in (0, 1):
                raise RuntimeError("Unsupported memory database version")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, normalized TEXT NOT NULL,
                    kind TEXT NOT NULL, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
                    persona_id TEXT NOT NULL, namespace TEXT NOT NULL, session_id TEXT NOT NULL,
                    source_message_id TEXT, importance INTEGER NOT NULL DEFAULT 3,
                    core INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
                    expires_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, origin TEXT NOT NULL DEFAULT 'conversation',
                    term_count INTEGER NOT NULL DEFAULT 1, legacy_line INTEGER
                );
                CREATE INDEX IF NOT EXISTS memory_scope ON memories(persona_id, namespace, session_id);
                CREATE INDEX IF NOT EXISTS memory_origin ON memories(origin);
                CREATE TABLE IF NOT EXISTS memory_terms (
                    memory_id TEXT NOT NULL REFERENCES memories(id) ON DELETE CASCADE,
                    term TEXT NOT NULL, PRIMARY KEY(memory_id, term)
                );
                CREATE INDEX IF NOT EXISTS memory_term_lookup ON memory_terms(term, memory_id);
                CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 1;
            """)
            async with db.execute("SELECT 1 FROM memory_meta WHERE key = 'core_txt_migration'") as cursor:
                if await cursor.fetchone():
                    return 0
        snapshot = await asyncio.to_thread(_legacy_snapshot, Path(legacy_path))
        if snapshot is None:
            return 0
        content, digest = snapshot
        count = 0
        async with self.connection(write=True) as db:
            async with db.execute("SELECT 1 FROM memory_meta WHERE key = 'core_txt_migration'") as cursor:
                if await cursor.fetchone():
                    return 0
            for index, line in enumerate(content.splitlines()):
                if not line.strip():
                    continue
                now = time.time()
                memory_id = uuid.uuid4().hex
                await db.execute(
                    "INSERT INTO memories (id,text,normalized,kind,owner_type,owner_id,persona_id,"
                    "namespace,session_id,core,created_at,updated_at,origin,legacy_line) "
                    "VALUES (?,?,?,'semantic','legacy','shared','','','',1,?,?,'legacy',?)",
                    (memory_id, line, normalize(line), now, now, index),
                )
                await self._index(db, memory_id, line)
                count += 1
            await db.execute("INSERT INTO memory_meta VALUES ('core_txt_migration', ?)", (digest,))
        return count

    @staticmethod
    async def _index(db, memory_id, text):
        # Legacy lines may exceed the new write limit; index their complete content off-loop.
        indexed = await asyncio.to_thread(terms, text)
        await db.execute("DELETE FROM memory_terms WHERE memory_id = ?", (memory_id,))
        await db.executemany(
            "INSERT INTO memory_terms VALUES (?, ?)", ((memory_id, term) for term in indexed),
        )
        await db.execute("UPDATE memories SET term_count = ? WHERE id = ?", (max(1, len(indexed)), memory_id))

    @staticmethod
    def _visible(scope):
        predicate, params = scope.predicate()
        return f"(({predicate}) OR m.origin = 'legacy')", params

    async def add(self, scope: MemoryScope, *, text: str, owner_type="user", user_id=None,
                  source_message_id=None, kind="semantic", importance=3, core=False, expires_at=None):
        validate(text, kind, importance, core, expires_at)
        owner_id = scope.owner(owner_type, user_id)
        source_id = scope.source(owner_type, user_id, source_message_id)
        text = text.strip()
        now = time.time()
        async with self.connection(write=True) as db:
            async with db.execute(
                "SELECT * FROM memories WHERE persona_id=? AND namespace=? AND session_id=? "
                "AND owner_type=? AND owner_id=? AND normalized=? AND kind=? AND status='active' "
                "AND (expires_at IS NULL OR expires_at>?) AND origin='conversation'",
                (scope.persona_id, scope.namespace, scope.session_id, owner_type, owner_id,
                 normalize(text), kind, now),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing:
                return dict(existing), False
            memory_id = uuid.uuid4().hex
            await db.execute(
                "INSERT INTO memories (id,text,normalized,kind,owner_type,owner_id,persona_id,"
                "namespace,session_id,source_message_id,importance,core,expires_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (memory_id, text, normalize(text), kind, owner_type, owner_id, scope.persona_id,
                 scope.namespace, scope.session_id, source_id, importance, int(core), expires_at, now, now),
            )
            await self._index(db, memory_id, text)
            async with db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)) as cursor:
                return dict(await cursor.fetchone()), True

    async def get(self, scope, memory_id):
        predicate, params = self._visible(scope)
        async with self.connection() as db:
            async with db.execute(f"SELECT m.* FROM memories m WHERE m.id=? AND {predicate}",
                                  [memory_id, *params]) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update(self, scope, memory_id, revision, *, text, kind=None, importance=None,
                     core=None, status=None, expires_at=None, clear_expiry=False, source_message_id=None):
        if type(revision) is not int or revision < 1:
            raise MemoryInputError("invalid_revision")
        predicate, params = self._visible(scope)
        async with self.connection(write=True) as db:
            async with db.execute(f"SELECT m.* FROM memories m WHERE m.id=? AND {predicate}",
                                  [memory_id, *params]) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise MemoryInputError("not_found")
            row = dict(row)
            if row["revision"] != revision:
                raise MemoryInputError("conflict")
            # Modifications must be tied to a real incoming message.
            source_owner = row["owner_type"] if row["owner_type"] == "user" else "self"
            source_user = json.loads(row["owner_id"])[-1] if source_owner == "user" else None
            source_id = scope.source(source_owner, source_user, source_message_id)
            kind = row["kind"] if kind is None else kind
            importance = row["importance"] if importance is None else importance
            core = bool(row["core"]) if core is None else core
            status = row["status"] if status is None else status
            expiry = None if clear_expiry else (row["expires_at"] if expires_at is None else expires_at)
            validate(text, kind, importance, core, expiry, status)
            await db.execute(
                "UPDATE memories SET text=?,normalized=?,kind=?,importance=?,core=?,status=?,expires_at=?,"
                "source_message_id=?,updated_at=?,revision=revision+1 WHERE id=?",
                (text.strip(), normalize(text), kind, importance, int(core), status, expiry,
                 source_id, time.time(), memory_id),
            )
            await self._index(db, memory_id, text)
        return revision + 1

    async def remove(self, scope, memory_id, revision, source_message_id=None):
        if type(revision) is not int or revision < 1:
            raise MemoryInputError("invalid_revision")
        predicate, params = self._visible(scope)
        async with self.connection(write=True) as db:
            async with db.execute(
                f"SELECT m.* FROM memories m WHERE m.id=? AND {predicate}", [memory_id, *params],
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                raise MemoryInputError("not_found")
            if row["revision"] != revision:
                raise MemoryInputError("conflict")
            source_owner = row["owner_type"] if row["owner_type"] == "user" else "self"
            source_user = json.loads(row["owner_id"])[-1] if source_owner == "user" else None
            scope.source(source_owner, source_user, source_message_id)
            await db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

    async def search(self, scope, query="", *, limit=8, kind=None, owner_type=None, core_only=False,
                     include_inactive=False, offset=0):
        if not isinstance(query, str) or len(query) > 512:
            raise MemoryInputError("invalid_query")
        if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 10000:
            raise MemoryInputError("invalid_limit")
        if kind is not None and kind not in KINDS:
            raise MemoryInputError("invalid_category")
        if owner_type is not None and owner_type not in {"user", "group", "self", "legacy"}:
            raise MemoryInputError("invalid_owner")
        predicate, params = self._visible(scope)
        if not include_inactive:
            predicate += " AND m.status='active' AND (m.expires_at IS NULL OR m.expires_at>?)"
            params.append(time.time())
        for column, value in (("kind", kind), ("owner_type", owner_type)):
            if value is not None:
                predicate += f" AND m.{column}=?"
                params.append(value)
        if core_only:
            predicate += " AND m.core=1"
        query_terms = list(terms(query, query=True).items())[:256]
        if query.strip() and not query_terms:
            return []
        if query_terms:
            values = ",".join("(?,?)" for _ in query_terms)
            sql = (
                f"WITH q(term,weight) AS (VALUES {values}) "
                f"SELECT m.*, SUM(q.weight) / (1.0 + 0.02*m.term_count) AS score "
                f"FROM q JOIN memory_terms t ON t.term=q.term JOIN memories m ON m.id=t.memory_id "
                f"WHERE {predicate} GROUP BY m.id "
                "ORDER BY score DESC,m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?"
            )
            params = [value for pair in query_terms for value in pair] + params
        else:
            sql = f"SELECT m.* FROM memories m WHERE {predicate} ORDER BY m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?"
        async with self.connection() as db:
            async with db.execute(sql, [*params, limit, offset]) as cursor:
                return [dict(row) for row in await cursor.fetchall()]
