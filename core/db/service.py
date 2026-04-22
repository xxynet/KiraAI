import time
from typing import Optional
from sqlalchemy import select, delete, or_, and_

from .db_mgr import DatabaseManager
from .models import Sticker, ImageDescCache, Persona


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
