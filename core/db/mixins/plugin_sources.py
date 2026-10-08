"""Database operations for plugin_sources."""

from typing import Optional

from sqlalchemy import select

from ..db_mgr import DatabaseManager
from ..models import PluginStoreSource


class PluginSourceMixin:
    db: DatabaseManager

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
