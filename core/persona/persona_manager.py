from typing import Optional

from core.utils.path_utils import get_data_path
from core.db.service import DatabaseService

from .default import default_persona_template
from .model import PersonaInfo


class PersonaManager:
    def __init__(self, db: DatabaseService):
        self.db = db

    async def get_persona(self, persona_id: str = "default") -> Optional[PersonaInfo]:
        """
        Get persona text
        :return: str
        """
        persona_dict = await self.db.get_persona(persona_id)
        if not persona_dict:
            return

        persona = self.wrap_persona(persona_dict)

        return persona

    @staticmethod
    def wrap_persona(persona_dict: dict) -> PersonaInfo:
        return PersonaInfo(
            id=persona_dict.get("id"),
            name=persona_dict.get("name"),
            format=persona_dict.get("format"),
            content=persona_dict.get("content"),
            created_at=persona_dict.get("created_at")
        )

    async def update_persona(self, persona: PersonaInfo):

        success = await self.db.update_persona(
            persona_id=persona.id,
            name=persona.name,
            content=persona.content,
            format=persona.format
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
                created_at=int(time.time())
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
        return await self.db.delete_persona(persona_id)
