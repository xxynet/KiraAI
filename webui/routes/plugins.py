import shutil
import time
import json
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import Depends, File, HTTPException, Query, UploadFile

from core.plugin.plugin_registry import PluginManager, PLUGIN_CONFIG_DIR, PLUGIN_DATA_DIR
from core.logging_manager import get_logger
from core.plugin.plugin_installer import install_from_github, install_from_zip, install_requirements
from core.utils.path_utils import get_data_path
from webui.models import (
    PluginConfigUpdateRequest, PluginInstallGithubRequest, PluginInstallResult, PluginItem,
    PluginStoreItemResponse, PluginStoreFetchRequest,
    PluginStoreSourceItem, PluginStoreSourceCreateRequest, PluginStoreSourceUpdateRequest,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import schema_to_dict

logger = get_logger("webui", "blue")


class PluginsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/plugins",
                methods=["GET"],
                endpoint=self.list_plugins,
                response_model=List[PluginItem],
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/config",
                methods=["GET"],
                endpoint=self.get_plugin_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/config",
                methods=["PUT"],
                endpoint=self.update_plugin_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/enabled",
                methods=["POST"],
                endpoint=self.set_plugin_enabled,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}/reload",
                methods=["POST"],
                endpoint=self.reload_plugin,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/{plugin_id}",
                methods=["DELETE"],
                endpoint=self.delete_plugin,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/github",
                methods=["POST"],
                endpoint=self.install_from_github,
                response_model=PluginInstallResult,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/plugins/install/upload",
                methods=["POST"],
                endpoint=self.install_from_upload,
                response_model=PluginInstallResult,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
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

    async def list_plugins(self):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            return []
        try:
            plugin_manager = self.lifecycle.plugin_manager
            items: List[PluginItem] = []
            for info in plugin_manager.list_plugins():
                if info.hidden:
                    continue
                items.append(
                    PluginItem(
                        id=info.plugin_id,
                        name=info.display_name,
                        version=info.version,
                        author=info.author,
                        description=info.description,
                        repo=info.repo,
                        enabled=plugin_manager.is_plugin_enabled(info.plugin_id),
                        builtin=info.builtin,
                        uninstallable=info.uninstallable,
                        locales=info.locales,
                        tags=info.tags,
                        core_version=info.core_version,
                        error=info.error,
                    )
                )
            return items
        except Exception as e:
            logger.error(f"Failed to list plugins: {e}")
            raise HTTPException(status_code=500, detail="Failed to list plugins")

    async def get_plugin_config(self, plugin_id: str):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            schema_fields = plugin_manager.get_plugin_schema(plugin_id) or []
            config = plugin_manager.get_plugin_config(plugin_id)
            return {"schema": schema_to_dict(schema_fields), "config": config}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to get config for plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to load plugin config")

    async def update_plugin_config(
        self,
        plugin_id: str,
        payload: PluginConfigUpdateRequest,
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            updated_config = await plugin_manager.update_plugin_config(plugin_id, payload.config or {})
            schema_fields = plugin_manager.get_plugin_schema(plugin_id) or []
            return {"schema": schema_to_dict(schema_fields), "config": updated_config}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update config for plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save plugin config")

    async def set_plugin_enabled(self, plugin_id: str, payload: Dict):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            enabled = bool(payload.get("enabled"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            if plugin_id in plugin_manager.get_plugin_load_errors():
                raise HTTPException(status_code=400, detail="Cannot enable a plugin that failed to load")
            await plugin_manager.set_plugin_enabled(plugin_id, enabled)
            return {"plugin_id": plugin_id, "enabled": enabled}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set plugin enabled state for {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to update plugin state")

    async def reload_plugin(self, plugin_id: str):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")
        try:
            plugin_manager = self.lifecycle.plugin_manager
            if not plugin_manager.has_plugin(plugin_id):
                raise HTTPException(status_code=404, detail="Plugin not found")
            if plugin_manager.is_builtin_plugin(plugin_id):
                raise HTTPException(status_code=400, detail="Built-in plugins cannot be reloaded")
            await plugin_manager.reload(plugin_id)
            # Check if the plugin reloaded successfully
            if plugin_id in plugin_manager.get_registered_plugins():
                return {"plugin_id": plugin_id, "reloaded": True}
            # Plugin failed to reload — get the error
            errors = plugin_manager.get_plugin_load_errors()
            error_msg = errors.get(plugin_id, {}).get("error", "Unknown error")
            return {"plugin_id": plugin_id, "reloaded": False, "error": error_msg}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to reload plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to reload plugin: {e}")

    async def delete_plugin(
        self,
        plugin_id: str,
        delete_config: bool = Query(False),
        delete_data: bool = Query(False),
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager

        if not plugin_manager.has_plugin(plugin_id):
            raise HTTPException(status_code=404, detail="Plugin not found")

        if not plugin_manager.is_plugin_uninstallable(plugin_id):
            raise HTTPException(status_code=400, detail="This built-in plugin cannot be deleted")

        plugin_dir = plugin_manager.get_plugin_module_path(plugin_id)
        if not plugin_dir:
            # Failed plugins may not have a registered path; try the plugins directory
            plugin_dir = plugin_manager.plugin_dir / plugin_id
            if not plugin_dir.exists():
                raise HTTPException(status_code=500, detail="Could not resolve plugin path")

        try:
            await plugin_manager.uninstall_plugin(plugin_id)
        except Exception as e:
            logger.error(f"Failed to uninstall plugin {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to uninstall plugin: {e}")

        try:
            shutil.rmtree(plugin_dir)
        except Exception as e:
            logger.error(f"Failed to delete plugin directory {plugin_dir}: {e}")
            raise HTTPException(status_code=500, detail=f"Plugin unregistered but directory deletion failed: {e}")

        if delete_config:
            config_file = PLUGIN_CONFIG_DIR / f"{plugin_id}.json"
            try:
                if config_file.exists():
                    config_file.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete plugin config {config_file}: {e}")

        if delete_data:
            data_dir = PLUGIN_DATA_DIR / plugin_id
            try:
                if data_dir.exists():
                    shutil.rmtree(data_dir)
            except Exception as e:
                logger.warning(f"Failed to delete plugin data {data_dir}: {e}")

        return {"plugin_id": plugin_id, "deleted": True}

    async def install_from_github(self, payload: PluginInstallGithubRequest) -> PluginInstallResult:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager

        try:
            plugin_dir = await install_from_github(
                payload.repo_url,
                plugin_manager.plugin_dir,
                proxy=payload.proxy,
                gh_proxy=payload.gh_proxy,
            )
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        except ConnectionError as e:
            raise HTTPException(status_code=422, detail=str(e))

        warnings = await install_requirements(plugin_dir)

        plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
        if not plugin_id:
            raise HTTPException(status_code=500, detail="Plugin files were installed but failed to load")

        return self._build_install_result(plugin_manager, plugin_id, warnings)

    async def install_from_upload(self, file: UploadFile = File(...)) -> PluginInstallResult:
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are accepted")

        plugin_manager = self.lifecycle.plugin_manager

        zip_bytes = await file.read()
        try:
            plugin_dir = await install_from_zip(zip_bytes, plugin_manager.plugin_dir)
        except (ValueError, IOError) as e:
            raise HTTPException(status_code=422, detail=str(e))

        warnings = await install_requirements(plugin_dir)

        plugin_id = await plugin_manager.load_plugin_from_dir(plugin_dir)
        if not plugin_id:
            raise HTTPException(status_code=500, detail="Plugin files were installed but failed to load")

        return self._build_install_result(plugin_manager, plugin_id, warnings)

    @staticmethod
    def _build_install_result(plugin_manager, plugin_id: str, warnings: List[str]) -> PluginInstallResult:
        manifest = plugin_manager.get_plugin_manifest(plugin_id) or {}
        tags = manifest.get("tags") or []
        return PluginInstallResult(
            id=plugin_id,
            name=str(manifest.get("display_name") or plugin_id),
            version=str(manifest.get("version") or ""),
            author=str(manifest.get("author") or ""),
            description=str(manifest.get("description") or ""),
            repo=manifest.get("repo") if isinstance(manifest.get("repo"), str) else None,
            enabled=plugin_manager.is_plugin_enabled(plugin_id),
            tags=[str(t) for t in tags if t],
            warnings=warnings,
        )

    async def fetch_plugin_store(self, payload: PluginStoreFetchRequest) -> List[PluginStoreItemResponse]:
        url: Optional[str] = payload.url
        source_id: Optional[str] = None

        # If source_id is provided, look up URL from DB
        if payload.source_id and self.lifecycle and self.lifecycle.db_service:
            source = await self.lifecycle.db_service.get_plugin_store_source(payload.source_id)
            if not source:
                raise HTTPException(status_code=404, detail="Plugin store source not found")
            url = source["url"]
            source_id = payload.source_id

        if not url:
            raise HTTPException(status_code=400, detail="Either url or source_id is required")

        try:
            raw_data = await PluginManager.fetch_plugin_store_data(url)
            items = self._extract_plugins(raw_data)

            # Update cache on force refresh
            if payload.force_refresh and source_id and self.lifecycle and self.lifecycle.db_service:
                now = int(time.time())
                cache_file = await self._fetch_and_cache(
                    source_id, url, existing_filename=source.get("cache_file") if source_id else None,
                )
                if cache_file:
                    await self.lifecycle.db_service.update_plugin_store_source(
                        source_id, cache_file=cache_file, updated_at=now,
                    )
            result: List[PluginStoreItemResponse] = []
            for item in items:
                tags = item.get("tags") or []
                result.append(PluginStoreItemResponse(
                    id=str(item.get("plugin_id", "")),
                    name=str(item.get("display_name", "")),
                    version=str(item.get("version") or ""),
                    author=str(item.get("author", "")),
                    description=str(item.get("description", "")),
                    category=item.get("category"),
                    repo=item.get("repo"),
                    locales=item.get("locales") or {},
                    tags=[str(t) for t in tags if t],
                ))
            return result
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"Failed to fetch plugin store data: {e}")

    @staticmethod
    def _extract_plugins(raw_data: Any) -> List[Dict[str, Any]]:
        """Extract and normalize plugin entries from raw store JSON.

        Supports the standard format ``{\"plugins\": {\"<id>\": {...}, ...}}``
        as well as a plain array of plugin objects.

        Standard schema fields prioritized:
          plugin_id, display_name, version, author, description

        Extra useful fields (if present): category, repo, name, id

        NOTE: github_data is intentionally NOT parsed.
        """
        raw_plugins: Any = None
        if isinstance(raw_data, dict):
            raw_plugins = raw_data.get("plugins", [])
        elif isinstance(raw_data, list):
            raw_plugins = raw_data

        if not isinstance(raw_plugins, (dict, list)):
            return []

        if isinstance(raw_plugins, dict):
            plugin_list = list(raw_plugins.values())
        else:
            plugin_list = list(raw_plugins)

        result: List[Dict[str, Any]] = []
        for raw in plugin_list:
            if not isinstance(raw, dict):
                continue

            plugin_id = raw.get("plugin_id") or raw.get("id") or raw.get("name", "")
            display_name = raw.get("display_name") or raw.get("name") or str(plugin_id)
            version = raw.get("version")
            author = raw.get("author", "")
            description = raw.get("description", "")
            category = raw.get("category")
            repo = raw.get("repo") or raw.get("repo_url")

            locales = raw.get("locales")

            item: Dict[str, Any] = {
                "plugin_id": str(plugin_id),
                "display_name": str(display_name),
                "version": str(version) if version else None,
                "author": str(author),
                "description": str(description),
                "category": str(category) if category else None,
                "repo": str(repo) if repo else None,
                "locales": locales if isinstance(locales, dict) else {},
            }

            if "id" in raw and raw["id"] is not None:
                item["id"] = raw["id"]

            result.append(item)

        return result

    # ---- Plugin Store Source CRUD ----

    async def list_plugin_sources(self) -> List[PluginStoreSourceItem]:
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")
        sources = await self.lifecycle.db_service.list_plugin_store_sources()
        return [
            PluginStoreSourceItem(
                id=s["id"],
                name=s["name"],
                url=s["url"],
                cache_file=s.get("cache_file"),
                updated_at=s.get("updated_at", 0),
                is_current=s.get("is_current", False),
                created_at=s.get("created_at", 0),
            )
            for s in sources
        ]

    async def create_plugin_source(self, payload: PluginStoreSourceCreateRequest) -> PluginStoreSourceItem:
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        source_id = uuid4().hex
        now = int(time.time())

        # Save to DB
        await db.add_plugin_store_source(
            source_id=source_id,
            name=payload.name,
            url=payload.url,
            updated_at=now,
            is_current=False,
            created_at=now,
        )

        # Fetch and cache plugins
        cache_file = await self._fetch_and_cache(source_id, payload.url)
        if cache_file:
            await db.update_plugin_store_source(source_id, cache_file=cache_file, updated_at=now)

        created = await db.get_plugin_store_source(source_id)
        return PluginStoreSourceItem(
            id=created["id"],
            name=created["name"],
            url=created["url"],
            cache_file=created.get("cache_file"),
            updated_at=created.get("updated_at", 0),
            is_current=created.get("is_current", False),
            created_at=created.get("created_at", 0),
        )

    async def set_current_source(self, source_id: str):
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        source = await db.get_plugin_store_source(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Plugin store source not found")

        # Set this source as current
        await db.update_plugin_store_source(source_id, is_current=True)

        # Refresh cache if stale
        now = int(time.time())
        updated_at = source.get("updated_at", 0)
        if now - updated_at > 600:  # 10 minutes
            cache_file = await self._fetch_and_cache(
                source_id, source["url"], existing_filename=source.get("cache_file"),
            )
            if cache_file:
                await db.update_plugin_store_source(source_id, cache_file=cache_file, updated_at=now)

        return {"success": True}

    async def delete_plugin_source(self, source_id: str):
        if not self.lifecycle or not self.lifecycle.db_service:
            raise HTTPException(status_code=503, detail="Database service not available")

        db = self.lifecycle.db_service
        source = await db.get_plugin_store_source(source_id)
        if not source:
            raise HTTPException(status_code=404, detail="Plugin store source not found")

        # Delete cache file if exists
        cache_file = source.get("cache_file")
        if cache_file:
            plugin_src_dir = get_data_path() / "plugin_src"
            cache_path = plugin_src_dir / cache_file
            try:
                if cache_path.exists():
                    cache_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to delete cache file {cache_path}: {e}")

        await db.delete_plugin_store_source(source_id)
        return {"success": True}

    @staticmethod
    async def _fetch_and_cache(source_id: str, url: str, existing_filename: Optional[str] = None) -> Optional[str]:
        """Fetch plugin store data, save complete raw JSON to disk. Return cache filename or None.

        If *existing_filename* is provided and its file exists on disk, the fetched
        data will **overwrite** that file instead of creating a new one, so no
        orphaned cache files are left behind.
        """
        try:
            raw_data = await PluginManager.fetch_plugin_store_data(url)
            plugin_src_dir = get_data_path() / "plugin_src"
            plugin_src_dir.mkdir(parents=True, exist_ok=True)
            # Reuse the existing file when it is already on disk
            if existing_filename and (plugin_src_dir / existing_filename).exists():
                filename = existing_filename
            else:
                filename = f"plugins_{uuid4().hex}.json"
            cache_path = plugin_src_dir / filename
            cache_path.write_text(json.dumps(raw_data, ensure_ascii=False, indent=2), encoding="utf-8")
            return filename
        except Exception as e:
            logger.warning(f"Failed to fetch/cache plugin store data from {url}: {e}")
            return None
