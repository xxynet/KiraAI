import asyncio
import mimetypes
import re
from pathlib import PureWindowsPath

from fastapi import Depends, HTTPException, status
from fastapi.responses import FileResponse

from core.chat.message_elements import _infer_mime_from_bytes
from core.chat.session import Session
from core.utils.media_refs import MEDIA_ROOT_NAME
from core.utils.path_utils import get_data_path, is_within_directory

from core.logging_manager import get_logger
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class SessionsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/messages", methods=["GET"], endpoint=self.list_messages,
                tags=["sessions"], dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/messages/{message_id}/media", methods=["GET"], endpoint=self.get_message_media,
                tags=["sessions"], dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/messages/{message_id}", methods=["GET"], endpoint=self.get_message,
                tags=["sessions"], dependencies=[Depends(require_auth)],
            ),
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

    @property
    def message_history(self):
        return getattr(self.lifecycle, "message_history", None)

    async def list_messages(self, session_id: str, cursor: str | None = None,
                            limit: int = 50, llm_message_id: str | None = None):
        if self.message_history is None:
            raise HTTPException(status_code=503, detail="Message history unavailable")
        try:
            page = await self.message_history.list_messages(
                session_id, cursor=cursor, limit=limit, llm_message_id=llm_message_id)
            return page.to_dict()
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def get_message(self, message_id: str):
        if self.message_history is None:
            raise HTTPException(status_code=503, detail="Message history unavailable")
        message = await self.message_history.get_message(internal_message_id=message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        return {"message": message.to_dict(), "memory": await self.message_history.get_linked_memory(message)}

    async def get_message_media(self, message_id: str, element_path: str):
        """Serve only archived media referenced by a persisted message element."""
        if self.message_history is None:
            raise HTTPException(status_code=503, detail="Message history unavailable")
        if not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}", element_path):
            raise HTTPException(status_code=400, detail="Invalid element path")
        message = await self.message_history.get_message(internal_message_id=message_id)
        if message is None:
            raise HTTPException(status_code=404, detail="Message not found")
        element = message.to_dict()
        for part in element_path.split("."):
            chain = element.get("chain")
            index = int(part)
            if not isinstance(chain, list) or index >= len(chain) or not isinstance(chain[index], dict):
                raise HTTPException(status_code=404, detail="Message element not found")
            element = chain[index]
        file = element.get("file")
        if (element.get("type") not in {"image", "sticker", "record", "video", "file"}
                or element.get("file_type") != "archive" or not isinstance(file, str)
                or not re.fullmatch(rf"{MEDIA_ROOT_NAME}/archive/[0-9a-f]{{64}}", file)):
            raise HTTPException(status_code=404, detail="Archived media unavailable")

        def resolve_media():
            root = get_data_path() / MEDIA_ROOT_NAME / "archive"
            target = (get_data_path() / file).resolve()
            if not is_within_directory(root, target) or not target.is_file():
                raise HTTPException(status_code=404, detail="Archived media unavailable")
            with target.open("rb") as source:
                inferred = _infer_mime_from_bytes(source.read(16))
            return target, inferred

        try:
            target, inferred_mime = await asyncio.to_thread(resolve_media)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=404, detail="Archived media unavailable") from exc
        name = element.get("name")
        filename = PureWindowsPath(name).name if isinstance(name, str) and name else target.name
        mime = inferred_mime or element.get("mime") or mimetypes.guess_type(filename)[0]
        if not isinstance(mime, str) or not re.fullmatch(r"(?:image|audio|video)/[a-zA-Z0-9.+-]+", mime):
            mime = "application/octet-stream"
        return FileResponse(target, media_type=mime, filename=filename, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })

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

    @staticmethod
    def _session_response(session_id: str, row: Session | None) -> dict:
        parts = session_id.split(":", 2)
        adapter, kind, target = parts if len(parts) == 3 else ("", "", session_id)
        return {
            "id": session_id,
            "internal_id": row.internal_id if row else None,
            "created_at": row.created_at if row else None,
            "updated_at": row.updated_at if row else None,
            "adapter_name": adapter, "session_type": kind, "session_id": target,
            "title": row.session_title if row else "",
            "description": row.session_description if row else "",
            "capabilities": row.data.get("capabilities") if row else None,
            "messages": row.content if row else [],
            "message_count": len(row.content) if row and isinstance(row.content, list) else 0,
        }

    async def list_sessions(self):
        if not self.lifecycle or not self.lifecycle.session_manager:
            return {"sessions": []}

        records = await self.lifecycle.session_manager.get_sessions(include_content=False)
        message_counts = await self.lifecycle.session_manager.get_session_message_counts()
        malformed = set()
        sessions = []
        for row in records:
            sid = row.sid
            if not isinstance(row.data, dict):
                malformed.add(sid)
                continue
            if len(sid.split(":", 2)) != 3:
                continue
            item = self._session_response(sid, row)
            item.pop("messages")
            item.pop("capabilities")
            item["message_count"] = message_counts.get(sid, 0)
            sessions.append(item)
        if self.message_history is not None:
            history_sessions = await self.message_history.list_sessions()
            by_id = {item["id"]: item for item in sessions}
            for item in history_sessions:
                sid = item.session_id
                if sid in malformed or len(sid.split(":", 2)) != 3:
                    continue
                if sid not in by_id:
                    record = self._session_response(sid, None)
                    record.pop("messages")
                    record.pop("capabilities")
                    record["message_count"] = 0
                    sessions.append(record)
                    by_id[sid] = record
                by_id[sid]["history_count"] = item.message_count
        return {"sessions": sessions}

    async def get_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")
        if len(session_id.split(":", 2)) != 3:
            raise HTTPException(status_code=400, detail="Invalid session id format")

        try:
            row = await self.lifecycle.session_manager.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        if row is None or row.content is None:
            history = await self.message_history.list_messages(session_id, limit=1) if self.message_history else None
            if history is None or not history.messages:
                raise HTTPException(status_code=404, detail="Session not found")
            response = self._session_response(session_id, row)
            response["messages"] = []
            return response
        return self._session_response(session_id, row)

    async def update_session(self, session_id: str, payload: dict):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")

        messages = payload.get("messages")
        capabilities_provided = "capabilities" in payload
        capabilities = payload.get("capabilities")
        if capabilities_provided:
            self._validate_capabilities_payload(capabilities)

        changes = {key: payload[key] for key in ("title", "description") if key in payload}
        if messages is not None:
            changes["content"] = messages
        if changes:
            try:
                await self.lifecycle.session_manager.update_session(session_id, **changes)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        if capabilities_provided:
            await self.lifecycle.session_manager.update_session_capabilities(
                session_id, capabilities
            )

        try:
            row = await self.lifecycle.session_manager.get_session(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="Session not found") from exc
        return self._session_response(session_id, row)

    async def delete_session(self, session_id: str):
        if not self.lifecycle or not self.lifecycle.session_manager:
            raise HTTPException(status_code=404, detail="Memory manager not available")
        await self.lifecycle.session_manager.delete_session(session_id)
        # Clean up scope entries referencing this session
        if self.lifecycle.mcp_manager:
            self.lifecycle.mcp_manager.remove_session_from_scopes(session_id)
        if self.lifecycle.skills_manager:
            self.lifecycle.skills_manager.remove_session_from_scopes(session_id)
        return None
