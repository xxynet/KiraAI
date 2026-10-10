import asyncio
import base64
import mimetypes
import re
from pathlib import PureWindowsPath
from uuid import UUID
from typing import Literal

from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from core.chat.message_elements import File as FileElement, Image, _infer_mime_from_bytes
from core.utils.path_utils import is_within_directory
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes


MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_ATTACHMENTS = 10


class WebChatProfile(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    nickname: str = Field(min_length=1, max_length=80)
    peer_nickname: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=4000)


class WebChatMessage(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    request_id: UUID
    text: str = Field(min_length=1, max_length=16000)


class WebChatRoutes(Routes):
    def get_routes(self):
        return [RouteDefinition(path="/api/webchat" + path, methods=[method], endpoint=endpoint,
                                tags=["webchat"], dependencies=[Depends(require_auth)])
                for path, method, endpoint in [
                    ("", "GET", self.state),
                    ("/profile", "PUT", self.save_profile),
                    ("/messages", "GET", self.messages),
                    ("/messages", "DELETE", self.clear_messages),
                    ("/messages", "POST", self.send),
                    ("/messages/upload", "POST", self.send_with_attachments),
                    ("/messages/{message_id}/media", "GET", self.media),
                ]]

    @property
    def service(self):
        service = getattr(self.lifecycle, "webchat", None)
        if service is None:
            raise HTTPException(503, detail="unavailable")
        return service

    async def state(self):
        store = self.service.store
        return {"profile": await store.get_setting("profile"), "request": await store.latest_request()}

    async def save_profile(self, payload: WebChatProfile):
        try:
            return await self.service.save_profile(payload.model_dump())
        except ValueError as exc:
            raise HTTPException(409, detail=str(exc)) from exc

    async def send(self, payload: WebChatMessage):
        try:
            return await self.service.submit(str(payload.request_id), payload.text)
        except ValueError as exc:
            code = str(exc)
            raise HTTPException(503 if code == "unavailable" else 409, detail=code) from exc

    async def send_with_attachments(
        self,
        request_id: UUID = Form(...),
        text: str = Form("", max_length=16000),
        kinds: list[Literal["image", "file"]] = Form(...),
        files: list[UploadFile] = File(...),
    ):
        try:
            service = self.service
            if await service.store.get_setting("profile") is None:
                raise HTTPException(409, detail="setup_required")
            if not 1 <= len(files) <= MAX_ATTACHMENTS or len(files) != len(kinds):
                raise HTTPException(400, detail="attachment_count")
            total = 0
            attachments = []
            for upload, kind in zip(files, kinds):
                content = await upload.read(MAX_ATTACHMENT_BYTES - total + 1)
                total += len(content)
                if total > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(413, detail="attachments_too_large")
                name = PureWindowsPath(upload.filename or "attachment").name
                if not name or name in {".", ".."} or len(name) > 255 or any(ord(char) < 32 for char in name):
                    raise HTTPException(400, detail="invalid_attachment")

                def make_element():
                    mime = _infer_mime_from_bytes(content) if kind == "image" else "application/octet-stream"
                    if not mime:
                        raise ValueError("invalid_image")
                    encoded = base64.b64encode(content).decode("ascii")
                    element = (Image if kind == "image" else FileElement)(
                        f"data:{mime};base64,{encoded}", name=name, mime=mime,
                    )
                    element.size = len(content)
                    return element

                attachments.append(await asyncio.to_thread(make_element))
            return await service.submit(str(request_id), text.strip(), attachments)
        except ValueError as exc:
            code = str(exc)
            status_code = 503 if code == "unavailable" else 409 if code == "request_conflict" else 400
            raise HTTPException(status_code, detail=code) from exc
        finally:
            for upload in files:
                await upload.close()

    async def messages(self, before: int | None = Query(None, ge=1), after: int = Query(0, ge=0)):
        if before is not None and after:
            raise HTTPException(400, detail="Invalid cursor")
        return await self.service.store.list_messages(before=before, after=after)

    async def clear_messages(self):
        try:
            await self.service.clear_messages()
        except ValueError as exc:
            raise HTTPException(503, detail="unavailable") from exc
        except OSError as exc:
            raise HTTPException(500, detail="delete_failed") from exc
        return {"ok": True}

    async def media(self, message_id: str, element_path: str):
        store = self.service.store
        if not re.fullmatch(r"[0-9]{1,6}(?:\.[0-9]{1,6}){0,3}", element_path):
            raise HTTPException(400, detail="Invalid element path")
        element = await store.get_message(message_id)
        for part in element_path.split("."):
            chain = element.get("chain") if isinstance(element, dict) else None
            index = int(part)
            if not isinstance(chain, list) or index >= len(chain):
                raise HTTPException(404, detail="Media not found")
            element = chain[index]
        if (not isinstance(element, dict) or element.get("file_type") != "archive"
                or not re.fullmatch(r"[0-9a-f]{64}", str(element.get("file", "")))):
            raise HTTPException(404, detail="Media not found")

        def resolve():
            target = (store.media_dir / element["file"]).resolve()
            if not is_within_directory(store.media_dir, target) or not target.is_file():
                raise HTTPException(404, detail="Media not found")
            with target.open("rb") as source:
                mime = _infer_mime_from_bytes(source.read(16))
            return target, mime

        try:
            target, mime = await asyncio.to_thread(resolve)
        except (OSError, ValueError) as exc:
            raise HTTPException(404, detail="Media not found") from exc
        name = PureWindowsPath(element.get("name") or target.name).name
        mime = mime or mimetypes.guess_type(name)[0] or "application/octet-stream"
        if not re.fullmatch(r"(?:image|audio|video)/[a-zA-Z0-9.+-]+", mime):
            mime = "application/octet-stream"
        return FileResponse(target, media_type=mime, filename=name, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        })
