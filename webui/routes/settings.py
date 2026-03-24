from fastapi import Depends

from webui.models import SettingsRequest, SettingsResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes


class SettingsRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._settings = SettingsResponse()

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/settings",
                methods=["GET"],
                endpoint=self.get_settings,
                response_model=SettingsResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings",
                methods=["PUT"],
                endpoint=self.update_settings,
                response_model=SettingsResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_settings(self):
        return self._settings

    async def update_settings(self, payload: SettingsRequest):
        self._settings = SettingsResponse(**payload.model_dump(), updated_by="admin")
        return self._settings
