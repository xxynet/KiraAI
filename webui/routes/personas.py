import json
from typing import List

from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from core.agent.message import OpenAIMessage
from core.persona.model import PersonaInfo
from core.prompts.persona_generator import get_persona_generator_prompt
from core.provider import LLMRequest

from webui.models import PersonaBase, PersonaGenerateRequest, PersonaResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _generate_id

logger = get_logger("webui", "blue")
SUPPORTED_PERSONA_FORMATS = {"text", "markdown", "json", "yaml"}


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
                path="/api/personas/active",
                methods=["GET"],
                endpoint=self.get_active_persona,
                tags=["personas"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/personas/active",
                methods=["PUT"],
                endpoint=self.set_active_persona,
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
                path="/api/personas/generate",
                methods=["POST"],
                endpoint=self.generate_persona,
                response_model=PersonaBase,
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
            raise HTTPException(status_code=404, detail="Persona not found")
        return {"content": content, "format": persona_format, "name": name, "id": persona_id}

    async def list_personas(self):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        items = await self.lifecycle.persona_manager.list_personas()
        return [PersonaResponse(id=p.id, name=p.name, format=p.format, content=p.content, created_at=p.created_at or 0, is_active=p.is_active or False) for p in items]

    async def get_active_persona(self):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        persona = await self.lifecycle.persona_manager.get_active_persona()
        if not persona:
            raise HTTPException(status_code=404, detail="No active persona found")
        return PersonaResponse(id=persona.id, name=persona.name, format=persona.format, content=persona.content, created_at=persona.created_at or 0, is_active=True)

    async def set_active_persona(self, payload: dict):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        if "persona_id" not in payload:
            raise HTTPException(status_code=422, detail="Missing persona_id field")
        persona_id = payload["persona_id"]
        if not isinstance(persona_id, str):
            raise HTTPException(status_code=422, detail="Invalid persona_id value")
        success = await self.lifecycle.persona_manager.set_active_persona(persona_id)
        if not success:
            raise HTTPException(status_code=404, detail="Persona not found")
        return {"success": True, "active_persona_id": persona_id}

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
        return PersonaResponse(id=created.id, name=created.name, format=created.format, content=created.content, created_at=created.created_at or 0, is_active=created.is_active or False)

    async def generate_persona(self, payload: PersonaGenerateRequest):
        """Generate a draft persona with the configured default LLM."""
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=404, detail="Provider manager not available")
        try:
            client = self.lifecycle.provider_manager.get_default_llm()
            lang = self.lifecycle.kira_config.get_config("locale.lang")
            user_idea = payload.idea.strip() or (
                "请为我创作一个温暖、有特色、适合日常陪伴聊天的原创人设。"
                if (lang or "").lower().startswith("zh")
                else "Create a warm, distinctive original persona for everyday companion chats."
            )
            response = await client.chat(
                LLMRequest(messages=[
                    OpenAIMessage(role="system", content=get_persona_generator_prompt(lang)),
                    OpenAIMessage(role="user", content=user_idea),
                ]),
                max_tokens=1600,
            )
        except Exception as exc:
            logger.exception("Failed to generate persona")
            raise HTTPException(status_code=502, detail="Failed to generate persona") from exc

        try:
            generated = json.loads(response.text_response)
        except (TypeError, json.JSONDecodeError) as exc:
            logger.warning("Persona generator returned invalid JSON")
            raise HTTPException(status_code=502, detail="Persona generator returned an invalid response") from exc

        if not isinstance(generated, dict):
            raise HTTPException(status_code=502, detail="Persona generator returned an invalid response")
        name = generated.get("name")
        persona_format = generated.get("format")
        content = generated.get("content")
        if not all(isinstance(value, str) and value.strip() for value in (name, persona_format, content)):
            raise HTTPException(status_code=502, detail="Persona generator returned an incomplete response")
        if persona_format not in SUPPORTED_PERSONA_FORMATS:
            raise HTTPException(status_code=502, detail="Persona generator returned an unsupported format")
        return PersonaBase(name=name.strip(), format=persona_format, content=content)

    async def get_persona(self, persona_id: str):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        persona = await self.lifecycle.persona_manager.get_persona(persona_id)
        if not persona:
            raise HTTPException(status_code=404, detail="Persona not found")
        return PersonaResponse(id=persona.id, name=persona.name, format=persona.format, content=persona.content, created_at=persona.created_at or 0, is_active=persona.is_active or False)

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
        return PersonaResponse(id=persona_id, name=updated.name, format=updated.format, content=updated.content, created_at=updated.created_at or 0, is_active=updated.is_active or False)

    async def delete_persona(self, persona_id: str):
        if not self.lifecycle or not self.lifecycle.persona_manager:
            raise HTTPException(status_code=404, detail="Persona manager not available")
        try:
            success = await self.lifecycle.persona_manager.delete_persona(persona_id)
            if not success:
                raise HTTPException(status_code=404, detail="Persona not found")
            return None
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
