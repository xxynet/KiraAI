import time
from dataclasses import asdict
from typing import List, Optional
from uuid import uuid4

from fastapi import Depends, HTTPException, Response

from core.plugin.store import CACHE_TTL_SECONDS, PluginStore, StoreSource, extract_plugins
from webui.models import (
    PluginStoreFetchRequest,
    PluginStoreItemResponse,
    PluginStoreSourceCreateRequest,
    PluginStoreSourceItem,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes


class PluginStoreRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/plugin-store/fetch",
                methods=["POST"],
                endpoint=self.fetch_plugin_store,
                response_model=List[PluginStoreItemResponse],
                tags=["plugin-store"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugin-store/sources",
                methods=["GET"],
                endpoint=self.list_plugin_sources,
                response_model=List[PluginStoreSourceItem],
                tags=["plugin-store"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugin-store/sources",
                methods=["POST"],
                endpoint=self.create_plugin_source,
                response_model=PluginStoreSourceItem,
                tags=["plugin-store"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugin-store/sources/{source_id}/current",
                methods=["POST"],
                endpoint=self.set_current_source,
                tags=["plugin-store"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugin-store/sources/{source_id}",
                methods=["DELETE"],
                endpoint=self.delete_plugin_source,
                tags=["plugin-store"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def fetch_plugin_store(
        self, payload: PluginStoreFetchRequest, response: Response,
    ) -> List[PluginStoreItemResponse]:
        source: Optional[StoreSource] = StoreSource(url=payload.url) if payload.url else None

        # If source_id is provided, look up URL from DB
        if payload.source_id and self.lifecycle and self.lifecycle.db_service:
            record = await self.lifecycle.db_service.get_plugin_store_source(payload.source_id)
            if not record:
                raise HTTPException(status_code=404, detail="Plugin store source not found")
            source = StoreSource.from_record(record)

        if source is None or not source.url:
            raise HTTPException(status_code=400, detail="Either url or source_id is required")

        try:
            db_service = getattr(self.lifecycle, "db_service", None) if self.lifecycle else None
            fetched = await PluginStore(source).fetch(
                force_refresh=payload.force_refresh,
                persist_cache=bool(source.id and db_service),
                allow_cache_fallback=True,
            )
            if fetched.cache_file is not None:
                await db_service.update_plugin_store_source(
                    source.id, cache_file=fetched.cache_file, updated_at=fetched.updated_at,
                )
            if fetched.fetch_error is not None:
                response.headers["X-Plugin-Store-Cache-Fallback"] = "true"
                response.headers["X-Plugin-Store-Cache-Fallback-Status"] = str(
                    self._plugin_store_error_status(fetched.fetch_error)
                )

            return extract_plugins(fetched.data)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to fetch plugin store data: {e}")

    @staticmethod
    def _plugin_store_error_status(error: Exception) -> int:
        """Return an HTTP status from a store error, or the API's validation status."""
        status_code = getattr(error, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        error_response = getattr(error, "response", None)
        status_code = getattr(error_response, "status_code", None)
        if isinstance(status_code, int):
            return status_code

        return 422

    # ---- Plugin Store Source CRUD ----

    async def list_plugin_sources(self) -> List[PluginStoreSourceItem]:
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")
        sources = await self.lifecycle.db_service.list_plugin_store_sources()
        return [PluginStoreSourceItem(**asdict(StoreSource.from_record(record))) for record in sources]

    async def create_plugin_source(self, payload: PluginStoreSourceCreateRequest) -> PluginStoreSourceItem:
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        source_id = uuid4().hex
        now = int(time.time())

        source = StoreSource(
            id=source_id, name=payload.name, url=payload.url, updated_at=now, created_at=now,
        )

        # Save to DB
        await db.add_plugin_store_source(
            source_id=source.id,
            name=source.name,
            url=source.url,
            updated_at=source.updated_at,
            is_current=source.is_current,
            created_at=source.created_at,
        )

        cache_file = await PluginStore(source).refresh_cache()
        if cache_file:
            await db.update_plugin_store_source(source_id, cache_file=cache_file, updated_at=now)

        created = await db.get_plugin_store_source(source_id)
        return PluginStoreSourceItem(**asdict(StoreSource.from_record(created)))

    async def set_current_source(self, source_id: str):
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        record = await db.get_plugin_store_source(source_id)
        if not record:
            raise HTTPException(status_code=404, detail="Plugin store source not found")

        source = StoreSource.from_record(record)

        # Set this source as current
        await db.update_plugin_store_source(source_id, is_current=True)

        # Refresh cache if stale
        now = int(time.time())
        updated_at = source.updated_at
        if now - updated_at > CACHE_TTL_SECONDS:
            cache_file = await PluginStore(source).refresh_cache()
            if cache_file:
                await db.update_plugin_store_source(source_id, cache_file=cache_file, updated_at=now)

        return {"success": True}

    async def delete_plugin_source(self, source_id: str):
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        record = await db.get_plugin_store_source(source_id)
        if not record:
            raise HTTPException(status_code=404, detail="Plugin store source not found")

        await PluginStore(StoreSource.from_record(record)).delete_cache()

        await db.delete_plugin_store_source(source_id)
        return {"success": True}
