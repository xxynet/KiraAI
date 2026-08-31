from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class SessionsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/sessions",
                methods=["GET"],
                endpoint=self.list_sessions,
                tags=["sessions"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/sessions/{session_id:path}",
                methods=["GET"],
                endpoint=self.get_session,
                tags=["sessions"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/sessions/{session_id:path}",
                methods=["PUT"],
                endpoint=self.update_session,
                tags=["sessions"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/sessions/{session_id:path}",
                methods=["DELETE"],
                endpoint=self.delete_session,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["sessions"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    @staticmethod
    def _validate_capabilities_payload(capabilities: object) -> None:
        """Validate a session capability override before mutating session data."""
        if capabilities is None:
            return
        if not isinstance(capabilities, dict):
            raise HTTPException(status_code=400, detail="Capabilities must be an object or null")

        capability_schema = {
            "image_recognition": {"enabled": bool, "mode": str, "desc_prompt": str},
            "tts": {"enabled": bool},
            "stt": {"enabled": bool},
            "image_generation": {"enabled": bool},
            "video_generation": {"enabled": bool},
            "forward_parsing": {"enabled": bool},
        }
        for group_name, group_config in capabilities.items():
            expected_fields = capability_schema.get(group_name)
            if expected_fields is None or not isinstance(group_config, dict):
                raise HTTPException(status_code=400, detail=f"Invalid capability group: {group_name}")
            for field_name, field_value in group_config.items():
                expected_type = expected_fields.get(field_name)
                if expected_type is None or not isinstance(field_value, expected_type):
                    raise HTTPException(status_code=400, detail=f"Invalid capability field: {group_name}.{field_name}")
            if group_name == "image_recognition" and group_config.get("mode") not in (None, "vlm_description", "native"):
                raise HTTPException(status_code=400, detail="Invalid image recognition mode")

    async def list_sessions(self):
        if not self.lifecycle or not self.lifecycle.session_manager:
            return {"sessions": []}

        session_keys = list(self.lifecycle.session_manager.chat_memory.keys())
        sessions = []
        for session_key in session_keys:
            parts = session_key.split(":")
            if len(parts) < 3:
                continue
            adapter_name, session_type, session_id = parts[0], parts[1], ":".join(parts[2:])
            session_meta = self.lifecycle.session_manager.chat_memory.get(session_key, {})
            title = session_meta.get("title", "")
            description = session_meta.get("description", "")
            sessions.append({
                "id": session_key,
                "adapter_name": adapter_name,
                "session_type": session_type,
                "session_id": session_id,
                "title": title,
                "description": description,
                "message_count": self.lifecycle.session_manager.get_memory_count(session_key),
            })
        return {"sessions": sessions}

    async def get_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")

        parts = session_id.split(":")
        if len(parts) < 3:
            raise HTTPException(status_code=400, detail="Invalid session id format")

        memory = self.lifecycle.session_manager.read_memory(session_id)

        adapter_name, session_type, session_key = parts[0], parts[1], ":".join(parts[2:])
        session_meta = self.lifecycle.session_manager.chat_memory.get(session_id, {})
        title = session_meta.get("title", "")
        description = session_meta.get("description", "")

        return {
            "id": session_id,
            "adapter_name": adapter_name,
            "session_type": session_type,
            "session_id": session_key,
            "title": title,
            "description": description,
            "capabilities": session_meta.get("capabilities"),
            "messages": memory,
        }

    async def update_session(self, session_id: str, payload: dict):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")

        messages = payload.get("messages")
        title = payload.get("title")
        capabilities_provided = "capabilities" in payload
        capabilities = payload.get("capabilities")
        description = payload.get("description")
        if capabilities_provided:
            self._validate_capabilities_payload(capabilities)

        if messages is not None:
            self.lifecycle.session_manager.write_memory(session_id, messages)

        if title is not None or description is not None:
            self.lifecycle.session_manager.update_session_info(
                session_id, title=title, description=description
            )
        if capabilities_provided:
            self.lifecycle.session_manager.update_session_capabilities(
                session_id, capabilities
            )


        parts = session_id.split(":")
        if len(parts) >= 3:
            adapter_name = parts[0]
            session_type = parts[1]
            session_key = ":".join(parts[2:])
        else:
            adapter_name = ""
            session_type = ""
            session_key = session_id

        session_meta = self.lifecycle.session_manager.chat_memory.get(session_id, {})
        return {
            "id": session_id,
            "adapter_name": adapter_name,
            "session_type": session_type,
            "session_id": session_key,
            "title": title if title is not None else "",
            "description": description if description is not None else "",
            "capabilities": session_meta.get("capabilities"),
            "messages": messages,
        }

    async def delete_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")
        self.lifecycle.session_manager.delete_session(session_id)
        # Clean up scope entries referencing this session
        if self.lifecycle.mcp_manager:
            self.lifecycle.mcp_manager.remove_session_from_scopes(session_id)
        if self.lifecycle.skills_manager:
            self.lifecycle.skills_manager.remove_session_from_scopes(session_id)
        return None
