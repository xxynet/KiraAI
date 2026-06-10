import time
import uuid
from typing import Optional
from sqlalchemy import select, delete, or_, and_, func, cast, Integer

from .db_mgr import DatabaseManager
from .models import Sticker, ImageDescCache, Persona, PluginStoreSource, TelemetryMessage, TelemetryLLMUsage


class DatabaseService:
    """High-level database service for KiraAI business operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager

    async def init_tables(self) -> None:
        """Create all tables if they do not exist."""
        await self.db.create_all()

    # ------------------------------------------------------------------
    # Sticker operations
    # ------------------------------------------------------------------
    async def add_sticker(
        self,
        sticker_id: str,
        desc: str,
        path: str,
        extra: Optional[dict] = None,
    ) -> None:
        async with self.db.transaction() as session:
            session.add(Sticker(id=sticker_id, desc=desc, path=path, extra=extra))

    async def get_sticker(self, sticker_id: str) -> Optional[dict]:
        stmt = select(Sticker).where(Sticker.id == sticker_id)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["Sticker"]
        return {"id": item.id, "desc": item.desc, "path": item.path, "extra": item.extra}

    async def list_stickers(self) -> list[dict]:
        stmt = select(Sticker).order_by(Sticker.id)
        rows = await self.db.fetch_all(stmt)
        return [
            {"id": r["Sticker"].id, "desc": r["Sticker"].desc, "path": r["Sticker"].path, "extra": r["Sticker"].extra}
            for r in rows
        ]

    async def update_sticker(
        self,
        sticker_id: str,
        desc: Optional[str] = None,
        path: Optional[str] = None,
        extra: Optional[dict] = None,
    ) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(Sticker).where(Sticker.id == sticker_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            if desc is not None:
                item.desc = desc
            if path is not None:
                item.path = path
            if extra is not None:
                item.extra = extra
            return True

    async def delete_sticker(self, sticker_id: str) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(Sticker).where(Sticker.id == sticker_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            await session.delete(item)
            return True

    # ------------------------------------------------------------------
    # Image description cache operations
    # ------------------------------------------------------------------
    async def add_image_desc_cache(
        self,
        md5: str,
        description: str,
        count: int = 0,
        last_seen: int = 0,
    ) -> None:
        async with self.db.transaction() as session:
            session.add(
                ImageDescCache(
                    md5=md5,
                    description=description,
                    count=count,
                    last_seen=last_seen,
                )
            )

    async def get_image_desc_cache(self, md5: str) -> Optional[dict]:
        stmt = select(ImageDescCache).where(ImageDescCache.md5 == md5)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["ImageDescCache"]
        return {
            "md5": item.md5,
            "description": item.description,
            "count": item.count,
            "last_seen": item.last_seen,
        }

    async def update_image_desc_cache(
        self,
        md5: str,
        description: Optional[str] = None,
        count: Optional[int] = None,
        last_seen: Optional[int] = None,
    ) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(ImageDescCache).where(ImageDescCache.md5 == md5)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            if description is not None:
                item.description = description
            if count is not None:
                item.count = count
            if last_seen is not None:
                item.last_seen = last_seen
            return True

    async def delete_image_desc_cache(self, md5: str) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(ImageDescCache).where(ImageDescCache.md5 == md5)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            await session.delete(item)
            return True

    async def cleanup_expired_image_desc_cache(self) -> int:
        """Remove entries older than 15 days with count < 2 or older than 30 days with count < 3."""
        now = int(time.time())
        fifteen_days = 15 * 24 * 60 * 60
        thirty_days = 30 * 24 * 60 * 60

        async with self.db.get_session() as session:
            stmt = delete(ImageDescCache).where(
                or_(
                    and_(ImageDescCache.last_seen < now - fifteen_days, ImageDescCache.count < 2),
                    and_(ImageDescCache.last_seen < now - thirty_days, ImageDescCache.count < 3),
                )
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount

    # ------------------------------------------------------------------
    # Persona operations
    # ------------------------------------------------------------------
    async def add_persona(
        self,
        persona_id: str,
        name: str,
        content: str,
        format: str = "text",
        created_at: Optional[int] = None,
    ) -> None:
        if created_at is None:
            created_at = int(time.time())
        async with self.db.transaction() as session:
            session.add(Persona(id=persona_id, name=name, format=format, content=content, created_at=created_at))

    async def get_persona(self, persona_id: str) -> Optional[dict]:
        stmt = select(Persona).where(Persona.id == persona_id)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["Persona"]
        return {"id": item.id, "name": item.name, "format": item.format, "content": item.content, "created_at": item.created_at}

    async def update_persona(
        self,
        persona_id: str,
        name: Optional[str] = None,
        content: Optional[str] = None,
        format: Optional[str] = None,
    ) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(Persona).where(Persona.id == persona_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            if name is not None:
                item.name = name
            if content is not None:
                item.content = content
            if format is not None:
                item.format = format
            return True

    async def delete_persona(self, persona_id: str) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(Persona).where(Persona.id == persona_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            await session.delete(item)
            return True

    async def list_personas(self) -> list[dict]:
        stmt = select(Persona).order_by(Persona.id)
        rows = await self.db.fetch_all(stmt)
        return [
            {"id": r["Persona"].id, "name": r["Persona"].name, "format": r["Persona"].format, "content": r["Persona"].content, "created_at": r["Persona"].created_at}
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Plugin store source operations
    # ------------------------------------------------------------------
    async def add_plugin_store_source(
        self,
        source_id: str,
        name: str,
        url: str,
        cache_file: Optional[str] = None,
        updated_at: int = 0,
        is_current: bool = False,
        created_at: int = 0,
    ) -> None:
        async with self.db.transaction() as session:
            if is_current:
                # Unset all other current flags
                result = await session.execute(
                    select(PluginStoreSource).where(PluginStoreSource.is_current == True)
                )
                for row in result.scalars().all():
                    row.is_current = False
            session.add(
                PluginStoreSource(
                    id=source_id,
                    name=name,
                    url=url,
                    cache_file=cache_file,
                    updated_at=updated_at,
                    is_current=is_current,
                    created_at=created_at,
                )
            )

    async def get_plugin_store_source(self, source_id: str) -> Optional[dict]:
        stmt = select(PluginStoreSource).where(PluginStoreSource.id == source_id)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["PluginStoreSource"]
        return {
            "id": item.id,
            "name": item.name,
            "url": item.url,
            "cache_file": item.cache_file,
            "updated_at": item.updated_at,
            "is_current": item.is_current,
            "created_at": item.created_at,
        }

    async def get_plugin_store_source_by_url(self, url: str) -> Optional[dict]:
        stmt = select(PluginStoreSource).where(PluginStoreSource.url == url)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["PluginStoreSource"]
        return {
            "id": item.id,
            "name": item.name,
            "url": item.url,
            "cache_file": item.cache_file,
            "updated_at": item.updated_at,
            "is_current": item.is_current,
            "created_at": item.created_at,
        }

    async def list_plugin_store_sources(self) -> list[dict]:
        stmt = select(PluginStoreSource).order_by(PluginStoreSource.created_at)
        rows = await self.db.fetch_all(stmt)
        return [
            {
                "id": r["PluginStoreSource"].id,
                "name": r["PluginStoreSource"].name,
                "url": r["PluginStoreSource"].url,
                "cache_file": r["PluginStoreSource"].cache_file,
                "updated_at": r["PluginStoreSource"].updated_at,
                "is_current": r["PluginStoreSource"].is_current,
                "created_at": r["PluginStoreSource"].created_at,
            }
            for r in rows
        ]

    async def update_plugin_store_source(
        self,
        source_id: str,
        name: Optional[str] = None,
        url: Optional[str] = None,
        cache_file: Optional[str] = None,
        updated_at: Optional[int] = None,
        is_current: Optional[bool] = None,
    ) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(PluginStoreSource).where(PluginStoreSource.id == source_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            if name is not None:
                item.name = name
            if url is not None:
                item.url = url
            if cache_file is not None:
                item.cache_file = cache_file
            if updated_at is not None:
                item.updated_at = updated_at
            if is_current is not None:
                if is_current:
                    # Unset all other current flags
                    others = await session.execute(
                        select(PluginStoreSource).where(
                            PluginStoreSource.is_current == True,
                            PluginStoreSource.id != source_id,
                        )
                    )
                    for row in others.scalars().all():
                        row.is_current = False
                item.is_current = is_current
            return True

    async def delete_plugin_store_source(self, source_id: str) -> bool:
        async with self.db.transaction() as session:
            result = await session.execute(
                select(PluginStoreSource).where(PluginStoreSource.id == source_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False
            await session.delete(item)
            return True

    # ------------------------------------------------------------------
    # Telemetry raw records
    # ------------------------------------------------------------------

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

    async def mark_telemetry_messages_by_hours(self, hour_ts_list: list[int]) -> None:
        if not hour_ts_list:
            return
        async with self.db.transaction() as session:
            conditions = [
                and_(TelemetryMessage.timestamp >= h, TelemetryMessage.timestamp < h + 3600)
                for h in hour_ts_list
            ]
            await session.execute(
                TelemetryMessage.__table__.update()
                .where(and_(TelemetryMessage.reported.is_(False), or_(*conditions)))
                .values(reported=True)
            )

    async def mark_telemetry_llm_by_hours(self, hour_ts_list: list[int]) -> None:
        if not hour_ts_list:
            return
        async with self.db.transaction() as session:
            conditions = [
                and_(TelemetryLLMUsage.timestamp >= h, TelemetryLLMUsage.timestamp < h + 3600)
                for h in hour_ts_list
            ]
            await session.execute(
                TelemetryLLMUsage.__table__.update()
                .where(and_(TelemetryLLMUsage.reported.is_(False), or_(*conditions)))
                .values(reported=True)
            )

    async def delete_telemetry_records_before(self, cutoff_ts: int) -> None:
        async with self.db.transaction() as session:
            await session.execute(delete(TelemetryMessage).where(TelemetryMessage.timestamp < cutoff_ts))
            await session.execute(delete(TelemetryLLMUsage).where(TelemetryLLMUsage.timestamp < cutoff_ts))
