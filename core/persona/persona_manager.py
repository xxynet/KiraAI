from typing import Optional

from core.utils.path_utils import get_data_path
from core.db.service import DatabaseService

from .default import default_persona_template
from .model import PersonaInfo


class PersonaManager:
    def __init__(self, db: DatabaseService):
        self.db = db

    async def get_persona(self, persona_id: Optional[str] = None) -> Optional[PersonaInfo]:
        """
        Get persona text.
        If persona_id is specified, get that persona.
        Otherwise, get the currently active persona.
        :return: PersonaInfo
        """
        if persona_id:
            persona_dict = await self.db.get_persona(persona_id)
            if not persona_dict:
                return None
            return self.wrap_persona(persona_dict)
        else:
            # Get the currently active persona
            active_persona = await self.get_active_persona()
            if active_persona:
                return active_persona
            # Fallback to default persona if no active persona
            persona_dict = await self.db.get_persona("default")
            if not persona_dict:
                return None
            return self.wrap_persona(persona_dict)

    @staticmethod
    def wrap_persona(persona_dict: dict) -> PersonaInfo:
        return PersonaInfo(
            id=persona_dict.get("id"),
            name=persona_dict.get("name"),
            format=persona_dict.get("format"),
            content=persona_dict.get("content"),
            created_at=persona_dict.get("created_at"),
            is_active=persona_dict.get("is_active", False)
        )

    async def update_persona(self, persona: PersonaInfo):

        success = await self.db.update_persona(
            persona_id=persona.id,
            name=persona.name,
            content=persona.content,
            format=persona.format,
            is_active=persona.is_active if persona.is_active is not None else None
        )
        return success

    async def init_persona(self):
        persona_dict = await self.db.get_persona(persona_id="default")
        if not persona_dict:
            import time
            await self.db.add_persona(
                persona_id="default",
                name="Default",
                content=default_persona_template,
                format="yaml",
                created_at=int(time.time()),
                is_active=True
            )

    async def list_personas(self) -> list[PersonaInfo]:
        rows = await self.db.list_personas()
        return [self.wrap_persona(r) for r in rows]

    async def create_persona(self, persona: PersonaInfo) -> bool:
        await self.db.add_persona(
            persona_id=persona.id,
            name=persona.name,
            content=persona.content,
            format=persona.format,
        )
        return True

    async def delete_persona(self, persona_id: str) -> bool:
        """Delete a persona. Cannot delete the active persona."""
        # Check if this is the active persona
        active = await self.get_active_persona()
        if active and active.id == persona_id:
            raise ValueError("Cannot delete the active persona. Switch to another persona first.")
        return await self.db.delete_persona(persona_id)

    async def set_active_persona(self, persona_id: str) -> bool:
        """Set a persona as the active one."""
        return await self.db.set_active_persona(persona_id)

    async def get_active_persona(self) -> Optional[PersonaInfo]:
        """Get the currently active persona."""
        persona_dict = await self.db.get_active_persona()
        if not persona_dict:
            return None
        return self.wrap_persona(persona_dict)
