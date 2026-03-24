from typing import Any, Dict, List, Optional

from fastapi import Depends, HTTPException

from core.logging_manager import get_logger
from webui.models import PluginConfigUpdateRequest, PluginItem
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

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
            schema_dict: Dict[str, Dict[str, Any]] = {}
            for field in schema_fields:
                key = getattr(field, "key", None)
                if not key:
                    continue
                try:
                    field_dict = field.to_dict()
                except Exception:
                    continue
                schema_dict[str(key)] = field_dict
            config = plugin_manager.get_plugin_config(plugin_id)
            return {"schema": schema_dict, "config": config}
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
            schema_dict: Dict[str, Dict[str, Any]] = {}
            for field in schema_fields:
                key = getattr(field, "key", None)
                if not key:
                    continue
                try:
                    field_dict = field.to_dict()
                except Exception:
                    continue
                schema_dict[str(key)] = field_dict
            return {"schema": schema_dict, "config": updated_config}
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
