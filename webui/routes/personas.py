from typing import List

from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from core.persona.model import PersonaInfo

from webui.models import PersonaBase, PersonaResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _generate_id

logger = get_logger("webui", "blue")


class PersonasRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/personas/current/content",
                methods=["GET"],
                endpoint=self.get_current_persona_content,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas/current/content",
                methods=["PUT"],
                endpoint=self.update_current_persona_content,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas",
                methods=["GET"],
                endpoint=self.list_personas,
                response_model=List[PersonaResponse],
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas",
                methods=["POST"],
                endpoint=self.create_persona,
                response_model=PersonaResponse,
                status_code=status.HTTP_201_CREATED,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas/{persona_id}",
                methods=["GET"],
                endpoint=self.get_persona,
                response_model=PersonaResponse,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas/{persona_id}",
                methods=["PUT"],
                endpoint=self.update_persona,
                response_model=PersonaResponse,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas/{persona_id}",
                methods=["DELETE"],
                endpoint=self.delete_persona,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_current_persona_content(self):
        if self.lifecycle and self.lifecycle.persona_manager:
            persona = await self.lifecycle.persona_manager.get_persona()
            persona_content = persona.content
            persona_format = persona.format
            persona_name = persona.name
            return {"content": persona_content, "format": persona_format, "name": persona_name}
        raise HTTPException(status_code=404, detail="Persona manager not available")

    async def update_current_persona_content(self, payload: dict):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        if "content" not in payload:
            raise HTTPException(status_code=422, detail="Missing content field")
        content = payload["content"]
        if not isinstance(content, str):
            raise HTTPException(status_code=422, detail="Invalid content value")
        persona_id = "default"
        # Preserve existing name/format when the caller only supplies content,
        # so partial updates from clients that don't know about `name` don't
        # wipe unrelated fields. Missing default persona is treated as 404 so
        # clients don't silently persist against a non-existent row.
        existing = await self.lifecycle.persona_manager.get_persona(persona_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Persona not found")
        name = payload["name"] if "name" in payload else existing.name
        persona_format = payload["format"] if "format" in payload else existing.format
        if not isinstance(name, str):
            raise HTTPException(status_code=422, detail="Invalid name value")
        if not isinstance(persona_format, str):
            raise HTTPException(status_code=422, detail="Invalid format value")
        persona = PersonaInfo(
            id=persona_id,
            name=name,
            format=persona_format,
            content=content,
        )
        success = await self.lifecycle.persona_manager.update_persona(persona)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update persona")
        return {"content": content, "format": persona_format, "name": name, "id": persona_id}

    async def list_personas(self):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        items = await self.lifecycle.persona_manager.list_personas()
        return [PersonaResponse(id=p.id, name=p.name, format=p.format, content=p.content, created_at=p.created_at or 0) for p in items]

    async def create_persona(self, payload: PersonaBase):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        persona_id = _generate_id()
        persona = PersonaInfo(
            id=persona_id,
            name=payload.name,
            format=payload.format,
            content=payload.content,
        )
        await self.lifecycle.persona_manager.create_persona(persona)
        created = await self.lifecycle.persona_manager.get_persona(persona_id)
        if not created:
            raise HTTPException(status_code=500, detail="Failed to create persona")
        return PersonaResponse(id=created.id, name=created.name, format=created.format, content=created.content, created_at=created.created_at or 0)

    async def get_persona(self, persona_id: str):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        persona = await self.lifecycle.persona_manager.get_persona(persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        return PersonaResponse(id=persona.id, name=persona.name, format=persona.format, content=persona.content, created_at=persona.created_at or 0)

    async def update_persona(self, persona_id: str, payload: PersonaBase):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        persona = PersonaInfo(
            id=persona_id,
            name=payload.name,
            format=payload.format,
            content=payload.content,
        )
        success = await self.lifecycle.persona_manager.update_persona(persona)
        if not success:
            raise HTTPException(status_code=404, detail="Persona not found")
        updated = await self.lifecycle.persona_manager.get_persona(persona_id)
        return PersonaResponse(id=persona_id, name=updated.name, format=updated.format, content=updated.content, created_at=updated.created_at or 0)

    async def delete_persona(self, persona_id: str):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        success = await self.lifecycle.persona_manager.delete_persona(persona_id)
        if not success:
            raise HTTPException(status_code=404, detail="Persona not found")
        return None
