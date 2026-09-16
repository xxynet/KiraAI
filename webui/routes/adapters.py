import asyncio
import base64
import io
import secrets
import time
from dataclasses import dataclass
from typing import Dict, List
from urllib.parse import quote

from fastapi import Depends, HTTPException, status
from fastapi.responses import FileResponse
import qrcode
from qrcode.image.svg import SvgPathImage

from core.adapter.qr_login import QRCodeLoginHandler, QRCodeLoginPollResult
from core.logging_manager import get_logger
from webui.models import AdapterBase, AdapterResponse, QRCodeLoginStartRequest
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import schema_to_dict
from webui.utils import _generate_id

logger = get_logger("webui", "blue")


@dataclass
class _QRCodeLoginSession:
    handler: QRCodeLoginHandler
    expires_at: float
    lock: asyncio.Lock
    terminal_result: QRCodeLoginPollResult | None = None


class AdaptersRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._adapters: Dict[str, AdapterResponse] = {}
        self._qrcode_login_sessions: Dict[str, _QRCodeLoginSession] = {}

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/adapter-platforms",
                methods=["GET"],
                endpoint=self.get_adapter_platforms,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapter-platforms/{platform}/icon",
                methods=["GET"],
                endpoint=self.get_adapter_platform_icon,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/schema/{platform}",
                methods=["GET"],
                endpoint=self.get_adapter_schema,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/login/qrcode/{platform}",
                methods=["POST"],
                endpoint=self.start_qrcode_login,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/login/qrcode/session/{session_id}",
                methods=["GET"],
                endpoint=self.poll_qrcode_login,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/login/qrcode/session/{session_id}",
                methods=["DELETE"],
                endpoint=self.cancel_qrcode_login,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters",
                methods=["GET"],
                endpoint=self.list_adapters,
                response_model=List[AdapterResponse],
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters",
                methods=["POST"],
                endpoint=self.create_adapter,
                response_model=AdapterResponse,
                status_code=status.HTTP_201_CREATED,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/{adapter_id}",
                methods=["GET"],
                endpoint=self.get_adapter,
                response_model=AdapterResponse,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/{adapter_id}",
                methods=["PUT"],
                endpoint=self.update_adapter,
                response_model=AdapterResponse,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/adapters/{adapter_id}",
                methods=["DELETE"],
                endpoint=self.delete_adapter,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["adapters"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_adapter_platforms(self, details: bool = False):
        """Return stable platform IDs for backwards compatibility."""
        try:
            if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
                logger.warning("Adapter manager not available for get_adapter_platforms")
                return []
            adapter_manager = self.lifecycle.adapter_manager
            if not details:
                return adapter_manager.get_adapter_types()
            return [
                {
                    "id": adapter_id,
                    "display_name": manifest.get("display_name") or adapter_id,
                    "description": manifest.get("description") or "",
                    "locales": manifest.get("locales") or {},
                    "icon": self._get_adapter_platform_icon(adapter_id),
                    "icon_dark": self._get_adapter_platform_icon(adapter_id, dark=True),
                    "login_method": manifest.get("login_method"),
                }
                for adapter_id in adapter_manager.get_adapter_types()
                for manifest in [adapter_manager.get_manifest(adapter_id)]
            ]
        except Exception as e:
            logger.error(f"Error getting adapter platforms: {e}")
            return []

    async def get_adapter_schema(self, platform: str):
        if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
            raise HTTPException(status_code=404, detail="Adapter manager not available")
        schema_fields = self.lifecycle.adapter_manager.get_schema(platform)
        if not schema_fields:
            raise HTTPException(
                status_code=404,
                detail=f"Schema not found for adapter platform: {platform}",
            )
        return schema_to_dict(schema_fields)

    @staticmethod
    def _qrcode_data_url(content: str) -> str:
        qr = qrcode.QRCode(border=2)
        qr.add_data(content)
        qr.make(fit=True)
        buffer = io.BytesIO()
        qr.make_image(image_factory=SvgPathImage).save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"

    async def start_qrcode_login(
        self,
        platform: str,
        payload: QRCodeLoginStartRequest,
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
            raise HTTPException(status_code=404, detail="Adapter manager not available")
        adapter_manager = self.lifecycle.adapter_manager
        manifest = adapter_manager.get_manifest(platform)
        if manifest.get("login_method") != "qrcode":
            raise HTTPException(
                status_code=400,
                detail=f"Adapter platform does not support QR-code login: {platform}",
            )
        adapter_cls = adapter_manager.get_adapter_class(platform)
        if not adapter_cls:
            raise HTTPException(status_code=404, detail="Adapter platform not found")

        now = time.monotonic()
        for old_id, old_session in list(self._qrcode_login_sessions.items()):
            if old_session.expires_at <= now:
                self._qrcode_login_sessions.pop(old_id, None)
                await old_session.handler.close()
        if len(self._qrcode_login_sessions) >= 20:
            raise HTTPException(status_code=429, detail="Too many QR-code login sessions")

        handler = adapter_cls.create_qrcode_login_handler(payload.config)
        if handler is None:
            raise HTTPException(
                status_code=500,
                detail=f"QR-code login handler is unavailable: {platform}",
            )
        try:
            result = await handler.start()
            if not result.qr_content:
                raise RuntimeError("QR-code login did not return QR content")
        except Exception as exc:
            await handler.close()
            logger.error(f"Failed to start QR-code login for {platform}: {exc}")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        session_id = secrets.token_urlsafe(24)
        expires_in = max(30, min(int(result.expires_in), 600))
        self._qrcode_login_sessions[session_id] = _QRCodeLoginSession(
            handler=handler,
            expires_at=time.monotonic() + expires_in,
            lock=asyncio.Lock(),
        )
        return {
            "session_id": session_id,
            "status": "pending",
            "qrcode_image": self._qrcode_data_url(result.qr_content),
            "poll_interval": max(1, int(result.poll_interval)),
            "expires_in": expires_in,
        }

    async def poll_qrcode_login(self, session_id: str):
        login_session = self._qrcode_login_sessions.get(session_id)
        if not login_session:
            raise HTTPException(status_code=404, detail="QR-code login session not found")
        if login_session.expires_at <= time.monotonic():
            self._qrcode_login_sessions.pop(session_id, None)
            await login_session.handler.close()
            return {
                "status": "expired",
                "config_patch": {},
                "message": "QR code expired",
            }

        async with login_session.lock:
            result = login_session.terminal_result
            if result is None:
                try:
                    result = await login_session.handler.poll()
                except Exception as exc:
                    logger.error(f"Failed to poll QR-code login: {exc}")
                    result = QRCodeLoginPollResult(status="error", message=str(exc))
                if result.status != "pending":
                    login_session.terminal_result = result
                    await login_session.handler.close()
            return {
                "status": result.status,
                "config_patch": result.config_patch,
                "message": result.message,
            }

    async def cancel_qrcode_login(self, session_id: str):
        login_session = self._qrcode_login_sessions.pop(session_id, None)
        if login_session:
            await login_session.handler.close()
        return None

    def _get_adapter_locales(self, platform: str) -> Dict[str, Dict[str, str]]:
        """Get locales dict from adapter manifest for the given platform."""
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            manifest = self.lifecycle.adapter_manager.get_manifest(platform)
            return manifest.get("locales") or {}
        return {}

    def _get_adapter_platform_display(self, platform: str) -> tuple[str, Dict[str, Dict[str, str]]]:
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            manifest = self.lifecycle.adapter_manager.get_manifest(platform)
            return manifest.get("display_name") or platform, manifest.get("locales") or {}
        return platform, {}

    def _get_adapter_platform_icon(self, platform: str, dark: bool = False) -> str | None:
        if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
            return None
        if not self.lifecycle.adapter_manager.get_icon_path(platform, dark=dark):
            return None
        suffix = "?dark=true" if dark else ""
        return f"/api/adapter-platforms/{quote(platform, safe='')}/icon{suffix}"

    def _adapter_response(self, info, status_value: str) -> AdapterResponse:
        platform_display_name, platform_locales = self._get_adapter_platform_display(info.platform)
        return AdapterResponse(
            id=info.adapter_id,
            name=info.name,
            platform=info.platform,
            status=status_value,
            description=info.description,
            config=info.config,
            locales=self._get_adapter_locales(info.platform),
            platform_display_name=platform_display_name,
            platform_locales=platform_locales,
            platform_icon=self._get_adapter_platform_icon(info.platform),
            platform_icon_dark=self._get_adapter_platform_icon(info.platform, dark=True),
        )

    async def get_adapter_platform_icon(self, platform: str, dark: bool = False):
        if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
            raise HTTPException(status_code=404, detail="Adapter manager not available")
        icon_path = self.lifecycle.adapter_manager.get_icon_path(platform, dark=dark)
        if not icon_path:
            raise HTTPException(status_code=404, detail="Adapter icon not found")
        return FileResponse(icon_path, headers={"Cache-Control": "no-cache"})

    async def list_adapters(self):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                adapters_info = adapter_mgr.get_adapters_info()
                running_adapters = set(adapter_mgr.get_adapters().keys())
                adapters: List[AdapterResponse] = []
                for info in adapters_info:
                    adapter_status = (
                        "active" if info.enabled and info.name in running_adapters else "inactive"
                    )
                    adapters.append(self._adapter_response(info, adapter_status))
                return adapters
            except Exception as e:
                logger.error(f"Error listing adapters from lifecycle: {e}")
        return list(self._adapters.values())

    async def create_adapter(self, payload: AdapterBase):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            name = payload.name
            platform = payload.platform
            if not name or not platform:
                raise HTTPException(status_code=400, detail="name and platform are required")
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                info = await adapter_mgr.create_adapter(
                    name=name,
                    platform=platform,
                    status=payload.status,
                    description=payload.description,
                    config=payload.config or {},
                )
                if not info:
                    raise HTTPException(status_code=500, detail="Failed to create adapter")
                running_adapters = set(adapter_mgr.get_adapters().keys())
                status_value = "active" if info.enabled and info.name in running_adapters else "inactive"
                return self._adapter_response(info, status_value)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error creating adapter: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        adapter_id = _generate_id()
        adapter = AdapterResponse(id=adapter_id, **payload.model_dump())
        self._adapters[adapter_id] = adapter
        return adapter

    async def get_adapter(self, adapter_id: str):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None) and getattr(self.lifecycle, "kira_config", None):
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                info = adapter_mgr.get_adapter_info(adapter_id)
                if not info:
                    raise HTTPException(status_code=404, detail="Adapter not found")
                running_adapters = set(adapter_mgr.get_adapters().keys())
                adapter_status = "active" if info.enabled and info.name in running_adapters else "inactive"
                return self._adapter_response(info, adapter_status)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error getting adapter {adapter_id} from lifecycle: {e}")
        adapter = self._adapters.get(adapter_id)
        if not adapter:
            raise HTTPException(status_code=404, detail="Adapter not found")
        return adapter

    async def update_adapter(self, adapter_id: str, payload: AdapterBase):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                info = await adapter_mgr.update_adapter(
                    adapter_id=adapter_id,
                    name=payload.name,
                    platform=payload.platform,
                    status=payload.status,
                    description=payload.description,
                    config=payload.config or {},
                )
                if not info:
                    raise HTTPException(status_code=404, detail="Adapter not found")
                running_adapters = set(adapter_mgr.get_adapters().keys())
                status_value = "active" if info.enabled and info.name in running_adapters else "inactive"
                return self._adapter_response(info, status_value)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Error updating adapter {adapter_id}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
        adapter = self._adapters.get(adapter_id)
        if not adapter:
            raise HTTPException(status_code=404, detail="Adapter not found")
        updated = adapter.model_copy(update=payload.model_dump())
        self._adapters[adapter_id] = updated
        return updated

    async def delete_adapter(self, adapter_id: str):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            adapter_mgr = self.lifecycle.adapter_manager
            try:
                deleted = await adapter_mgr.delete_adapter(adapter_id)
            except Exception as e:
                logger.error(f"Error deleting adapter {adapter_id}: {e}")
                raise HTTPException(status_code=500, detail=str(e))
            if not deleted:
                raise HTTPException(status_code=404, detail="Adapter not found")
            return None
        if adapter_id not in self._adapters:
            raise HTTPException(status_code=404, detail="Adapter not found")
        self._adapters.pop(adapter_id, None)
        return None
