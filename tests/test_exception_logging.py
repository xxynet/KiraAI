"""Regression tests verifying high-impact error paths retain exception tracebacks."""

import asyncio
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.src.qq_official import im as qq_official_im
from core.agent import mcp_mgr, tool_executor
from core.agent.config import ToolExecutionConfig
from core.agent.mcp_mgr import MCPManager, MCPServer
from core.agent.tool import ToolSet
from core.agent.tool_executor import ToolExecutor
from core.chat import MessageChain
from core.chat.message_elements import Text
from core.event_bus import EventBus
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool
from core.webchat import service as webchat_service
from core.webchat.service import WebChatService
from core.webchat.store import WebChatStore
from core.workflow.src.im.stages import request as request_stage
from tests.test_qq_official_adapter import make_adapter as make_qq_adapter
from tests.test_qq_official_messages import attach_api
from tests.test_qq_official_messages import message as qq_message
from tests.test_webchat import PROFILE, Sessions, make_adapter

try:
    _ExceptionGroup = ExceptionGroup
except NameError:  # Python 3.10 fallback
    from exceptiongroup import ExceptionGroup as _ExceptionGroup


@contextmanager
def _capture(logger_obj: logging.Logger):
    records: list[logging.LogRecord] = []

    class _Handler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Handler()
    logger_obj.addHandler(handler)
    try:
        yield records
    finally:
        logger_obj.removeHandler(handler)


@pytest.mark.anyio
async def test_event_bus_dispatch_task_error_keeps_traceback():
    queue: asyncio.Queue = asyncio.Queue()
    bus = EventBus(SimpleNamespace(set_stats=Mock()), queue)
    bus._dispatch_event = AsyncMock(side_effect=RuntimeError("boom-dispatch"))
    with _capture(bus.logger) as records:
        runner = asyncio.create_task(bus.dispatch())
        await queue.put(SimpleNamespace(event_type="custom"))
        await asyncio.sleep(0.05)
        await bus.stop()
        runner.cancel()
        with pytest.raises(asyncio.CancelledError):
            await runner
    assert any(r.exc_info and "boom-dispatch" in r.getMessage() for r in records)


@pytest.mark.anyio
async def test_tool_executor_error_keeps_traceback_and_llm_message():
    class FailingTool(BaseTool):
        name = "failing"
        description = "Always raises."
        parameters = {"type": "object", "properties": {}}

        async def execute(self, **args):
            raise RuntimeError("boom-tool")

    resp = LLMResponse("", tool_calls=[{"id": "c1", "function": {"name": "failing", "arguments": "{}"}}])
    with _capture(tool_executor.tool_logger) as records:
        await ToolExecutor().execute_tools(resp, ToolSet([FailingTool()]), config=ToolExecutionConfig())
    assert resp.tool_results[0]["content"] == "Error: Failed to call tool 'failing': boom-tool"
    assert any(r.exc_info and "boom-tool" in r.getMessage() for r in records)


@pytest.mark.anyio
async def test_mcp_list_tools_expands_exception_group(monkeypatch, tmp_path):
    monkeypatch.setattr(mcp_mgr, "MCP_CONFIG_PATH", tmp_path / "mcp.json")
    mgr = MCPManager(SimpleNamespace())
    nested = _ExceptionGroup("outer", [_ExceptionGroup("inner", [ValueError("root-cause")])])
    mgr._get_connected_client = AsyncMock(side_effect=nested)
    server = MCPServer(type="stdio", id="s1", enabled=False, name="demo", command="echo", args=[])
    with _capture(mcp_mgr.logger) as records:
        assert await mgr.list_tools(server, keep_connection=True) == []
    assert any(r.exc_info and "Failed to connect to MCP server demo" in r.getMessage() for r in records)
    assert any(r.exc_info and "ValueError: root-cause" in r.getMessage() for r in records)


@pytest.mark.anyio
async def test_request_stage_and_webchat_log_original_exception(tmp_path, monkeypatch):
    # BuildRequestStage: default LLM failure must include the original exception and traceback.
    session = SimpleNamespace(session_title="t", data={}, flatten_content=lambda: [])
    services = SimpleNamespace(
        session_manager=SimpleNamespace(get_session=AsyncMock(return_value=session)),
        prompt_manager=SimpleNamespace(get_agent_prompt=AsyncMock(return_value=[])),
        skills_manager=SimpleNamespace(skills_info=[]),
        subagent_manager=SimpleNamespace(presets=SimpleNamespace(build_presets_prompt=lambda sid: None)),
        provider_mgr=SimpleNamespace(get_default_llm=Mock(side_effect=RuntimeError("auth-bad"))),
    )
    event = SimpleNamespace(
        adapter=SimpleNamespace(platform="qq", name="qq"),
        is_group_message=lambda: False, self_id="1", model_group=None,
        session=SimpleNamespace(session_title="t", session_description=""),
    )
    ctx = SimpleNamespace(services=services, event=event, sid="qq:dm:1")
    with _capture(request_stage.llm_logger) as req_records:
        assert await request_stage.BuildRequestStage().run(ctx) is False
    assert any(r.exc_info and "auth-bad" in r.getMessage() for r in req_records)

    # WebChatService: dispatch failure must log traceback before raising ValueError("unavailable").
    store = WebChatStore(tmp_path / "webchat")
    await store.initialize()
    await store.set_setting("profile", PROFILE)
    svc = WebChatService(make_adapter(store), Sessions())
    monkeypatch.setattr(svc.adapter.get_capability(webchat_service.WebChatIMCapability), "receive_message", Mock(side_effect=RuntimeError("queue-boom")))
    with _capture(webchat_service.logger) as wc_records, pytest.raises(ValueError, match="unavailable"):
        await svc.submit("req-1", "hello")
    assert any(r.exc_info and "req-1" in r.getMessage() for r in wc_records)


@pytest.mark.anyio
async def test_qq_official_send_error_logs_details_while_keeping_result_err_sanitized():
    adapter = make_qq_adapter(proactive_enabled=False)
    attach_api(adapter, AsyncMock(side_effect=RuntimeError("code=40034005 detail=upstream-rejected")))
    await adapter.im._handle_group_message(qq_message())
    with _capture(qq_official_im.logger) as records:
        result = await adapter.send_group_message("group-openid", MessageChain([Text("hi")]))
    assert not result.ok and result.err == "Failed to send QQ official message (40034005)"
    assert any(r.exc_info and "40034005" in r.getMessage() and "upstream-rejected" in r.getMessage() for r in records)
