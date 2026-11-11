from fastapi import Depends, HTTPException

from core.agent.subagent_presets import DuplicatePresetNameError, SubAgentPreset
from core.logging_manager import get_logger
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class SubAgentsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/subagents/presets",
                methods=["GET"],
                endpoint=self.list_presets,
                tags=["subagents"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/subagents/presets",
                methods=["POST"],
                endpoint=self.create_preset,
                status_code=201,
                tags=["subagents"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/subagents/presets/{preset_id}",
                methods=["PUT"],
                endpoint=self.update_preset,
                tags=["subagents"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/subagents/presets/{preset_id}",
                methods=["DELETE"],
                endpoint=self.delete_preset,
                status_code=204,
                tags=["subagents"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    def _store(self):
        manager = getattr(self.lifecycle, "subagent_manager", None)
        if manager is None:
            raise HTTPException(status_code=503, detail="Subagent manager unavailable")
        return manager.presets

    async def list_presets(self):
        return {"presets": self._store().list()}

    async def create_preset(self, payload: SubAgentPreset):
        return await self._save(payload)

    async def update_preset(self, preset_id: str, payload: SubAgentPreset):
        return await self._save(payload, preset_id)

    async def _save(self, payload: SubAgentPreset, preset_id: str | None = None):
        try:
            return await self._store().save(payload, preset_id)
        except DuplicatePresetNameError as exc:
            raise HTTPException(
                status_code=409,
                detail=str(exc),
            ) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Subagent preset not found") from exc
        except OSError as exc:
            logger.exception("Failed to save subagent preset %s", preset_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    async def delete_preset(self, preset_id: str):
        try:
            await self._store().delete(preset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Subagent preset not found") from exc
        except OSError as exc:
            logger.exception("Failed to delete subagent preset %s", preset_id)
            raise HTTPException(status_code=500, detail=str(exc)) from exc
