"""Database operations for stickers."""

from typing import Optional

from sqlalchemy import select

from ..db_mgr import DatabaseManager
from ..models import Sticker


class StickerMixin:
    db: DatabaseManager

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
