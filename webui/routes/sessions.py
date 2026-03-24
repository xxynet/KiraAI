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

    async def list_sessions(self):
        if not self.lifecycle or not self.lifecycle.memory_manager:
            return {"sessions": []}

        session_keys = list(self.lifecycle.memory_manager.chat_memory.keys())
        sessions = []
        for session_key in session_keys:
            parts = session_key.split(":")
            if len(parts) < 3:
                continue
            adapter_name, session_type, session_id = parts[0], parts[1], ":".join(parts[2:])
            session_meta = self.lifecycle.memory_manager.chat_memory.get(session_key, {})
            title = session_meta.get("title", "")
            description = session_meta.get("description", "")
            sessions.append({
                "id": session_key,
                "adapter_name": adapter_name,
                "session_type": session_type,
                "session_id": session_id,
                "title": title,
                "description": description,
                "message_count": self.lifecycle.memory_manager.get_memory_count(session_key),
            })
        return {"sessions": sessions}

    async def get_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.memory_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")

        memory = self.lifecycle.memory_manager.read_memory(session_id)

        parts = session_id.split(":")
        if len(parts) < 3:
            raise HTTPException(status_code=400, detail="Invalid session id format")

        adapter_name, session_type, session_key = parts[0], parts[1], ":".join(parts[2:])
        session_meta = self.lifecycle.memory_manager.chat_memory.get(session_id, {})
        title = session_meta.get("title", "")
        description = session_meta.get("description", "")

        return {
            "id": session_id,
            "adapter_name": adapter_name,
            "session_type": session_type,
            "session_id": session_key,
            "title": title,
            "description": description,
            "messages": memory,
        }

    async def update_session(self, session_id: str, payload: dict):
        if not self.lifecycle or not self.lifecycle.memory_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")

        messages = payload.get("messages")
        title = payload.get("title")
        description = payload.get("description")

        if messages is not None:
            self.lifecycle.memory_manager.write_memory(session_id, messages)

        if title is not None or description is not None:
            self.lifecycle.memory_manager.update_session_info(
                session_id, title=title, description=description
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

        return {
            "id": session_id,
            "adapter_name": adapter_name,
            "session_type": session_type,
            "session_id": session_key,
            "title": title if title is not None else "",
            "description": description if description is not None else "",
            "messages": messages,
        }

    async def delete_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.memory_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")
        self.lifecycle.memory_manager.delete_session(session_id)
        return None
