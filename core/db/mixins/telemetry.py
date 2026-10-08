"""Database operations for telemetry."""

import uuid
from typing import Optional

from sqlalchemy import Integer, and_, cast, delete, func, select

from ..db_mgr import DatabaseManager
from ..models import TelemetryMessage, TelemetryLLMUsage


class TelemetryMixin:
    db: DatabaseManager

    async def add_telemetry_message(self, timestamp: int, platform: str) -> None:
        async with self.db.transaction() as session:
            session.add(TelemetryMessage(id=str(uuid.uuid4()), timestamp=timestamp, platform=platform))

    async def add_telemetry_llm_usage(
        self, timestamp: int, model: str,
        input_tokens: int, output_tokens: int,
        cached_tokens: Optional[int], response_time_ms: int, success: bool
    ) -> None:
        async with self.db.transaction() as session:
            session.add(TelemetryLLMUsage(
                id=str(uuid.uuid4()), timestamp=timestamp, model=model,
                input_tokens=input_tokens, output_tokens=output_tokens,
                cached_tokens=cached_tokens, response_time_ms=response_time_ms, success=success,
            ))

    async def get_unreported_telemetry_messages_by_hour(self, since_ts: int) -> list[dict]:
        hour_bucket = cast(TelemetryMessage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(hour_bucket.label("hour_ts"), TelemetryMessage.platform, func.count().label("count"))
            .where(and_(TelemetryMessage.reported.is_(False), TelemetryMessage.timestamp >= since_ts))
            .group_by(hour_bucket, TelemetryMessage.platform)
        )
        rows = await self.db.fetch_all(stmt)
        return [{"hour_ts": r["hour_ts"], "platform": r["platform"], "count": r["count"]} for r in rows]

    async def get_unreported_telemetry_message_rows(self, since_ts: int) -> list[dict]:
        """Return every unreported message row (id + hour bucket + platform) in one query.

        Deriving BOTH the per-platform counts and the id set to mark from this single
        snapshot keeps them exactly consistent: no row can be counted without being
        marked reported, or marked without being counted (which the previous two-query
        approach allowed when a row was inserted between the two reads).
        """
        hour_bucket = cast(TelemetryMessage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(hour_bucket.label("hour_ts"), TelemetryMessage.platform, TelemetryMessage.id)
            .where(and_(TelemetryMessage.reported.is_(False), TelemetryMessage.timestamp >= since_ts))
        )
        rows = await self.db.fetch_all(stmt)
        return [{"hour_ts": r["hour_ts"], "platform": r["platform"], "id": r["id"]} for r in rows]

    async def get_unreported_telemetry_llm_usage_by_hour(self, since_ts: int) -> list[dict]:
        """Return per-(hour, model) rows for building aggregated hourly reports."""
        hour_bucket = cast(TelemetryLLMUsage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(
                hour_bucket.label("hour_ts"),
                TelemetryLLMUsage.model,
                func.count().label("call_count"),
                func.sum(func.cast(TelemetryLLMUsage.success, Integer)).label("success_count"),
                func.coalesce(func.sum(TelemetryLLMUsage.input_tokens), 0).label("total_input"),
                func.coalesce(func.sum(TelemetryLLMUsage.output_tokens), 0).label("total_output"),
                func.coalesce(func.sum(TelemetryLLMUsage.cached_tokens), 0).label("total_cached"),
                func.coalesce(func.sum(TelemetryLLMUsage.response_time_ms), 0).label("total_response_ms"),
            )
            .where(and_(TelemetryLLMUsage.reported.is_(False), TelemetryLLMUsage.timestamp >= since_ts))
            .group_by(hour_bucket, TelemetryLLMUsage.model)
        )
        rows = await self.db.fetch_all(stmt)
        return [
            {
                "hour_ts": r["hour_ts"], "model": r["model"],
                "call_count": r["call_count"], "success_count": r["success_count"] or 0,
                "total_input": r["total_input"], "total_output": r["total_output"],
                "total_cached": r["total_cached"], "total_response_ms": r["total_response_ms"],
            }
            for r in rows
        ]

    async def get_unreported_telemetry_llm_usage_rows(self, since_ts: int) -> list[dict]:
        """Return every unreported LLM-usage row (id + hour bucket + measures) in one query.

        Counts and the id set to mark are aggregated in Python from this single
        snapshot (see get_unreported_telemetry_message_rows for the consistency
        rationale).
        """
        hour_bucket = cast(TelemetryLLMUsage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(
                hour_bucket.label("hour_ts"),
                TelemetryLLMUsage.id,
                TelemetryLLMUsage.model,
                TelemetryLLMUsage.success,
                TelemetryLLMUsage.input_tokens,
                TelemetryLLMUsage.output_tokens,
                TelemetryLLMUsage.cached_tokens,
                TelemetryLLMUsage.response_time_ms,
            )
            .where(and_(TelemetryLLMUsage.reported.is_(False), TelemetryLLMUsage.timestamp >= since_ts))
        )
        rows = await self.db.fetch_all(stmt)
        return [
            {
                "hour_ts": r["hour_ts"], "id": r["id"], "model": r["model"],
                "success": r["success"],
                "input_tokens": r["input_tokens"] or 0,
                "output_tokens": r["output_tokens"] or 0,
                "cached_tokens": r["cached_tokens"] or 0,
                "response_time_ms": r["response_time_ms"] or 0,
            }
            for r in rows
        ]

    async def mark_telemetry_reported(self) -> None:
        async with self.db.transaction() as session:
            await session.execute(
                TelemetryMessage.__table__.update()
                .where(TelemetryMessage.reported.is_(False))
                .values(reported=True)
            )
            await session.execute(
                TelemetryLLMUsage.__table__.update()
                .where(TelemetryLLMUsage.reported.is_(False))
                .values(reported=True)
            )

    async def mark_telemetry_messages_by_ids(self, ids: list[str]) -> None:
        """Mark only the specific message rows (by primary key) as reported.

        Marking exact ids — instead of an hour window — guarantees rows inserted into the
        still-filling hour after aggregation are never marked reported without being sent.
        """
        if not ids:
            return
        async with self.db.transaction() as session:
            # Chunk so the bound-parameter count stays well under SQLite's
            # SQLITE_MAX_VARIABLE_NUMBER (999 on older builds) no matter how many
            # rows accumulated in an hour bucket.
            for i in range(0, len(ids), 500):
                await session.execute(
                    TelemetryMessage.__table__.update()
                    .where(TelemetryMessage.id.in_(ids[i:i + 500]))
                    .values(reported=True)
                )

    async def mark_telemetry_llm_by_ids(self, ids: list[str]) -> None:
        """Mark only the specific LLM-usage rows (by primary key) as reported.

        Marking exact ids — instead of an hour window — guarantees rows inserted into the
        still-filling hour after aggregation are never marked reported without being sent.
        """
        if not ids:
            return
        async with self.db.transaction() as session:
            # Chunk to stay under SQLite's bound-parameter limit (see
            # mark_telemetry_messages_by_ids).
            for i in range(0, len(ids), 500):
                await session.execute(
                    TelemetryLLMUsage.__table__.update()
                    .where(TelemetryLLMUsage.id.in_(ids[i:i + 500]))
                    .values(reported=True)
                )

    async def delete_telemetry_records_before(self, cutoff_ts: int) -> None:
        async with self.db.transaction() as session:
            await session.execute(delete(TelemetryMessage).where(TelemetryMessage.timestamp < cutoff_ts))
            await session.execute(delete(TelemetryLLMUsage).where(TelemetryLLMUsage.timestamp < cutoff_ts))

    # ------------------------------------------------------------------
    # Overview aggregation queries
    # ------------------------------------------------------------------

    async def get_message_hourly_counts(self, since_ts: int) -> list[dict]:
        """Aggregate total message count per hour since since_ts.

        Returns [{"hour_ts": int_unix, "count": int}, ...] ordered by hour.
        """
        hour_bucket = cast(TelemetryMessage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(hour_bucket.label("hour_ts"), func.count().label("count"))
            .where(TelemetryMessage.timestamp >= since_ts)
            .group_by(hour_bucket)
            .order_by(hour_bucket)
        )
        rows = await self.db.fetch_all(stmt)
        return [{"hour_ts": r["hour_ts"], "count": r["count"]} for r in rows]

    async def get_message_platform_counts(self, since_ts: int) -> list[dict]:
        """Aggregate message count per platform since since_ts.

        Returns [{"platform": str, "count": int}, ...] ordered by count desc.
        """
        stmt = (
            select(TelemetryMessage.platform, func.count().label("count"))
            .where(TelemetryMessage.timestamp >= since_ts)
            .group_by(TelemetryMessage.platform)
            .order_by(func.count().desc())
        )
        rows = await self.db.fetch_all(stmt)
        return [{"platform": r["platform"], "count": r["count"]} for r in rows]

    async def get_llm_summary(self, since_ts: int) -> dict:
        """Aggregate LLM usage stats since since_ts.

        Returns {
          "total_calls": int,
          "total_input_tokens": int,
          "total_output_tokens": int,
          "total_cached_tokens": int,
          "success_count": int,
          "total_response_ms": int,
          "by_model": [{"model": str, "calls": int, "success": int,
                        "input_tokens": int, "output_tokens": int,
                        "cached_tokens": int, "total_response_ms": int,
                        "avg_response_ms": float}, ...],
        }
        """
        by_model_stmt = (
            select(
                TelemetryLLMUsage.model,
                func.count().label("calls"),
                func.coalesce(func.sum(func.cast(TelemetryLLMUsage.success, Integer)), 0).label("success"),
                func.coalesce(func.sum(TelemetryLLMUsage.input_tokens), 0).label("input_tokens"),
                func.coalesce(func.sum(TelemetryLLMUsage.output_tokens), 0).label("output_tokens"),
                func.coalesce(func.sum(TelemetryLLMUsage.cached_tokens), 0).label("cached_tokens"),
                func.coalesce(func.sum(TelemetryLLMUsage.response_time_ms), 0).label("total_response_ms"),
            )
            .where(TelemetryLLMUsage.timestamp >= since_ts)
            .group_by(TelemetryLLMUsage.model)
            .order_by(func.count().desc())
        )
        by_model = await self.db.fetch_all(by_model_stmt)

        return {
            "total_calls": sum(r["calls"] for r in by_model),
            "total_input_tokens": sum(r["input_tokens"] for r in by_model),
            "total_output_tokens": sum(r["output_tokens"] for r in by_model),
            "total_cached_tokens": sum(r["cached_tokens"] for r in by_model),
            "success_count": sum(r["success"] for r in by_model),
            "total_response_ms": sum(r["total_response_ms"] for r in by_model),
            "by_model": [
                {
                    "model": r["model"],
                    "calls": r["calls"],
                    "success": r["success"],
                    "input_tokens": r["input_tokens"],
                    "output_tokens": r["output_tokens"],
                    "cached_tokens": r["cached_tokens"],
                    "total_response_ms": r["total_response_ms"],
                    "avg_response_ms": round(r["total_response_ms"] / r["calls"], 1) if r["calls"] > 0 else 0,
                }
                for r in by_model
            ],
        }
