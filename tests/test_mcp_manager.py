"""Tests for MCPManager persistent connection handling."""

import pytest

import core.agent.mcp_mgr as mcp_mgr
from core.agent.mcp_mgr import MCPManager, MCPServer


class FakeClient:
    """Minimal stand-in for fastmcp.Client tracking connect/close calls.

    Models the real fastmcp contract: `connected` mirrors is_connected(), which
    only reports that a session object exists and stays True even after the
    transport dies. `alive` is the real transport health, observable only via
    ping() -- tests flip it to simulate a crashed server.
    """

    instances = []

    def __init__(self, config):
        self.config = config
        self.connected = False
        self.alive = False
        self.enter_count = 0
        self.close_count = 0
        self.calls = []
        FakeClient.instances.append(self)

    def is_connected(self):
        return self.connected

    async def ping(self):
        if not self.alive:
            raise ConnectionError("transport is dead")
        return True

    async def __aenter__(self):
        self.connected = True
        self.alive = True
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.connected = False
        self.alive = False

    async def close(self):
        self.connected = False
        self.alive = False
        self.close_count += 1

    async def call_tool(self, tool_name, kwargs, timeout=None):
        if not self.alive:
            raise ConnectionError("transport is dead")
        self.calls.append((tool_name, kwargs))
        return f"result:{tool_name}"

    async def list_tools(self):
        return [
            {"name": "echo", "description": "echo tool", "inputSchema": {}},
        ]


class FakeLLMClient:
    def __init__(self):
        self.registered = {}

    def register_tool(self, name, description, parameters, func):
        self.registered[name] = func

    def unregister_tool(self, name):
        self.registered.pop(name, None)


@pytest.fixture
def manager(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_mgr, "MCP_CONFIG_PATH", tmp_path / "mcp.json")
    monkeypatch.setattr(mcp_mgr, "Client", FakeClient)
    FakeClient.instances = []
    mgr = MCPManager(FakeLLMClient())
    return mgr


def _make_server(server_id="srv1", enabled=False):
    return MCPServer(
        type="stdio",
        id=server_id,
        enabled=enabled,
        name="test-server",
        command="echo",
        args=[],
    )


@pytest.mark.anyio
async def test_tool_calls_reuse_one_connection(manager):
    server = _make_server(enabled=True)
    manager.add_server(server)

    func = manager._make_mcp_func(server, "echo")
    await func(x=1)
    await func(x=2)
    await func(x=3)

    # one client created, connected once, all calls on the same instance
    assert len(FakeClient.instances) == 1
    client = FakeClient.instances[0]
    assert client.enter_count == 1
    assert len(client.calls) == 3
    assert client.connected is True


@pytest.mark.anyio
async def test_reconnects_after_connection_drop(manager):
    server = _make_server(enabled=True)
    manager.add_server(server)

    func = manager._make_mcp_func(server, "echo")
    await func(x=1)

    # simulate the server dying between calls
    FakeClient.instances[0].connected = False

    result = await func(x=2)
    assert result == "result:echo"
    # a fresh client was built for the reconnect
    assert len(FakeClient.instances) == 2
    assert FakeClient.instances[1].connected is True


@pytest.mark.anyio
async def test_dead_transport_is_detected_despite_is_connected(manager):
    """fastmcp's is_connected() stays True after the transport dies, so the
    manager must fall back to a ping probe to notice."""
    server = _make_server(enabled=True)
    manager.add_server(server)

    func = manager._make_mcp_func(server, "echo")
    await func(x=0)

    dead = FakeClient.instances[0]
    dead.alive = False  # transport died; is_connected() still reports True
    assert dead.is_connected() is True

    with pytest.raises(ConnectionError):
        await func(x=1)

    # the poisoned client was dropped instead of being cached forever
    assert server.id not in manager._clients
    assert dead.close_count == 1


@pytest.mark.anyio
async def test_call_is_not_retried_when_connection_drops_mid_call(manager):
    """A dropped connection must not re-issue the call: the request may already
    have executed server-side, and a retry would duplicate side effects."""
    server = _make_server(enabled=True)
    manager.add_server(server)

    executions = []

    async def failing_call_tool(tool_name, kwargs, timeout=None):
        # the side effect lands, then the connection dies before responding
        executions.append(kwargs)
        FakeClient.instances[0].alive = False
        raise RuntimeError("connection lost")

    func = manager._make_mcp_func(server, "echo")
    await func(x=0)  # establish connection
    FakeClient.instances[0].call_tool = failing_call_tool

    with pytest.raises(RuntimeError):
        await func(x=1)

    # executed exactly once, no second dispatch
    assert executions == [{"x": 1}]
    assert len(FakeClient.instances) == 1


@pytest.mark.anyio
async def test_next_call_recovers_after_connection_death(manager):
    """Dropping the dead client must let the following call reconnect, so one
    crash does not permanently disable the server."""
    server = _make_server(enabled=True)
    manager.add_server(server)

    func = manager._make_mcp_func(server, "echo")
    await func(x=0)
    FakeClient.instances[0].alive = False

    with pytest.raises(ConnectionError):
        await func(x=1)

    # the next call builds a fresh connection and succeeds
    assert await func(x=2) == "result:echo"
    assert len(FakeClient.instances) == 2
    assert manager._clients[server.id] is FakeClient.instances[1]


@pytest.mark.anyio
async def test_genuine_tool_error_is_not_retried(manager):
    server = _make_server(enabled=True)
    manager.add_server(server)

    func = manager._make_mcp_func(server, "echo")
    await func(x=0)

    async def tool_error(tool_name, kwargs, timeout=None):
        raise ValueError("bad arguments")

    FakeClient.instances[0].call_tool = tool_error

    with pytest.raises(ValueError):
        await func(x=1)
    # connection is alive, so it is kept and no reconnect happened
    assert len(FakeClient.instances) == 1
    assert FakeClient.instances[0].connected is True
    assert manager._clients[server.id] is FakeClient.instances[0]


@pytest.mark.anyio
async def test_disable_server_closes_connection(manager):
    server = _make_server(enabled=False)
    manager.add_server(server)
    manager.mcp_config = {"mcpServers": {server.id: {"command": "echo"}}}

    await manager.enable_server(server.id)
    assert server.enabled is True
    assert server.id in manager._clients
    assert manager._clients[server.id].connected is True
    assert "echo" in manager.llm_api.registered

    await manager.disable_server(server.id)
    assert server.enabled is False
    assert server.id not in manager._clients
    assert FakeClient.instances[0].close_count == 1
    assert "echo" not in manager.llm_api.registered


@pytest.mark.anyio
async def test_list_tools_closes_connection_for_disabled_server(manager):
    server = _make_server(enabled=False)
    manager.add_server(server)

    tools = await manager.list_tools(server)
    assert tools and tools[0]["name"] == "echo"
    # disabled server: no lingering connection
    assert server.id not in manager._clients
    assert FakeClient.instances[0].close_count == 1


@pytest.mark.anyio
async def test_list_tools_keeps_connection_when_requested(manager):
    server = _make_server(enabled=False)
    manager.add_server(server)

    await manager.list_tools(server, keep_connection=True)
    assert server.id in manager._clients
    assert manager._clients[server.id].connected is True


@pytest.mark.anyio
async def test_shutdown_closes_all_connections(manager):
    servers = [_make_server(f"srv{i}") for i in range(3)]
    for server in servers:
        manager.add_server(server)
        await manager.list_tools(server, keep_connection=True)

    assert len(manager._clients) == 3
    await manager.shutdown()
    assert manager._clients == {}
    assert all(c.connected is False for c in FakeClient.instances)
    assert all(c.close_count == 1 for c in FakeClient.instances)


@pytest.mark.anyio
async def test_delete_server_closes_connection(manager):
    server = _make_server(enabled=False)
    manager.add_server(server)
    manager.mcp_config = {"mcpServers": {server.id: {"command": "echo"}}}

    await manager.enable_server(server.id)
    assert server.id in manager._clients

    await manager.delete_server(server.id)
    assert server.id not in manager._clients
    assert FakeClient.instances[0].close_count == 1
    assert server.id not in manager.mcp_config.get("mcpServers", {})


@pytest.mark.anyio
async def test_no_reconnect_after_disable(manager):
    """An in-flight/leftover tool func must not resurrect a deliberately
    closed connection after the server is disabled."""
    server = _make_server(enabled=False)
    manager.add_server(server)
    manager.mcp_config = {"mcpServers": {server.id: {"command": "echo"}}}

    await manager.enable_server(server.id)
    func = manager.llm_api.registered["echo"]
    await func(x=1)

    await manager.disable_server(server.id)

    with pytest.raises(RuntimeError):
        await func(x=2)
    # no new client was built for the disabled server
    assert len(FakeClient.instances) == 1
    assert server.id not in manager._clients


@pytest.mark.anyio
async def test_enable_server_fails_when_unreachable(manager, monkeypatch):
    server = _make_server(enabled=False)
    manager.add_server(server)
    manager.mcp_config = {"mcpServers": {server.id: {"command": "echo"}}}

    async def failing_aenter(self):
        raise RuntimeError("cannot connect")

    monkeypatch.setattr(FakeClient, "__aenter__", failing_aenter)

    with pytest.raises(ConnectionError):
        await manager.enable_server(server.id)

    # server must not be marked enabled, nothing registered, no client kept
    assert server.enabled is False
    assert manager.mcp_config["mcpServers"][server.id].get("enabled") is not True
    assert manager.llm_api.registered == {}
    assert server.id not in manager._clients
