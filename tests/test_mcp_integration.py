"""End-to-end MCPManager tests against a real stdio MCP server.

These cover behaviour the FakeClient unit tests cannot: fastmcp's real
is_connected() keeps returning True after a stdio subprocess dies, so a cached
client can look healthy while being permanently unusable.
"""

import sys
import textwrap
from pathlib import Path

import pytest
from mcp.shared.exceptions import McpError

from core.agent.mcp_mgr import MCPManager, MCPServer

# A tool that performs its side effect and then hard-crashes before responding:
# exactly the window where a blind retry would double-execute it.
SERVER_SOURCE = textwrap.dedent(
    """
    import os
    import sys
    from pathlib import Path

    from fastmcp import FastMCP

    LEDGER = Path(sys.argv[1])
    mcp = FastMCP("flaky")

    @mcp.tool
    def transfer(amount: int) -> str:
        with LEDGER.open("a", encoding="utf-8") as f:
            f.write(f"transfer {amount}\\n")
        os._exit(1)

    @mcp.tool
    def ping_tool() -> str:
        return "pong"

    if __name__ == "__main__":
        mcp.run()
    """
)


class _DummyLLM:
    def register_tool(self, **kwargs):
        pass

    def unregister_tool(self, name):
        pass


@pytest.fixture
def flaky_env(tmp_path, monkeypatch):
    import core.agent.mcp_mgr as mcp_mgr

    monkeypatch.setattr(mcp_mgr, "MCP_CONFIG_PATH", tmp_path / "mcp.json")

    script = tmp_path / "flaky_server.py"
    script.write_text(SERVER_SOURCE, encoding="utf-8")
    ledger = tmp_path / "ledger.txt"
    ledger.write_text("", encoding="utf-8")

    manager = MCPManager(_DummyLLM())
    server = MCPServer(
        type="stdio",
        id="flaky",
        enabled=True,
        name="flaky",
        command=sys.executable,
        args=[str(script), str(ledger)],
        timeout=30.0,
    )
    manager.add_server(server)
    return manager, server, ledger


def _ledger_entries(ledger: Path) -> list[str]:
    return [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.anyio
async def test_crashing_tool_executes_exactly_once(flaky_env):
    """A server crash mid-call must not cause the side effect to run twice."""
    manager, server, ledger = flaky_env
    try:
        transfer = manager._make_mcp_func(server, "transfer")
        with pytest.raises(McpError):
            await transfer(amount=100)

        assert _ledger_entries(ledger) == ["transfer 100"]
    finally:
        await manager.shutdown()


@pytest.mark.anyio
async def test_server_recovers_after_crash(flaky_env):
    """One crash must not permanently poison the cached connection."""
    manager, server, ledger = flaky_env
    try:
        ping = manager._make_mcp_func(server, "ping_tool")
        transfer = manager._make_mcp_func(server, "transfer")

        assert "pong" in await ping()

        with pytest.raises(McpError):
            await transfer(amount=1)

        # the dead client must have been dropped, not cached as "connected"
        assert server.id not in manager._clients

        # a fresh subprocess is spawned and the server is usable again
        assert "pong" in await ping()
        assert _ledger_entries(ledger) == ["transfer 1"]
    finally:
        await manager.shutdown()
