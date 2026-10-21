"""Derived vector persistence and bounded, scoped cosine search."""

import asyncio
import heapq
import json
import uuid

from .search import MAX_CANDIDATES

INDEX_STATE_KEY = "memory_vector_index"


class VectorStore:
    def __init__(self, store):
        self.store = store

    async def initialize(self):
        async with self.store.connection(write=True) as db:
            # fingerprint is an opaque index generation, not a provider or model signature.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS memory_vectors (
                    memory_id TEXT PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
                    revision INTEGER NOT NULL, fingerprint TEXT NOT NULL,
                    dimensions INTEGER NOT NULL, vector BLOB NOT NULL
                )
            """)
            await self._state(db)

    @staticmethod
    async def _save_state(db, state):
        await db.execute(
            "INSERT INTO memory_meta(key,value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (INDEX_STATE_KEY, json.dumps(state)),
        )

    @classmethod
    async def _state(cls, db):
        async with db.execute("SELECT value FROM memory_meta WHERE key=?", (INDEX_STATE_KEY,)) as cursor:
            row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        async with db.execute("SELECT DISTINCT dimensions FROM memory_vectors ORDER BY dimensions LIMIT 2") as cursor:
            dimensions = [row[0] for row in await cursor.fetchall()]
        state = {
            "id": uuid.uuid4().hex, "dimensions": dimensions[0] if dimensions else None,
            "rebuild_required": len(dimensions) > 1,
            "received_dimensions": dimensions[1] if len(dimensions) > 1 else None,
        }
        await cls._save_state(db, state)
        return state

    async def state(self):
        async with self.store.connection(write=True) as db:
            return await self._state(db)

    async def reset(self):
        async with self.store.connection(write=True) as db:
            await db.execute("DELETE FROM memory_vectors")
            state = {"id": uuid.uuid4().hex, "dimensions": None,
                     "rebuild_required": False, "received_dimensions": None}
            await self._save_state(db, state)
            return state

    async def block_dimensions(self, index_id, received):
        async with self.store.connection(write=True) as db:
            state = await self._state(db)
            if state["id"] == index_id and state["dimensions"] != received:
                state["rebuild_required"] = True
                state["received_dimensions"] = received
                await self._save_state(db, state)
            return state

    @staticmethod
    async def advance_revision(db, memory_id, revision):
        """Reuse only a current vector when the same transaction leaves memory text unchanged."""
        # The optional vector table is absent until vector retrieval has been initialized.
        async with db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_vectors'") as cursor:
            if await cursor.fetchone() is None:
                return
        await db.execute(
            "UPDATE memory_vectors SET revision=? WHERE memory_id=? AND revision=?",
            (revision + 1, memory_id, revision),
        )

    async def is_current(self, memory_id):
        async with self.store.connection() as db:
            async with db.execute(
                "SELECT 1 FROM memory_vectors v JOIN memories m ON m.id=v.memory_id "
                "WHERE m.id=? AND v.revision=m.revision", (memory_id,),
            ) as cursor:
                return await cursor.fetchone() is not None

    async def progress(self):
        async with self.store.connection() as db:
            async with db.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(CASE WHEN v.revision=m.revision "
                "THEN 1 ELSE 0 END),0) AS indexed "
                "FROM memories m LEFT JOIN memory_vectors v ON v.memory_id=m.id",
            ) as cursor:
                return dict(await cursor.fetchone())

    async def pending(self, size=16):
        async with self.store.connection() as db:
            async with db.execute(
                "SELECT m.id,m.text,m.revision FROM memories m "
                "LEFT JOIN memory_vectors v ON v.memory_id=m.id "
                "WHERE v.memory_id IS NULL OR v.revision!=m.revision "
                "ORDER BY m.id LIMIT ?", (size,),
            ) as cursor:
                return [dict(row) for row in await cursor.fetchall()]

    async def put(self, index_id, rows, vectors, dimensions):
        async with self.store.connection(write=True) as db:
            state = await self._state(db)
            if state["id"] != index_id or state["rebuild_required"]:
                return state
            if state["dimensions"] is not None and state["dimensions"] != dimensions:
                state["rebuild_required"] = True
                state["received_dimensions"] = dimensions
                await self._save_state(db, state)
                return state
            state["dimensions"] = dimensions
            await self._save_state(db, state)
            for row, vector in zip(rows, vectors):
                # Accept metadata edits during embedding, but never changed text or deleted records.
                await db.execute(
                    "INSERT INTO memory_vectors(memory_id,revision,fingerprint,dimensions,vector) "
                    "SELECT id,revision,?,?,? FROM memories WHERE id=? AND text=? "
                    "ON CONFLICT(memory_id) DO UPDATE SET revision=excluded.revision,"
                    "fingerprint=excluded.fingerprint,dimensions=excluded.dimensions,vector=excluded.vector",
                    (index_id, dimensions, vector, row["id"], row["text"]),
                )
            return state

    @staticmethod
    def _rank_batch(np, batch, query, threshold, best, limit):
        matrix = np.stack([np.frombuffer(row["vector"], dtype="<f4") for row in batch])
        if matrix.shape[1] != len(query) or not np.isfinite(matrix).all():
            raise ValueError("Invalid vector index")
        scores = matrix @ query
        for row, score in zip(batch, scores):
            if float(score) >= threshold:
                record = dict(row)
                record.pop("vector")
                record["vector_score"] = float(score)
                best.append(record)
        return heapq.nlargest(limit, best, key=lambda row: (
            row["vector_score"], row["importance"], row["updated_at"], row["id"],
        ))

    async def search(self, np, query, predicate, params, threshold, limit=MAX_CANDIDATES):
        best = []
        async with self.store.connection() as db:
            async with db.execute(
                "SELECT m.*,v.vector FROM memories m JOIN memory_vectors v "
                "ON v.memory_id=m.id AND v.revision=m.revision "
                f"WHERE v.dimensions=? AND ({predicate})",
                [len(query), *params],
            ) as cursor:
                while batch := await cursor.fetchmany(256):
                    best = await asyncio.to_thread(
                        self._rank_batch, np, batch, query, threshold, best, limit,
                    )
        return best
