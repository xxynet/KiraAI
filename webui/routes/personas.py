from typing import Dict, List

from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from webui.models import PersonaBase, PersonaResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _generate_id

logger = get_logger("webui", "blue")


class PersonasRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._personas: Dict[str, PersonaResponse] = {}

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
            persona_content = self.lifecycle.persona_manager.get_persona()
            fmt = self.lifecycle.persona_manager._format
            return {"content": persona_content, "format": fmt}
        raise HTTPException(status_code=404, detail="Persona manager not available")

    async def update_current_persona_content(self, payload: dict):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        content = payload.get("content", "")
        fmt = payload.get("format", "text")
        if not isinstance(fmt, str) or not fmt.strip():
            raise HTTPException(status_code=422, detail="Invalid format value")
        from core.persona.persona_manager import ALLOWED_FORMATS
        if fmt not in ALLOWED_FORMATS:
            raise HTTPException(status_code=422, detail=f"Format must be one of {ALLOWED_FORMATS}")
        self.lifecycle.persona_manager.update_persona(content)
        self.lifecycle.persona_manager.set_format(fmt)
        return {"content": content, "format": fmt}

    async def list_personas(self):
        return list(self._personas.values())

    async def create_persona(self, payload: PersonaBase):
        persona_id = _generate_id()
        persona = PersonaResponse(id=persona_id, **payload.model_dump())
        self._personas[persona_id] = persona
        return persona

    async def get_persona(self, persona_id: str):
        persona = self._personas.get(persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        return persona

    async def update_persona(self, persona_id: str, payload: PersonaBase):
        persona = self._personas.get(persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        updated = persona.model_copy(update=payload.model_dump())
        self._personas[persona_id] = updated
        return updated

    async def delete_persona(self, persona_id: str):
        if persona_id not in self._personas:
            raise HTTPException(status_code=404, detail="Persona not found")
        self._personas.pop(persona_id, None)
        return None
