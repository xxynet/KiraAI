"""Database operations for image_cache."""

import time
from typing import Optional

from sqlalchemy import and_, delete, or_, select

from ..db_mgr import DatabaseManager
from ..models import ImageDescCache


class ImageCacheMixin:
    db: DatabaseManager

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
