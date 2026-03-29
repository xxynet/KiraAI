import json
from typing import Dict, List

from fastapi import Depends, HTTPException

from core.logging_manager import get_logger
from webui.models import McpServerConfigUpdateRequest, McpServerCreateRequest, McpServerItem
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class McpRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/mcp-servers",
                methods=["GET"],
                endpoint=self.list_mcp_servers,
                response_model=List[McpServerItem],
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/mcp-servers",
                methods=["POST"],
                endpoint=self.create_mcp_server,
                response_model=McpServerItem,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/mcp-servers/{server_name}/enabled",
                methods=["POST"],
                endpoint=self.set_mcp_server_enabled,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/mcp-servers/{server_name}/config",
                methods=["GET"],
                endpoint=self.get_mcp_server_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/mcp-servers/{server_name}/config",
                methods=["PUT"],
                endpoint=self.update_mcp_server_config,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/mcp-servers/{server_name}",
                methods=["DELETE"],
                endpoint=self.delete_mcp_server,
                tags=["plugins"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def list_mcp_servers(self):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            return []
        try:
            manager = self.lifecycle.mcp_manager
            items: List[McpServerItem] = []
            for server in manager.servers:
                items.append(
                    McpServerItem(
                        id=str(server.name),
                        type=str(server.type),
                        name=str(server.name),
                        description=str(server.description or ""),
                        enabled=bool(server.enabled),
                        url=str(server.url or ""),
                        tools_count=len(server.tools),
                    )
                )
            return items
        except Exception as e:
            logger.error(f"Failed to list MCP servers from MCPManager: {e}")
            raise HTTPException(status_code=500, detail="Failed to list MCP servers")

    async def create_mcp_server(self, payload: McpServerCreateRequest):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            raise HTTPException(status_code=503, detail="MCP manager not available")
        try:
            raw_config = payload.config
            if isinstance(raw_config, str):
                try:
                    config_json = json.loads(raw_config)
                except json.JSONDecodeError:
                    raise HTTPException(status_code=400, detail="Invalid MCP config JSON")
            elif isinstance(raw_config, dict):
                config_json = raw_config
            else:
                raise HTTPException(status_code=400, detail="Invalid MCP config JSON")

            manager = self.lifecycle.mcp_manager
            server = manager.add_or_update_server_from_config(
                name=payload.name,
                description=payload.description or "",
                config_json=config_json,
            )
            try:
                await manager.list_tools(server)
            except Exception:
                pass
            return McpServerItem(
                id=str(server.name),
                type=str(server.type),
                name=str(server.name),
                description=str(server.description or ""),
                enabled=bool(server.enabled),
                url=str(server.url or ""),
                tools_count=len(server.tools),
            )
        except HTTPException:
            raise
        except ValueError as e:
            logger.error(f"Failed to create MCP server {payload.name}: {e}")
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to create MCP server {payload.name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to create MCP server")

    async def set_mcp_server_enabled(self, server_name: str, payload: Dict):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            raise HTTPException(status_code=503, detail="MCP manager not available")
        try:
            enabled = bool(payload.get("enabled"))
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid payload")
        try:
            manager = self.lifecycle.mcp_manager
            if enabled:
                await manager.enable_server(server_name)
            else:
                manager.disable_server(server_name)
            return {"server_name": server_name, "enabled": enabled}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to set MCP server enabled state for {server_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to update MCP server state")

    async def get_mcp_server_config(self, server_name: str):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            raise HTTPException(status_code=503, detail="MCP manager not available")
        try:
            manager = self.lifecycle.mcp_manager
            editor_cfg = manager.get_server_config_for_editor(server_name)
            description = ""
            for server in manager.servers:
                if server.name == server_name:
                    description = server.description or ""
                    break
            return {"name": server_name, "description": description, "config": editor_cfg}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to load MCP config file for {server_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to load MCP config file")

    async def update_mcp_server_config(
        self,
        server_name: str,
        payload: McpServerConfigUpdateRequest,
    ):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            raise HTTPException(status_code=503, detail="MCP manager not available")
        try:
            try:
                editor_config = (
                    json.loads(payload.config)
                    if isinstance(payload.config, str)
                    else payload.config
                )
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid MCP config JSON")
            manager = self.lifecycle.mcp_manager
            manager.update_server_from_editor(
                name=server_name,
                description=payload.name or "",
                editor_config=editor_config,
            )
            return {"ok": True}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to update MCP config file for {server_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to save MCP config file")

    async def delete_mcp_server(self, server_name: str):
        if not self.lifecycle or not getattr(self.lifecycle, "mcp_manager", None):
            raise HTTPException(status_code=503, detail="MCP manager not available")
        try:
            self.lifecycle.mcp_manager.delete_server(server_name)
            return {"ok": True}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            logger.error(f"Failed to delete MCP server {server_name}: {e}")
            raise HTTPException(status_code=500, detail="Failed to delete MCP server")
