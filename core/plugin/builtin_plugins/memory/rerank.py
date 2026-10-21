"""Optional bounded reranking through the host's model interface."""

import asyncio
import math
import time

from core.plugin import logger
from core.provider import ModelType, RerankModelClient


class MemoryReranker:
    def __init__(self, ctx, config):
        self.ctx = ctx
        self.config = config
        self._slots = asyncio.Semaphore(2)
        self._retry_at = 0.0

    @property
    def enabled(self):
        return self.config.get("rerank_enabled") is True

    def setting(self, key, default, minimum, maximum):
        value = self.config.get(key, default)
        return max(minimum, min(maximum, value)) if type(value) is int else default

    @property
    def candidate_limit(self):
        return self.setting("rerank_candidates", 30, 2, 100)

    def report(self, phase, reason=None, started=None, candidates=0):
        return {"phase": phase, "reason": reason, "candidates": candidates,
                "elapsed_ms": round((time.monotonic() - started) * 1000) if started is not None else 0}

    def client(self):
        selected = self.config.get("rerank_model")
        manager = self.ctx.provider_mgr
        if selected:
            provider_id, model_id = selected.split(":", 1)
            client = manager.get_model_client(provider_id, model_id, ModelType.RERANK)
        else:
            client = manager.get_default_rerank()
        if not isinstance(client, RerankModelClient):
            raise ValueError("Rerank model unavailable")
        return client

    async def rank(self, query, rows):
        if not self.enabled:
            return rows, self.report("disabled")
        candidates = rows[:self.candidate_limit]
        if not query.strip() or len(candidates) < 2:
            return rows, self.report("skipped", "insufficient_candidates")
        if time.monotonic() < self._retry_at:
            return rows, self.report("fallback", "cooldown")
        started = time.monotonic()
        reason = "model_missing"
        try:
            client = self.client()
            # Bound the total document payload to 60,000 characters, independent of the database size.
            per_document = min(4000, 60000 // len(candidates))
            documents = [row["text"][:per_document] for row in candidates]

            cooldown = object()

            async def call():
                async with self._slots:
                    # A queued request must observe failures from an earlier request too.
                    if time.monotonic() < self._retry_at:
                        return cooldown
                    return await client.rerank(query=query, documents=documents, top_n=len(documents))

            reason = "request_failed"
            results = await asyncio.wait_for(
                call(), timeout=self.setting("rerank_timeout", 10, 1, 30),
            )
            if results is cooldown:
                return rows, self.report("fallback", "cooldown", started)
            reason = "invalid_response"
            if not isinstance(results, list) or len(results) != len(candidates):
                raise ValueError("Incomplete rerank response")
            scores = {}
            for result in results:
                index, score = result.index, result.score
                if (type(index) is not int or not 0 <= index < len(candidates) or index in scores
                        or type(score) not in (float, int) or not math.isfinite(score)):
                    raise ValueError("Invalid rerank response")
                scores[index] = score
            order = sorted(range(len(candidates)), key=lambda index: -scores[index])
            # Map only validated indices to original records; provider text is never trusted.
            ranked = [candidates[index] for index in order] + rows[len(candidates):]
            return ranked, self.report("applied", started=started, candidates=len(candidates))
        except asyncio.TimeoutError:
            reason = "timeout"
        except Exception:
            pass
        self._retry_at = time.monotonic() + 30
        logger.warning("Memory rerank unavailable (%s); retaining original order", reason)
        return rows, self.report("fallback", reason, started, len(candidates))
