"""Database operations for personas."""

import time
from typing import Optional

from sqlalchemy import select, update

from ..db_mgr import DatabaseManager
from ..models import Persona


class PersonaMixin:
    db: DatabaseManager

    async def add_persona(
        self,
        persona_id: str,
        name: str,
        content: str,
        format: str = "text",
        created_at: Optional[int] = None,
        is_active: bool = False,
        reference_image_path: Optional[str] = None,
        chat_rules: str = "",
        private_chat_rules: str = "",
        group_chat_rules: str = "",
    ) -> None:
        if created_at is None:
            created_at = int(time.time())
        async with self.db.transaction() as session:
            session.add(Persona(id=persona_id, name=name, format=format, content=content, created_at=created_at, is_active=is_active, reference_image_path=reference_image_path, chat_rules=chat_rules, private_chat_rules=private_chat_rules, group_chat_rules=group_chat_rules))

    async def get_persona(self, persona_id: str) -> Optional[dict]:
        stmt = select(Persona).where(Persona.id == persona_id)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["Persona"]
        return {"id": item.id, "name": item.name, "format": item.format, "content": item.content, "created_at": item.created_at, "is_active": item.is_active, "reference_image_path": item.reference_image_path, "chat_rules": item.chat_rules, "private_chat_rules": item.private_chat_rules, "group_chat_rules": item.group_chat_rules}

    async def update_persona(
        self,
        persona_id: str,
        name: Optional[str] = None,
        content: Optional[str] = None,
        format: Optional[str] = None,
        reference_image_path: Optional[str] = None,
        chat_rules: Optional[str] = None,
        private_chat_rules: Optional[str] = None,
        group_chat_rules: Optional[str] = None,
    ) -> bool:
        """Update non-activation fields of a persona.

        Activation changes must go through set_active_persona() to maintain
        the single-active-persona invariant.
        """
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
            if reference_image_path is not None:
                item.reference_image_path = reference_image_path
            if chat_rules is not None:
                item.chat_rules = chat_rules
            if private_chat_rules is not None:
                item.private_chat_rules = private_chat_rules
            if group_chat_rules is not None:
                item.group_chat_rules = group_chat_rules
            return True

    async def clear_persona_reference_image(self, persona_id: str) -> bool:
        """Clear the reference path without changing other persona fields."""
        async with self.db.transaction() as session:
            result = await session.execute(
                update(Persona).where(Persona.id == persona_id).values(reference_image_path=None)
            )
            return result.rowcount > 0

    async def set_active_persona(self, persona_id: str) -> bool:
        """Set a persona as the active one and deactivate all others."""
        async with self.db.transaction() as session:
            # Confirm the target persona exists before touching anything
            result = await session.execute(
                select(Persona).where(Persona.id == persona_id)
            )
            item = result.scalar_one_or_none()
            if item is None:
                return False

            # Deactivate all personas (including the target, for a clean reset)
            result = await session.execute(
                select(Persona).where(Persona.is_active)
            )
            for row in result.scalars().all():
                row.is_active = False

            # Activate the target persona
            item.is_active = True
            return True

    async def get_active_persona(self) -> Optional[dict]:
        """Get the currently active persona."""
        stmt = select(Persona).where(Persona.is_active)
        row = await self.db.fetch_one(stmt)
        if row is None:
            return None
        item = row["Persona"]
        return {"id": item.id, "name": item.name, "format": item.format, "content": item.content, "created_at": item.created_at, "is_active": item.is_active, "reference_image_path": item.reference_image_path, "chat_rules": item.chat_rules, "private_chat_rules": item.private_chat_rules, "group_chat_rules": item.group_chat_rules}

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
            {"id": r["Persona"].id, "name": r["Persona"].name, "format": r["Persona"].format, "content": r["Persona"].content, "created_at": r["Persona"].created_at, "is_active": r["Persona"].is_active, "reference_image_path": r["Persona"].reference_image_path, "chat_rules": r["Persona"].chat_rules, "private_chat_rules": r["Persona"].private_chat_rules, "group_chat_rules": r["Persona"].group_chat_rules}
            for r in rows
        ]
