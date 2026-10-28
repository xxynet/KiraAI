"""Optional remote embeddings; no numeric dependency is imported while disabled."""

import asyncio
import importlib
import importlib.metadata
import importlib.util
import time
from pathlib import Path

from packaging.version import Version

from .search import MAX_CANDIDATES
from .vector_store import VectorStore


def dependency_available():
    try:
        return (importlib.util.find_spec("numpy") is not None
                and Version("1.24") <= Version(importlib.metadata.version("numpy")) < Version("3"))
    except (ImportError, ValueError):
        return False


def load_numpy():
    if not dependency_available():
        raise ImportError("Optional vector dependency unavailable")
    return importlib.import_module("numpy")


def normalize_vectors(np, values, count, dimensions=None):
    matrix = np.asarray(values, dtype="float64")
    if (matrix.ndim != 2 or matrix.shape[0] != count or not 1 <= matrix.shape[1] <= 65536
            or not np.isfinite(matrix).all()):
        raise ValueError("Invalid embedding response")
    if dimensions is not None and matrix.shape[1] != dimensions:
        raise ValueError("Embedding dimensions changed")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or (norms <= 0).any():
        raise ValueError("Invalid embedding norm")
    return (matrix / norms).astype("<f4")


class VectorMemory:
    def __init__(self, store, ctx, config):
        self.store = VectorStore(store)
        self.ctx = ctx
        self.config = config
        self.enabled = config.get("enabled") is True
        self.np = None
        self.index_id = None
        self.dimension = None
        self.received_dimension = None
        self.phase = "disabled" if not self.enabled else "starting"
        self.reason = None
        self.indexed = 0
        self.total = 0
        self.ready = False
        self._wake = asyncio.Event()
        self._task = None
        self._install_task = None
        self._rebuild = False
        self._slots = asyncio.Semaphore(2)
        self._retry_at = 0.0

    def number(self, key, default, minimum, maximum):
        value = self.config.get(key, default)
        return max(minimum, min(maximum, value)) if type(value) in (float, int) else default

    @property
    def candidate_limit(self):
        value = self.config.get("candidates", 50)
        return max(1, min(1000, value)) if type(value) is int else 50

    def start(self):
        if self.enabled and (self._task is None or self._task.done()):
            self._task = asyncio.create_task(self._run())

    def changed(self):
        if self.enabled:
            if (self.np is not None and self.index_id is not None
                    and self.phase != "rebuild_required" and time.monotonic() >= self._retry_at):
                self.phase = "building"
            self._wake.set()

    async def updated(self, memory_id):
        """Keep retrieval ready when an edit has preserved the record's current vector."""
        if not self.enabled:
            return
        try:
            current = self.index_id is not None and await self.store.is_current(memory_id)
        except Exception:
            # An optional index check must not fail an already committed memory edit.
            current = False
        if not current:
            self.changed()

    async def close(self):
        tasks = [task for task in (self._task, self._install_task) if task is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.ready = False

    def client(self):
        selected = self.config.get("model")
        client = self.ctx.get_embedding_client(selected or "", default=not selected)
        if client is None:
            raise ValueError("Embedding model unavailable")
        return client

    async def _embed(self, client, texts):
        async def call():
            async with self._slots:
                return await client.embed(texts)
        return await asyncio.wait_for(
            call(), timeout=self.number("timeout", 10, 1, 30),
        )

    def _index_state(self, state):
        if self.index_id != state["id"]:
            self.ready = False
        self.index_id = state["id"]
        self.dimension = state["dimensions"]
        self.received_dimension = state["received_dimensions"]
        if state["rebuild_required"]:
            self.ready, self.phase, self.reason = False, "rebuild_required", "dimension_mismatch"

    async def _sync(self):
        if time.monotonic() < self._retry_at:
            return
        await self.store.initialize()
        state = await self.store.state()
        self._index_state(state)
        progress = await self.store.progress()
        self.indexed, self.total = progress["indexed"], progress["total"]
        if state["rebuild_required"] and not self._rebuild:
            return
        if self.np is None:
            try:
                self.np = await asyncio.to_thread(load_numpy)
            except ImportError:
                self.phase, self.ready = "dependency_missing", False
                if self.reason != "install_failed":
                    self.reason = None
                return
        try:
            self.client()
        except Exception:
            self.phase, self.reason, self.ready = "model_missing", None, False
            return
        if self._rebuild:
            self._rebuild = False
            self._index_state(await self.store.reset())
        index_id = self.index_id
        self.phase, self.reason = "building", None
        while True:
            state = await self.store.state()
            self._index_state(state)
            if state["rebuild_required"] or state["id"] != index_id:
                return
            progress = await self.store.progress()
            self.indexed, self.total = progress["indexed"], progress["total"]
            # Existing current vectors remain searchable while missing or stale rows are indexed.
            self.ready = self.indexed > 0 and self.dimension is not None and not self._rebuild
            rows = await self.store.pending()
            if not rows:
                self.ready, self.phase = True, "ready"
                return
            values = await self._embed(self.client(), [row["text"][:4000] for row in rows])
            matrix = await asyncio.to_thread(normalize_vectors, self.np, values, len(rows))
            if self.dimension is not None and self.dimension != matrix.shape[1]:
                self._index_state(await self.store.block_dimensions(index_id, matrix.shape[1]))
                return
            blobs = await asyncio.to_thread(lambda: [vector.tobytes() for vector in matrix])
            state = await self.store.put(index_id, rows, blobs, matrix.shape[1])
            self._index_state(state)
            if state["rebuild_required"] or state["id"] != index_id:
                return
            if self._rebuild:
                self.ready = False
                self._wake.set()
                return
            await asyncio.sleep(0)

    async def _run(self):
        # Check once per worker startup; failed installs can be retried from the dashboard.
        if self.np is None:
            await self.install()
            if self._install_task is not None:
                await self._install_task
        while True:
            self._wake.clear()
            try:
                await self._sync()
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.phase != "rebuild_required":
                    self.phase, self.reason = "degraded", "embedding_failed"
                    self._retry_at = time.monotonic() + 30
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=60 if self.phase == "degraded" else 30)
            except asyncio.TimeoutError:
                pass

    async def search(self, query, predicate, params, *, limit=MAX_CANDIDATES):
        if not self.enabled or not self.ready or not self.total:
            return None
        try:
            index_id = self.index_id
            values = await self._embed(self.client(), [query])
            matrix = await asyncio.to_thread(normalize_vectors, self.np, values, 1)
            if self.index_id != index_id or self._rebuild:
                return None
            if self.dimension is not None and len(matrix[0]) != self.dimension:
                self._index_state(await self.store.block_dimensions(index_id, len(matrix[0])))
                return None
            if not self.ready:
                return None
            results = await self.store.search(
                self.np, matrix[0], predicate, params,
                self.number("min_similarity", 0.35, 0, 1), limit=limit,
            )
            if not self.ready or self.index_id != index_id:
                return None
            return results
        except asyncio.CancelledError:
            raise
        except Exception:
            if self.index_id == index_id and self.phase != "rebuild_required":
                self.phase, self.reason, self.ready = "degraded", "embedding_failed", False
                self._retry_at = time.monotonic() + 30
            return None

    async def status(self):
        available = self.np is not None or await asyncio.to_thread(dependency_available)
        return {
            "enabled": self.enabled, "dependency_available": available,
            "phase": "installing" if self._install_task and not self._install_task.done() else self.phase,
            "reason": self.reason, "indexed": self.indexed, "total": self.total,
            "ready": self.ready, "index_dimensions": self.dimension,
            "received_dimensions": self.received_dimension,
        }

    async def _install(self):
        from core.plugin.plugin_installer import install_requirements
        try:
            config = getattr(self.ctx, "config", {})
            mirror = config.get("network", {}).get("pypi_mirror") if config else None
            warnings = await install_requirements(
                Path(__file__).parent / "vector_dependencies", pypi_mirror=mirror,
            )
            importlib.invalidate_caches()
            if warnings or not await asyncio.to_thread(dependency_available):
                self.reason = "install_failed"
                return
            self.phase, self.reason = "starting", None
            self._retry_at = 0
            self._wake.set()
            self.start()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.reason = "install_failed"

    async def install(self):
        if self.enabled and not await asyncio.to_thread(dependency_available):
            if self._install_task is None or self._install_task.done():
                self.reason = None
                self._install_task = asyncio.create_task(self._install())
        return await self.status()

    async def rebuild(self):
        if self.enabled:
            self.ready, self._rebuild = False, True
            self.phase, self.reason, self._retry_at = "starting", None, 0
            self._wake.set()
            self.start()
        return await self.status()
