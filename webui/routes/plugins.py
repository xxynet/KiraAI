import shutil
from typing import Any, Dict, List, Optional

from fastapi import Depends, File, HTTPException, UploadFile

from core.logging_manager import get_logger
from core.plugin.plugin_installer import install_from_github, install_from_zip, install_requirements
from webui.models import PluginConfigUpdateRequest, PluginInstallGithubRequest, PluginInstallResult, PluginItem
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
        ]

    async def list_plugins(self):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            return []
        try:
            plugin_manager = self.lifecycle.plugin_manager
            registered = plugin_manager.get_registered_plugins()
            items: List[PluginItem] = []
            for plugin_id, _ in registered.items():
                manifest = plugin_manager.get_plugin_manifest(plugin_id) or {}
                display_name = manifest.get("display_name") or plugin_id
                version = str(manifest.get("version") or "")
                author = str(manifest.get("author") or "")
                desc = str(manifest.get("description") or "")
                repo = manifest.get("repo")
                enabled = plugin_manager.is_plugin_enabled(plugin_id)
                items.append(
                    PluginItem(
                        id=str(plugin_id),
                        name=str(display_name),
                        version=version,
                        author=author,
                        description=desc,
                        repo=repo if isinstance(repo, str) and repo else None,
                        enabled=enabled,
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
            registered = plugin_manager.get_registered_plugins()
            if plugin_id not in registered:
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
            registered = plugin_manager.get_registered_plugins()
            if plugin_id not in registered:
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
            registered = plugin_manager.get_registered_plugins()
            if plugin_id not in registered:
                raise HTTPException(status_code=404, detail="Plugin not found")
            await plugin_manager.set_plugin_enabled(plugin_id, enabled)
            return {"plugin_id": plugin_id, "enabled": enabled}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set plugin enabled state for {plugin_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to update plugin state")

    async def delete_plugin(self, plugin_id: str):
        if not self.lifecycle or not getattr(self.lifecycle, "plugin_manager", None):
            raise HTTPException(status_code=503, detail="Plugin manager not available")

        plugin_manager = self.lifecycle.plugin_manager

        if plugin_id not in plugin_manager.get_registered_plugins():
            raise HTTPException(status_code=404, detail="Plugin not found")

        # Only user-installed plugins (under plugin_dir) can be deleted
        plugin_dir = plugin_manager.plugin_dir / plugin_id
        if not plugin_dir.exists():
            raise HTTPException(status_code=400, detail="Built-in plugins cannot be deleted")

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
        return PluginInstallResult(
            id=plugin_id,
            name=str(manifest.get("display_name") or plugin_id),
            version=str(manifest.get("version") or ""),
            author=str(manifest.get("author") or ""),
            description=str(manifest.get("description") or ""),
            repo=manifest.get("repo") if isinstance(manifest.get("repo"), str) else None,
            enabled=plugin_manager.is_plugin_enabled(plugin_id),
            warnings=warnings,
        )
