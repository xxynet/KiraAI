import asyncio
from pathlib import Path
from typing import Optional

from core.db.service import DatabaseService

from .default import default_persona_template
from .model import PersonaInfo
from .reference_image import REFERENCE_IMAGE_DIRECTORY, delete_reference_image, get_reference_image_path, save_reference_image


class PersonaManager:
    def __init__(self, db: DatabaseService):
        self.db = db
        self._reference_image_lock = asyncio.Lock()

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
            return await self.get_active_persona()

    @staticmethod
    def wrap_persona(persona_dict: dict) -> PersonaInfo:
        return PersonaInfo(
            id=persona_dict.get("id"),
            name=persona_dict.get("name"),
            format=persona_dict.get("format"),
            content=persona_dict.get("content"),
            created_at=persona_dict.get("created_at"),
            is_active=persona_dict.get("is_active", False),
            reference_image_path=persona_dict.get("reference_image_path"),
        )

    async def update_persona(self, persona: PersonaInfo):
        # Activation changes are routed through set_active_persona to maintain
        # the single-active-persona invariant in the database.
        if persona.is_active is True:
            await self.set_active_persona(persona.id)

        success = await self.db.update_persona(
            persona_id=persona.id,
            name=persona.name,
            content=persona.content,
            format=persona.format,
        )
        return success

    async def init_persona(self):
        personas = await self.db.list_personas()
        if not personas:
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
            reference_image_path=persona.reference_image_path,
        )
        return True

    async def delete_persona(self, persona_id: str) -> bool:
        """Delete a persona. Cannot delete the active persona."""
        # Check if this is the active persona
        active = await self.get_active_persona()
        if active and active.id == persona_id:
            raise ValueError("Cannot delete the active persona. Switch to another persona first.")
        async with self._reference_image_lock:
            persona = await self.get_persona(persona_id)
            if not persona:
                return False
            deleted = await self.db.delete_persona(persona_id)
            if deleted:
                await asyncio.to_thread(delete_reference_image, persona.id, persona.reference_image_path)
            return deleted

    async def get_reference_image(self, persona_id: Optional[str] = None) -> Optional[Path]:
        """Get the database-recorded selfie reference for a given or active persona."""
        async with self._reference_image_lock:
            persona = await self.get_persona(persona_id)
            if not persona:
                return None
            return await asyncio.to_thread(get_reference_image_path, persona.id, persona.reference_image_path)

    async def set_reference_image(self, persona_id: str, file_bytes: bytes, filename: str) -> Path:
        """Replace a selfie reference and persist its path before removing the old file."""
        async with self._reference_image_lock:
            persona = await self.get_persona(persona_id)
            if not persona:
                raise LookupError("Persona not found")
            previous_path = await asyncio.to_thread(get_reference_image_path, persona.id, persona.reference_image_path)
            previous_bytes = await asyncio.to_thread(previous_path.read_bytes) if previous_path else None
            path = await asyncio.to_thread(save_reference_image, persona_id, file_bytes, filename)
            stored_path = f"{REFERENCE_IMAGE_DIRECTORY}/{path.name}"
            try:
                if not await self.db.update_persona(persona_id, reference_image_path=stored_path):
                    raise LookupError("Persona not found")
            except Exception:
                if previous_path == path and previous_bytes is not None:
                    await asyncio.to_thread(save_reference_image, persona_id, previous_bytes, previous_path.name)
                else:
                    await asyncio.to_thread(delete_reference_image, persona_id, stored_path)
                raise
            if previous_path and previous_path != path:
                await asyncio.to_thread(delete_reference_image, persona_id, persona.reference_image_path)
            return path

    async def set_active_persona(self, persona_id: str) -> bool:
        """Set a persona as the active one."""
        return await self.db.set_active_persona(persona_id)

    async def get_active_persona(self) -> Optional[PersonaInfo]:
        """Get the currently active persona."""
        persona_dict = await self.db.get_active_persona()
        if not persona_dict:
            return None
        return self.wrap_persona(persona_dict)
