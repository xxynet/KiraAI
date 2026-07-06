import json
import asyncio
import uuid
from typing import Optional, Literal
from dataclasses import dataclass, field
from fastmcp import Client

from core.llm_client import LLMClient
from core.utils.path_utils import get_config_path

from core.logging_manager import get_logger

logger = get_logger("mcp", "orange")

MCP_CONFIG_PATH = get_config_path() / "mcp.json"

default_config = {
  "mcpServers": {}
}


@dataclass
class MCPServer:
    type: Literal["stdio", "sse", "streamable_http"]

    id: str
    enabled: bool
    name: str
    description: str = ""
    timeout: float = 10.0

    url: Optional[str] = ""
    headers: Optional[dict] = field(default_factory=dict)

    command: Optional[str] = ""
    args: Optional[list] = field(default_factory=list)
    env: Optional[dict] = field(default_factory=dict)

    tools: list = field(default_factory=list)

    def to_dict(self):
        server_cfg: dict = {}
        if self.type == "stdio":
            if self.command:
                server_cfg["command"] = self.command
            if self.args:
                server_cfg["args"] = self.args
            if self.env:
                server_cfg["env"] = self.env
        elif self.type in ("sse", "streamable_http"):
            if self.url:
                server_cfg["url"] = self.url
            if self.headers:
                server_cfg["headers"] = self.headers
        if self.timeout:
            server_cfg["timeout"] = self.timeout

        server_cfg.setdefault("type", self.type)
        server_cfg["name"] = self.name
        config = {"mcpServers": {self.id: server_cfg}}
        return config


class MCPManager:
    def __init__(self, llm_api: LLMClient):
        self.llm_api = llm_api
        self.mcp_config: dict = self.load_config()
        self.servers: list[MCPServer] = []

    @staticmethod
    def load_config():
        config_dir = MCP_CONFIG_PATH.parent
        if not config_dir.exists():
            config_dir.mkdir(parents=True, exist_ok=True)

        if not MCP_CONFIG_PATH.exists():
            with open(MCP_CONFIG_PATH, 'w', encoding="utf-8") as f:
                f.write(json.dumps(default_config, indent=4, ensure_ascii=False))

        with open(MCP_CONFIG_PATH, 'r', encoding="utf-8") as f:
            mcp_conf_str = f.read()
        try:
            mcp_conf = json.loads(mcp_conf_str)
        except json.JSONDecodeError:
            mcp_conf = default_config
        return mcp_conf

    @staticmethod
    def _check_server_type(server: dict) -> Literal["stdio", "sse", "streamable_http"]:
        server_type = server.get("type")

        if server_type and server_type in ("stdio", "sse", "streamable_http"):
            return server_type

        url: Optional[str] = server.get("url")
        if url and url.endswith("/sse"):
            return "sse"
        if url and url.endswith(("/mcp", "/message")):
            return "streamable_http"

        command: Optional[str] = server.get("command")
        if command:
            return "stdio"

    def load_servers(self):
        self.servers.clear()
        server_configs = self.mcp_config.get("mcpServers")
        if not server_configs:
            return []

        if not isinstance(server_configs, dict):
            return []

        for server_id, server_config in server_configs.items():
            server_type = self._check_server_type(server_config)
            if not server_type:
                continue

            enabled = server_config.get("enabled", False)
            name = server_config.get("name") or server_id
            description = server_config.get("description") or ""

            server = MCPServer(
                type=server_type,
                id=server_id,
                enabled=enabled,
                name=name,
                description=description
            )

            if server_type == "stdio":
                command = server_config.get("command")
                args = server_config.get("args", [])
                server.command = command
                server.args = args
            elif server_type in ("sse", "streamable_http"):
                url = server_config.get("url", "")
                headers = server_config.get("headers", {})
                server.url = url
                server.headers = headers

            self.servers.append(server)

    def add_server(self, server: MCPServer):
        self.servers.append(server)

    def save_server_config(self):
        with open(MCP_CONFIG_PATH, 'w', encoding="utf-8") as f:
            f.write(json.dumps(self.mcp_config, indent=4, ensure_ascii=False))

    @staticmethod
    def _build_single_server_config(name: str, description: str, raw_config: dict) -> dict:
        if not isinstance(raw_config, dict):
            raise ValueError("MCP server config must be a JSON object")

        source_config = raw_config
        maybe_servers = raw_config.get("mcpServers")
        if isinstance(maybe_servers, dict) and maybe_servers:
            if name in maybe_servers:
                source_config = maybe_servers[name]
            else:
                first_key = next(iter(maybe_servers))
                source_config = maybe_servers[first_key]

        if not isinstance(source_config, dict):
            raise ValueError("MCP server config must be a JSON object")

        server_cfg = dict(source_config)
        if description:
            server_cfg["description"] = description
        server_cfg.setdefault("name", name)
        return server_cfg

    def add_or_update_server_from_config(self, name: str, description: str, config_json: dict) -> MCPServer:
        if not isinstance(config_json, dict):
            raise ValueError("MCP config must be a JSON object")

        server_cfg = self._build_single_server_config(name=name, description=description, raw_config=config_json)
        if not self._check_server_type(server_cfg):
            raise ValueError(
                "Cannot determine server type from config. "
                "Please provide 'type' (stdio/sse/streamable_http), "
                "a 'url' ending with /sse, /mcp or /message, "
                "or a 'command' for stdio servers."
            )

        config = self.load_config()
        servers = config.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            config["mcpServers"] = servers

        server_id = uuid.uuid4().hex
        servers[server_id] = server_cfg

        self.mcp_config = config
        self.save_server_config()

        self.load_servers()
        for server in self.servers:
            if server.id == server_id:
                return server

        raise ValueError(f"Failed to create or update MCP server {name}")

    def get_server_config_for_editor(self, server_id: str) -> dict:
        """
        Return the config for a single server suitable for the editor:
        meta fields (enabled, name, description) removed.
        """
        config = self.load_config()
        servers = config.get("mcpServers") or {}
        if not isinstance(servers, dict):
            raise ValueError(f"MCP server {server_id} not found")

        server_cfg = servers.get(server_id)
        if server_cfg is None:
            raise ValueError(f"MCP server {server_id} not found")
        if not isinstance(server_cfg, dict):
            raise ValueError(f"MCP server {server_id} config is invalid")
        editor_cfg = {
            k: v
            for k, v in server_cfg.items()
            if k not in ("enabled", "name", "description")
        }
        return editor_cfg

    def update_server_from_editor(self, server_id: str, name: Optional[str], description: str, editor_config: dict) -> None:
        """
        Merge editor JSON back into the stored config for a single server.
        Meta fields are managed outside the editor:
        - keep existing 'enabled'
        - update 'name' and 'description' from arguments
        """
        if not isinstance(editor_config, dict):
            raise ValueError("MCP editor config must be a JSON object")

        config = self.load_config()
        servers = config.get("mcpServers")
        if not isinstance(servers, dict):
            servers = {}
            config["mcpServers"] = servers

        existing = servers.get(server_id)
        if existing is None or not isinstance(existing, dict):
            raise ValueError(f"MCP server {server_id} not found")

        enabled = bool(existing.get("enabled", False))
        final_name = (name or "").strip() or existing.get("name", server_id)
        base_without_meta = {
            k: v
            for k, v in existing.items()
            if k not in ("enabled", "name", "description")
        }

        merged = dict(base_without_meta)
        merged.update(editor_config)
        merged["enabled"] = enabled
        merged["name"] = final_name
        if description is not None:
            merged["description"] = description
        elif "description" in existing:
            merged["description"] = existing["description"]

        if not self._check_server_type(merged):
            raise ValueError(
                "Cannot determine server type from config. "
                "Please provide 'type' (stdio/sse/streamable_http), "
                "a 'url' ending with /sse, /mcp or /message, "
                "or a 'command' for stdio servers."
            )

        servers[server_id] = merged

        self.mcp_config = config
        self.save_server_config()

        for server in self.servers:
            if server.id != server_id:
                continue
            server.name = final_name
            server_type = self._check_server_type(merged)
            if server_type:
                server.type = server_type
            server.description = merged.get("description", server.description)
            timeout_val = merged.get("timeout")
            if isinstance(timeout_val, (int, float)):
                server.timeout = float(timeout_val)
            if server.type == "stdio":
                server.command = merged.get("command", server.command)
                server.args = merged.get("args", server.args)
                server.env = merged.get("env", server.env)
            elif server.type in ("sse", "streamable_http"):
                server.url = merged.get("url", server.url)
                headers_val = merged.get("headers")
                if isinstance(headers_val, dict):
                    server.headers = headers_val
            break

    def delete_server(self, server_id: str) -> None:
        """Remove a server from config and in-memory state. Raises ValueError if not found."""
        servers = self.mcp_config.get("mcpServers") or {}
        if not isinstance(servers, dict):
            raise ValueError(f"MCP server {server_id} not found")

        if server_id not in servers:
            raise ValueError(f"MCP server {server_id} not found")

        # Unregister tools if server was enabled
        target_server = next((s for s in self.servers if s.id == server_id), None)
        if target_server and target_server.enabled:
            for tool in target_server.tools:
                self.llm_api.unregister_tool(tool.get("name"))

        servers.pop(server_id)
        self.mcp_config["mcpServers"] = servers
        self.save_server_config()
        self.load_servers()

    # ====== Scope methods ======

    def get_tool_server_map(self) -> dict[str, str]:
        """Map tool_name -> server_id for all enabled servers."""
        mapping = {}
        for server in self.servers:
            if server.enabled:
                for tool in server.tools:
                    mapping[tool.get("name")] = server.id
        return mapping

    def get_server_scope(self, server_id: str) -> Optional[dict]:
        """Return scope entry for a server. None = global.
        Format: {"allow": [sids]} or {"deny": [sids]}"""
        return self.mcp_config.get("_scope", {}).get(server_id)

    def is_server_allowed(self, server_id: str, session_id: str) -> bool:
        """Check if a session is allowed to use a server."""
        scope = self.get_server_scope(server_id)
        if not scope:
            return True  # global
        if "allow" in scope:
            return session_id in scope["allow"]
        if "deny" in scope:
            return session_id not in scope["deny"]
        return True

    def set_server_scope(self, server_id: str, mode: Optional[str], sessions: list[str]):
        """Set scope for a server. mode='allow'|'deny', or None to clear."""
        scope = self.mcp_config.get("_scope", {})
        if mode and sessions:
            scope[server_id] = {mode: sessions}
        else:
            scope.pop(server_id, None)
        if scope:
            self.mcp_config["_scope"] = scope
        else:
            self.mcp_config.pop("_scope", None)
        self.save_server_config()

    def remove_session_from_scopes(self, session_id: str):
        """Remove a session from all MCP scope entries (cleanup on session delete)."""
        scope = self.mcp_config.get("_scope", {})
        changed = False
        for sid in list(scope.keys()):
            entry = scope[sid]
            for mode_key in ("allow", "deny"):
                if mode_key in entry and session_id in entry[mode_key]:
                    entry[mode_key].remove(session_id)
                    if not entry[mode_key]:
                        del scope[sid]
                    changed = True
                    break
        if changed:
            if scope:
                self.mcp_config["_scope"] = scope
            else:
                self.mcp_config.pop("_scope", None)
            self.save_server_config()

    # ====== End scope methods ======

    async def enable_server(self, server_id: str):
        target_server = None
        for server in self.servers:
            if server.id == server_id:
                target_server = server
                break
        if not target_server:
            raise ValueError(f"MCP server {server_id} not found")

        if target_server.enabled:
            return

        await self.list_tools(target_server)

        tool_names = []

        for tool in target_server.tools:
            tool_name = tool.get("name")
            tool_names.append(tool_name)

            func = await self._make_mcp_func(target_server, tool_name)

            self.llm_api.register_tool(
                name=tool_name,
                description=tool.get("description"),
                parameters=tool.get("parameters"),
                func=func,
            )
        logger.info(f"Registered {len(tool_names)} MCP tools from {target_server.name}: {tool_names}")

        target_server.enabled = True
        if server_id in self.mcp_config["mcpServers"]:
            self.mcp_config["mcpServers"][server_id]["enabled"] = True
        self.save_server_config()

    def disable_server(self, server_id: str):
        target_server = None
        for server in self.servers:
            if server.id == server_id:
                target_server = server
                break
        if not target_server:
            raise ValueError(f"MCP server {server_id} not found")

        if not target_server.enabled:
            return

        for tool in target_server.tools:
            tool_name = tool.get("name")
            self.llm_api.unregister_tool(tool_name)

        target_server.enabled = False
        if server_id in self.mcp_config["mcpServers"]:
            self.mcp_config["mcpServers"][server_id]["enabled"] = False
        self.save_server_config()

        logger.info(f"Disabled MCP Server {target_server.name}")

    async def init_mcp(self):
        self.mcp_config = self.load_config()
        self.load_servers()

        async def init_server(server):
            await self.list_tools(server)

            if server.enabled:
                tool_names = []
                for tool in server.tools:
                    tool_name = tool.get("name")
                    tool_names.append(tool_name)
                    func = await self._make_mcp_func(server, tool_name)
                    self.llm_api.register_tool(
                        name=tool_name,
                        description=tool.get("description"),
                        parameters=tool.get("parameters"),
                        func=func
                    )
                logger.info(f"Registered {len(tool_names)} MCP tools from {server.name}: {tool_names}")

        for server in self.servers:
            asyncio.create_task(init_server(server))

    @staticmethod
    async def _make_mcp_func(server: MCPServer, tool_name: str):
        async def _wrapped(*_, **kwargs):
            # ignore positional args, e.g. MessageEvent
            client_inner = Client(server.to_dict())
            async with client_inner:
                result = await client_inner.call_tool(tool_name, kwargs, timeout=server.timeout)
                return str(result)

        return _wrapped

    @staticmethod
    async def list_tools(server: MCPServer):
        server.tools.clear()
        client = Client(server.to_dict())
        try:
            async with client:
                try:
                    tools_response = await client.list_tools()
                except Exception as e:
                    logger.error(f"Failed to list MCP tools for {server.name}: {e}")
                    return
                if isinstance(tools_response, dict):
                    tools = tools_response.get("tools", [])
                elif isinstance(tools_response, list):
                    tools = tools_response
                else:
                    tools = []

            for tool in tools:
                if hasattr(tool, "model_dump"):
                    tool_dict = tool.model_dump()
                else:
                    tool_dict = tool

                name = tool_dict.get("name", "")
                description = tool_dict.get("description", "")
                parameters = tool_dict.get("inputSchema", {})

                if not name:
                    continue

                server.tools.append({
                    "name": name,
                    "description": description,
                    "parameters": parameters
                })

            return server.tools
        except Exception as e:
            logger.error(f"Failed to connect to MCP servers: {e}")
            return []
