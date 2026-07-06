from typing import Dict, List, Any

from fastapi import Depends, HTTPException

from core.logging_manager import get_logger
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class ScopeRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/scope",
                methods=["GET"],
                endpoint=self.get_scope,
                tags=["scope"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/scope",
                methods=["PUT"],
                endpoint=self.update_scope,
                tags=["scope"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_scope(self):
        """Return all scope configs, sessions, and resource lists."""
        if not self.lifecycle:
            raise HTTPException(status_code=503, detail="Lifecycle not available")

        # Gather MCP scopes: {server_id: {"allow": [...]} or {"deny": [...]}}
        mcp_scopes: Dict[str, Any] = {}
        mcp_servers: List[Dict[str, Any]] = []
        if self.lifecycle.mcp_manager:
            mcp_scopes = dict(self.lifecycle.mcp_manager.mcp_config.get("_scope", {}))
            for server in self.lifecycle.mcp_manager.servers:
                if server.enabled:
                    mcp_servers.append({
                        "id": server.id,
                        "name": server.name,
                        "enabled": True,
                    })

        # Gather skills scopes: {skill_name: {"allow": [...]} or {"deny": [...]}}
        skill_scopes: Dict[str, Any] = {}
        skills: List[Dict[str, Any]] = []
        if self.lifecycle.skills_manager:
            skill_scopes = dict(self.lifecycle.skills_manager._raw_config.get("_scope", {}))
            for skill in self.lifecycle.skills_manager.skills_info:
                if skill.enabled:
                    skills.append({
                        "name": skill.name,
                        "enabled": True,
                    })

        # Gather sessions
        sessions: List[Dict[str, Any]] = []
        if self.lifecycle.session_manager and self.lifecycle.session_manager.chat_memory:
            for session_key, session_meta in self.lifecycle.session_manager.chat_memory.items():
                parts = session_key.split(":")
                if len(parts) < 3:
                    continue
                adapter_name = parts[0]
                session_type = parts[1]
                session_id = ":".join(parts[2:])
                title = session_meta.get("title", "")
                sessions.append({
                    "id": session_key,
                    "adapter": adapter_name,
                    "type": session_type,
                    "session_id": session_id,
                    "title": title,
                })

        return {
            "mcp_scopes": mcp_scopes,
            "skill_scopes": skill_scopes,
            "sessions": sessions,
            "mcp_servers": mcp_servers,
            "skills": skills,
        }

    async def update_scope(self, payload: Dict):
        """Update scope configuration for MCP servers and skills.
        Payload format:
        {
          "mcp_scopes": { "server_id": {"allow": [...]} or {"deny": [...]} },
          "skill_scopes": { "skill_name": {"allow": [...]} or {"deny": [...]} }
        }
        """
        if not self.lifecycle:
            raise HTTPException(status_code=503, detail="Lifecycle not available")

        mcp_scopes = payload.get("mcp_scopes", {})
        skill_scopes = payload.get("skill_scopes", {})

        if not isinstance(mcp_scopes, dict) or not isinstance(skill_scopes, dict):
            raise HTTPException(status_code=400, detail="Invalid payload format")

        try:
            # Update MCP scopes
            if self.lifecycle.mcp_manager:
                existing_mcp = self.lifecycle.mcp_manager.mcp_config.get("_scope", {})
                # Clear entries not in the new payload
                for server_id in list(existing_mcp.keys()):
                    if server_id not in mcp_scopes:
                        self.lifecycle.mcp_manager.set_server_scope(server_id, None, [])
                # Set new entries
                for server_id, entry in mcp_scopes.items():
                    mode = "allow" if "allow" in entry else "deny" if "deny" in entry else None
                    sessions = entry.get(mode, []) if mode else []
                    self.lifecycle.mcp_manager.set_server_scope(server_id, mode, sessions)

            # Update skill scopes
            if self.lifecycle.skills_manager:
                existing_skills = self.lifecycle.skills_manager._raw_config.get("_scope", {})
                for skill_name in list(existing_skills.keys()):
                    if skill_name not in skill_scopes:
                        self.lifecycle.skills_manager.set_skill_scope(skill_name, None, [])
                for skill_name, entry in skill_scopes.items():
                    mode = "allow" if "allow" in entry else "deny" if "deny" in entry else None
                    sessions = entry.get(mode, []) if mode else []
                    self.lifecycle.skills_manager.set_skill_scope(skill_name, mode, sessions)

            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to update scope: {e}")
            raise HTTPException(status_code=500, detail="Failed to update scope configuration")
