"""Transactional SQLite storage, scoped retrieval, and legacy text migration."""

import asyncio
import hashlib
import json
import math
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .scope import MemoryInputError, MemoryScope
from .search import (
    MAX_CANDIDATES,
    index_columns,
    indexed_term_count,
    match_query,
    normalize,
)
from .vector_store import VectorStore

KINDS = {"semantic", "episodic", "procedural"}
STATUSES = {"active", "completed", "cancelled", "superseded"}
MAX_TEXT = 4000
# Administrative listings address memories by stable ID, not by conversation
# scope: the WebUI is an operator view over the whole store.
MAX_PAGE_SIZE = 100

FTS_SCHEMA = """
    CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
        memory_id UNINDEXED, w, g1, g2, g3, tokenize='ascii'
    );
    INSERT INTO memory_fts(memory_fts, rank) VALUES('rank', 'bm25(0.0, 3.0, 0.25, 1.0, 1.5)');
    CREATE TRIGGER IF NOT EXISTS memory_fts_delete AFTER DELETE ON memories BEGIN
        DELETE FROM memory_fts WHERE memory_id=old.id;
    END;
"""


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
            if version not in (0, 2):
                raise RuntimeError("Unsupported memory database version")
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY, text TEXT NOT NULL, normalized TEXT NOT NULL,
                    kind TEXT NOT NULL, owner_type TEXT NOT NULL, owner_id TEXT NOT NULL,
                    persona_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    source_message_id TEXT, importance INTEGER NOT NULL DEFAULT 3,
                    core INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
                    expires_at REAL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1, origin TEXT NOT NULL DEFAULT 'conversation'
                );
                CREATE INDEX IF NOT EXISTS memory_scope ON memories(persona_id, session_id);
                CREATE INDEX IF NOT EXISTS memory_origin ON memories(origin);
                CREATE TABLE IF NOT EXISTS memory_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                PRAGMA user_version = 2;
            """)
            await db.executescript(FTS_SCHEMA)
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
            for line in content.splitlines():
                if not line.strip():
                    continue
                now = time.time()
                memory_id = uuid.uuid4().hex
                await db.execute(
                    "INSERT INTO memories (id,text,normalized,kind,owner_type,owner_id,persona_id,"
                    "session_id,core,created_at,updated_at,origin) "
                    "VALUES (?,?,?,'semantic','legacy','shared','','',1,?,?,'legacy')",
                    (memory_id, line, normalize(line), now, now),
                )
                await self._index(db, memory_id, line)
                count += 1
            await db.execute("INSERT INTO memory_meta VALUES ('core_txt_migration', ?)", (digest,))
        return count

    @staticmethod
    async def _index(db, memory_id, text):
        # Legacy lines may exceed the new write limit; index their complete content off-loop.
        columns = await asyncio.to_thread(index_columns, text)
        await db.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
        await db.execute(
            "INSERT INTO memory_fts(memory_id,w,g1,g2,g3) VALUES (?, ?, ?, ?, ?)",
            (memory_id, *columns),
        )

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
                "SELECT * FROM memories WHERE persona_id=? AND session_id=? "
                "AND owner_type=? AND owner_id=? AND normalized=? AND kind=? AND status='active' "
                "AND (expires_at IS NULL OR expires_at>?) AND origin='conversation'",
                (scope.persona_id, scope.session_id, owner_type, owner_id,
                 normalize(text), kind, now),
            ) as cursor:
                existing = await cursor.fetchone()
            if existing:
                return dict(existing), False
            memory_id = uuid.uuid4().hex
            await db.execute(
                "INSERT INTO memories (id,text,normalized,kind,owner_type,owner_id,persona_id,"
                "session_id,source_message_id,importance,core,expires_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (memory_id, text, normalize(text), kind, owner_type, owner_id, scope.persona_id,
                 scope.session_id, source_id, importance, int(core), expires_at, now, now),
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
            await self._write_update(
                db, row, text=text, kind=kind, importance=importance, core=core, status=status,
                expires_at=expires_at, clear_expiry=clear_expiry, source_message_id=source_id,
            )
        return revision + 1

    async def _write_update(self, db, row, *, text, kind=None, importance=None, core=None,
                            status=None, expires_at=None, clear_expiry=False, source_message_id=None):
        """Apply validated edits and reuse derived indexes while the stored text is unchanged."""
        kind = row["kind"] if kind is None else kind
        importance = row["importance"] if importance is None else importance
        core = bool(row["core"]) if core is None else core
        status = row["status"] if status is None else status
        expiry = None if clear_expiry else (row["expires_at"] if expires_at is None else expires_at)
        validate(text, kind, importance, core, expiry, status)
        text = text.strip()
        await db.execute(
            "UPDATE memories SET text=?,normalized=?,kind=?,importance=?,core=?,status=?,expires_at=?,"
            "source_message_id=?,updated_at=?,revision=revision+1 WHERE id=?",
            (text, normalize(text), kind, importance, int(core), status, expiry,
             source_message_id, time.time(), row["id"]),
        )
        if text != row["text"]:
            await self._index(db, row["id"], text)
        else:
            await VectorStore.advance_revision(db, row["id"], row["revision"])

    async def admin_update(self, memory_id, revision, *, text, kind=None, importance=None,
                           core=None, status=None, expires_at=None, clear_expiry=False):
        """Update an operator-selected record without changing its ownership or provenance."""
        if type(revision) is not int or revision < 1:
            raise MemoryInputError("invalid_revision")
        async with self.connection(write=True) as db:
            async with db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise MemoryInputError("not_found")
            if row["revision"] != revision:
                raise MemoryInputError("conflict")
            await self._write_update(
                db, row, text=text, kind=kind, importance=importance, core=core, status=status,
                expires_at=expires_at, clear_expiry=clear_expiry,
                source_message_id=row["source_message_id"],
            )
            async with db.execute(
                "SELECT * FROM memories WHERE id=?", (memory_id,),
            ) as cursor:
                record = dict(await cursor.fetchone())
        record["terms"] = await asyncio.to_thread(indexed_term_count, record["text"])
        return record

    async def admin_remove(self, memory_id, revision):
        """Delete the operator-confirmed revision and its derived indexes atomically."""
        if type(revision) is not int or revision < 1:
            raise MemoryInputError("invalid_revision")
        async with self.connection(write=True) as db:
            async with db.execute("SELECT revision FROM memories WHERE id=?", (memory_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise MemoryInputError("not_found")
            if row["revision"] != revision:
                raise MemoryInputError("conflict")
            await db.execute("DELETE FROM memories WHERE id=?", (memory_id,))

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
        return await self._search(
            *self._visible(scope), query=query, limit=limit, kind=kind, owner_type=owner_type,
            core_only=core_only, include_inactive=include_inactive, offset=offset,
        )

    async def search_preview(self, query="", *, persona_id=None, session_id=None, **options):
        return await self._search(
            *self.preview_predicate(persona_id, session_id), query=query, **options,
        )

    @staticmethod
    def preview_predicate(persona_id=None, session_id=None):
        """Search operator-selected scopes without widening conversation visibility."""
        clauses, params = [], []
        for column, value in (("persona_id", persona_id), ("session_id", session_id)):
            if value is not None:
                if not isinstance(value, str) or not value.strip() or len(value) > 512:
                    raise MemoryInputError("invalid_recall")
                clauses.append(f"m.{column}=?")
                params.append(value)
        predicate = " AND ".join(clauses) or "1=1"
        return f"(({predicate}) OR m.origin='legacy')", params

    @staticmethod
    def search_filter(predicate, params, *, kind=None, owner_type=None, core_only=False, include_inactive=False):
        params = list(params)
        if kind is not None and kind not in KINDS:
            raise MemoryInputError("invalid_category")
        if owner_type is not None and owner_type not in {"user", "group", "self", "legacy"}:
            raise MemoryInputError("invalid_owner")
        if not include_inactive:
            predicate += " AND m.status='active' AND (m.expires_at IS NULL OR m.expires_at>?)"
            params.append(time.time())
        for column, value in (("kind", kind), ("owner_type", owner_type)):
            if value is not None:
                predicate += f" AND m.{column}=?"
                params.append(value)
        if core_only:
            predicate += " AND m.core=1"
        return predicate, params

    @staticmethod
    def _matched_query(predicate, params, match):
        """Apply visibility and eligibility filters before ranking and pagination."""
        sql = (
            "FROM memory_fts JOIN memories m ON m.id=memory_fts.memory_id "
            f"WHERE memory_fts MATCH ? AND {predicate} "
        )
        return sql, [match, *params]

    async def _search(self, predicate, params, query="", *, limit=8, kind=None, owner_type=None,
                      core_only=False, include_inactive=False, offset=0, candidate_pool=False):
        if not isinstance(query, str):
            raise MemoryInputError("invalid_query")
        if type(limit) is not int or not 1 <= limit <= (MAX_CANDIDATES if candidate_pool else 50) or type(offset) is not int or not 0 <= offset <= 10000:
            raise MemoryInputError("invalid_limit")
        predicate, params = self.search_filter(
            predicate, params, kind=kind, owner_type=owner_type, core_only=core_only,
            include_inactive=include_inactive,
        )
        match = await asyncio.to_thread(match_query, query)
        if query.strip() and not match:
            return []
        if match:
            matched, params = self._matched_query(predicate, params, match)
            sql = (
                "SELECT m.*,memory_fts.rank AS score " + matched +
                "ORDER BY memory_fts.rank,m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?"
            )
        else:
            sql = f"SELECT m.* FROM memories m WHERE {predicate} ORDER BY m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?"
        async with self.connection() as db:
            async with db.execute(sql, [*params, limit, offset]) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    # ------------------------------------------------------------------
    # Administrative views backing the WebUI maintenance page.
    #
    # These read the store without a conversation scope because the page is an
    # operator surface over all personas and sessions. Callers must still go
    # through the authenticated plugin API; nothing here widens what the model
    # tools can see, which keeps using the scoped paths above.
    # ------------------------------------------------------------------

    async def overview(self) -> dict:
        """Aggregate counters plus per-bucket breakdowns for the dashboard."""
        now = time.time()
        async with self.connection() as db:
            async def count(where="", params=()):
                async with db.execute(f"SELECT COUNT(*) FROM memories WHERE 1=1 {where}", params) as cursor:
                    return (await cursor.fetchone())[0]

            def breakdown(column, where="", params=()):
                return db.execute(
                    f"SELECT {column} AS k, COUNT(*) AS n FROM memories WHERE 1=1 {where} "
                    f"GROUP BY {column} ORDER BY n DESC", params,
                )

            async def collect(column, where="", params=()):
                async with breakdown(column, where, params) as cursor:
                    return {row[0]: row[1] for row in await cursor.fetchall()}

            total = await count()
            active = await count(
                " AND status='active' AND (expires_at IS NULL OR expires_at>?)", (now,),
            )
            statuses = await collect("status")
            kinds = await collect("kind")
            owners = await collect("owner_type")
            origins = await collect("origin")
            async with db.execute(
                "SELECT COUNT(*) FROM memories WHERE status='active' "
                "AND (expires_at IS NULL OR expires_at>?) AND core=1", (now,),
            ) as cursor:
                core = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT COUNT(*) FROM memories WHERE status='active' AND expires_at>?", (now,),
            ) as cursor:
                expiring = (await cursor.fetchone())[0]
            async with db.execute(
                "SELECT MAX(updated_at), MAX(created_at) FROM memories") as cursor:
                last_updated, last_created = await cursor.fetchone()
        return {
            "total": total,
            "active": active,
            "inactive": total - active,
            "core": core,
            "expiring": expiring,
            "statuses": statuses,
            "kinds": kinds,
            "owners": owners,
            "origins": origins,
            "last_updated": last_updated,
            "last_created": last_created,
        }

    async def admin_list(self, *, query="", owner_type=None, kind=None, status=None, origin=None,
                         core=None, page=1, size=20) -> dict:
        """Filtered, paginated listing ordered like the search results."""
        if not isinstance(query, str):
            raise MemoryInputError("invalid_query")
        if type(page) is not int or page < 1 or page > 100000:
            raise MemoryInputError("invalid_limit")
        if type(size) is not int or not 1 <= size <= MAX_PAGE_SIZE:
            raise MemoryInputError("invalid_limit")
        for name, value, allowed in (
            ("kind", kind, KINDS),
            ("status", status, STATUSES),
            ("owner_type", owner_type, {"user", "group", "self", "legacy"}),
            ("origin", origin, {"conversation", "legacy"}),
        ):
            if value is not None and value not in allowed:
                raise MemoryInputError("invalid_category")
        if core is not None and type(core) is not bool:
            raise MemoryInputError("invalid_priority")

        where, params = "1=1", []
        for column, value in (("kind", kind), ("status", status), ("owner_type", owner_type),
                              ("origin", origin)):
            if value is not None:
                where += f" AND m.{column}=?"
                params.append(value)
        if core is not None:
            where += " AND m.core=?"
            params.append(int(core))
        match = await asyncio.to_thread(match_query, query)
        if query.strip() and not match:
            return {"items": [], "total": 0, "page": page, "size": size}

        async with self.connection() as db:
            if match:
                matched, query_params = self._matched_query(where, params, match)
                async with db.execute("SELECT COUNT(*) " + matched, query_params) as cursor:
                    total = (await cursor.fetchone())[0]
                # Rank and paginate in SQLite's worker thread; only load the requested page.
                async with db.execute(
                    "SELECT m.*,memory_fts.rank AS score " + matched +
                    "ORDER BY memory_fts.rank,m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?",
                    [*query_params, size, (page - 1) * size],
                ) as cursor:
                    rows = [dict(row) for row in await cursor.fetchall()]
            else:
                async with db.execute(f"SELECT COUNT(*) FROM memories m WHERE {where}", params) as cursor:
                    total = (await cursor.fetchone())[0]
                async with db.execute(
                    f"SELECT m.* FROM memories m WHERE {where} "
                    "ORDER BY m.importance DESC,m.updated_at DESC,m.id LIMIT ? OFFSET ?",
                    [*params, size, (page - 1) * size],
                ) as cursor:
                    rows = [dict(row) for row in await cursor.fetchall()]
        return {"items": rows, "total": total, "page": page, "size": size}

    async def admin_get(self, memory_id: str):
        """Single record by stable ID, including its distinct indexed term count."""
        if not isinstance(memory_id, str) or not memory_id:
            raise MemoryInputError("not_found")
        async with self.connection() as db:
            async with db.execute("SELECT * FROM memories WHERE id=?", (memory_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return None
        record = dict(row)
        record["terms"] = await asyncio.to_thread(indexed_term_count, record["text"])
        return record

    async def recall_users(self, session_id):
        """List known user owners without loading memory text."""
        async with self.connection() as db, db.execute(
            "SELECT owner_id FROM memories WHERE session_id=? "
            "AND owner_type='user' AND origin='conversation' "
            "GROUP BY owner_id ORDER BY MAX(updated_at) DESC, owner_id LIMIT 200",
            (session_id,),
        ) as cursor:
            owners = [row[0] for row in await cursor.fetchall()]
        users = []
        for owner in owners:
            try:
                parts = json.loads(owner)
            except (TypeError, ValueError):
                continue
            if isinstance(parts, list) and len(parts) == 2 and isinstance(parts[1], str):
                users.append(parts[1])
        return users

    async def facets(self) -> dict:
        """Distinct personas/sessions for the filter selectors."""
        async with self.connection() as db:
            async def distinct(column):
                async with db.execute(
                    f"SELECT DISTINCT {column} FROM memories WHERE {column}!='' ORDER BY {column} LIMIT 200"
                ) as cursor:
                    return [row[0] for row in await cursor.fetchall()]
            async with db.execute(
                "SELECT DISTINCT persona_id, session_id FROM memories "
                "WHERE origin='conversation' ORDER BY persona_id, session_id LIMIT 200"
            ) as cursor:
                contexts = [dict(row) for row in await cursor.fetchall()]
            return {
                "contexts": contexts,
                "personas": await distinct("persona_id"),
                "sessions": await distinct("session_id"),
            }
