"""Read-only cache hit aggregation for the WebUI overview chart.

Kept out of the telemetry mixin so telemetry collection/reporting stays
untouched.
"""

from sqlalchemy import Integer, and_, cast, func, select

from ..models import TelemetryLLMUsage


class OverviewCacheMixin:
    async def get_main_cache_hit_hourly(self, since_ts: int, until_ts: int) -> list[dict]:
        """Aggregate the main-model prompt cache hit rate per hour and model.

        Only rows in ``[since_ts, until_ts)`` are aggregated, so the average
        computed from these buckets covers exactly the charted window even if
        new telemetry lands between capturing the window and running the query.

        Only main-source calls that actually report ``cached_tokens`` (not NULL)
        and consumed input tokens are counted, since the hit rate is undefined
        otherwise. The per-bucket rate is token-weighted: ``sum(cached) / sum(input)``.

        Splitting by model keeps a per-session model override or a failover
        model from blending its rate with the default model's.

        Returns [{"hour_ts": int, "model": str, "hit_rate": float (0..100),
                  "cached_tokens": int, "input_tokens": int, "calls": int}, ...].
        """
        hour_bucket = cast(TelemetryLLMUsage.timestamp / 3600, Integer) * 3600
        stmt = (
            select(
                hour_bucket.label("hour_ts"),
                TelemetryLLMUsage.model.label("model"),
                func.coalesce(func.sum(TelemetryLLMUsage.cached_tokens), 0).label("cached_tokens"),
                func.coalesce(func.sum(TelemetryLLMUsage.input_tokens), 0).label("input_tokens"),
                func.count().label("calls"),
            )
            .where(
                and_(
                    TelemetryLLMUsage.timestamp >= since_ts,
                    TelemetryLLMUsage.timestamp < until_ts,
                    TelemetryLLMUsage.source == "main",
                    TelemetryLLMUsage.cached_tokens.is_not(None),
                    TelemetryLLMUsage.input_tokens > 0,
                )
            )
            .group_by(hour_bucket, TelemetryLLMUsage.model)
            .order_by(hour_bucket, TelemetryLLMUsage.model)
        )
        rows = await self.db.fetch_all(stmt)
        result: list[dict] = []
        for r in rows:
            input_tokens = int(r["input_tokens"] or 0)
            cached_tokens = int(r["cached_tokens"] or 0)
            result.append({
                "hour_ts": r["hour_ts"],
                "model": r["model"] or "",
                "hit_rate": round(cached_tokens / input_tokens * 100, 2) if input_tokens > 0 else 0.0,
                "cached_tokens": cached_tokens,
                "input_tokens": input_tokens,
                "calls": int(r["calls"] or 0),
            })
        return result