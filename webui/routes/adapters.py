from typing import Dict, List

from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from webui.models import AdapterBase, AdapterResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _generate_id

logger = get_logger("webui", "blue")


class AdaptersRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._adapters: Dict[str, AdapterResponse] = {}

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
                path="/api/adapters/schema/{platform}",
                methods=["GET"],
                endpoint=self.get_adapter_schema,
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

    async def get_adapter_platforms(self):
        try:
            if not self.lifecycle or not getattr(self.lifecycle, "adapter_manager", None):
                logger.warning("Adapter manager not available for get_adapter_platforms")
                return []
            return self.lifecycle.adapter_manager.get_adapter_types()
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
        schema_dict: Dict[str, Dict] = {}
        for field in schema_fields:
            key = getattr(field, "key", None)
            if not key:
                continue
            schema_dict[key] = field.to_dict()
        return schema_dict

    async def list_adapters(self):
        if self.lifecycle and getattr(self.lifecycle, "adapter_manager", None):
            try:
                adapter_mgr = self.lifecycle.adapter_manager
                adapter_infos = adapter_mgr.get_adapter_infos()
                running_adapters = set(adapter_mgr.get_adapters().keys())
                adapters: List[AdapterResponse] = []
                for info in adapter_infos:
                    adapter_status = (
                        "active" if info.enabled and info.name in running_adapters else "inactive"
                    )
                    adapters.append(
                        AdapterResponse(
                            id=info.adapter_id,
                            name=info.name,
                            platform=info.platform,
                            status=adapter_status,
                            description=info.description,
                            config=info.config,
                        )
                    )
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
                return AdapterResponse(
                    id=info.adapter_id,
                    name=info.name,
                    platform=info.platform,
                    status=status_value,
                    description=info.description,
                    config=info.config,
                )
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
                return AdapterResponse(
                    id=adapter_id,
                    name=info.name,
                    platform=info.platform,
                    status=adapter_status,
                    description=info.description,
                    config=info.config,
                )
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
                return AdapterResponse(
                    id=info.adapter_id,
                    name=info.name,
                    platform=info.platform,
                    status=status_value,
                    description=info.description,
                    config=info.config,
                )
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
