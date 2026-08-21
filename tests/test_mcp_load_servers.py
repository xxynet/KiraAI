"""Tests for MCPManager.load_servers() parsing of mcp.json."""

import json

import pytest

import core.agent.mcp_mgr as mcp_mgr
from core.agent.mcp_mgr import MCPManager


class FakeFuncToolManager:
    def __init__(self):
        self.registered = {}

    def register_tool(self, name, description, parameters, func):
        self.registered[name] = func

    def unregister_tool(self, name):
        self.registered.pop(name, None)


@pytest.fixture
def make_manager(monkeypatch, tmp_path):
    config_path = tmp_path / "mcp.json"
    monkeypatch.setattr(mcp_mgr, "MCP_CONFIG_PATH", config_path)

    def _make(servers: dict) -> MCPManager:
        config_path.write_text(
            json.dumps({"mcpServers": servers}, ensure_ascii=False),
            encoding="utf-8",
        )
        manager = MCPManager(FakeFuncToolManager())
        manager.load_servers()
        return manager

    return _make


def test_stdio_server_keeps_env_and_timeout(make_manager):
    """Stdio servers usually carry their API keys in env; dropping it makes
    every tool call fail after a restart."""
    manager = make_manager({
        "srv1": {
            "enabled": True,
            "command": "uvx",
            "args": ["some-mcp-server"],
            "env": {"API_KEY": "secret"},
            "timeout": 45,
        }
    })

    server = manager.servers[0]
    assert server.type == "stdio"
    assert server.env == {"API_KEY": "secret"}
    assert server.timeout == 45.0

    # the env must survive into the config handed to the fastmcp client
    server_cfg = server.to_dict()["mcpServers"]["srv1"]
    assert server_cfg["env"] == {"API_KEY": "secret"}
    assert server_cfg["timeout"] == 45.0


def test_stdio_server_without_env_uses_defaults(make_manager):
    manager = make_manager({
        "srv1": {"enabled": True, "command": "uvx", "args": []}
    })

    server = manager.servers[0]
    assert server.env == {}
    assert server.timeout == 10.0
    assert "env" not in server.to_dict()["mcpServers"]["srv1"]


def test_remote_server_keeps_timeout_and_headers(make_manager):
    manager = make_manager({
        "srv1": {
            "enabled": True,
            "url": "https://example.com/mcp",
            "headers": {"Authorization": "Bearer x"},
            "timeout": 3.5,
        }
    })

    server = manager.servers[0]
    assert server.type == "streamable_http"
    assert server.headers == {"Authorization": "Bearer x"}
    assert server.timeout == 3.5


@pytest.mark.parametrize("timeout", [None, "30", True, {"seconds": 5}])
def test_invalid_timeout_falls_back_to_default(make_manager, timeout):
    manager = make_manager({
        "srv1": {"enabled": True, "command": "uvx", "timeout": timeout}
    })

    assert manager.servers[0].timeout == 10.0


def test_invalid_env_falls_back_to_empty_dict(make_manager):
    manager = make_manager({
        "srv1": {"enabled": True, "command": "uvx", "env": "API_KEY=secret"}
    })

    assert manager.servers[0].env == {}
