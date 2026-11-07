"""Tool interception, approval, and plugin dispatch regressions."""

import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig, ToolExecutionConfig
from core.agent.hook_context import ToolCallContext
from core.agent.hooks import AgentExecutionHooks
from core.agent.tool import ToolResult, ToolSet
from core.agent.tool_executor import ToolExecutor
from core.plugin import ToolCallContext as PluginToolCallContext
from core.plugin import on
from core.plugin.handlers import EventHandler, EventType, Priority, event_handler_reg
from core.provider import LLMModelClient, LLMRequest, LLMResponse, ModelInfo, ModelType
from core.utils.media_refs import MEDIA_REF_TYPE
from core.utils.tool_utils import BaseTool


class ProbeTool(BaseTool):
    name = "probe"
    description = "Record one invocation."
    parameters: ClassVar[dict] = {"type": "object", "properties": {"value": {"type": "string"}}}

    async def execute(self, **args):
        return "executed"


def _response(count=1):
    return LLMResponse("", tool_calls=[
        {"id": f"call-{index}", "type": "function", "function": {
            "name": "probe", "arguments": '{"value": "input"}',
        }}
        for index in range(1, count + 1)
    ])


def _executor(tool, *, hooks=None, im=False, response=None, tool_config=None):
    model = LLMModelClient(ModelInfo(
        model_type=ModelType.LLM, model_id="test", model_name="test-model",
        provider_id="test", provider_name="Test Provider",
    ))
    model.chat = AsyncMock(side_effect=[response or _response(), LLMResponse("complete")])
    context = (AgentExecutionContext(event=SimpleNamespace(sid="test", is_stopped=False))
               if im else BaseAgentExecutionContext())
    executor_type = AgentExecutor if im else BaseAgentExecutor
    return executor_type(
        [model], context=context, hooks=hooks,
        request=LLMRequest(tool_set=ToolSet([tool])),
        config=AgentExecutionConfig(max_steps=2, tool_config=tool_config or ToolExecutionConfig()),
    )


async def _collect(executor):
    return [step async for step in executor.run()]


@pytest.fixture
def isolated_handlers(monkeypatch):
    monkeypatch.setattr(event_handler_reg, "_handlers", {})


def test_tool_call_decorator_registers_priority_and_exports_context(monkeypatch):
    register = Mock()
    monkeypatch.setattr(on, "_register_hook", register)

    @on.tool_call(priority=Priority.HIGH)
    async def hook(ctx):
        pass

    register.assert_called_once_with(hook, Priority.HIGH, EventType.ON_TOOL_CALL)
    assert PluginToolCallContext is ToolCallContext


@pytest.mark.parametrize("agent_context", [None, BaseAgentExecutionContext()])
def test_tool_call_context_without_event_returns_none(agent_context):
    ctx = ToolCallContext("call-1", ProbeTool(), {}, agent_context=agent_context)
    assert ctx.event is None


def test_tool_call_context_exposes_original_event_without_a_second_copy():
    event = SimpleNamespace(sid="test", is_stopped=False)
    agent_context = AgentExecutionContext(event=event)
    ctx = ToolCallContext("call-1", ProbeTool(), {}, agent_context=agent_context)
    assert ctx.event is event

    replacement = SimpleNamespace(task_id="subagent-task")
    agent_context.event = replacement
    assert ctx.event is replacement


@pytest.mark.parametrize("invalid", [None, "invalid", {}])
def test_result_is_read_only_and_set_result_rejects_invalid_values(invalid):
    ctx = ToolCallContext("call-1", ProbeTool(), {})
    assert ctx.result is None
    result = ToolResult(text="denied")
    ctx.set_result(result)
    assert ctx.result is result

    with pytest.raises(AttributeError):
        ctx.result = ToolResult(text="direct assignment")
    with pytest.raises(TypeError, match="requires a ToolResult"):
        ctx.set_result(invalid)
    assert ctx.result is result


@pytest.mark.anyio
async def test_independent_hook_changes_arguments_without_accessing_im_registry(monkeypatch):
    lookups = Mock(side_effect=AssertionError("Independent agents must not dispatch IM events"))
    monkeypatch.setattr(event_handler_reg, "get_handlers", lookups)
    tool = ProbeTool()
    tool.execute = AsyncMock(return_value="executed")
    calls = []

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            calls.append(ctx)
            ctx.arguments = {"value": "approved input"}

    executor = _executor(tool, hooks=Hooks())
    steps = await _collect(executor)

    tool.execute.assert_awaited_once_with(value="approved input")
    assert len(calls) == 1
    assert calls[0].agent_context is executor.context
    assert calls[0].tool is tool
    assert calls[0].tool_call_id == "call-1"
    assert steps[0].llm_response.tool_results[0]["content"] == "executed"
    assert steps[-1].is_final
    lookups.assert_not_called()


@pytest.mark.anyio
async def test_override_is_per_call_and_uses_result_hooks_media_truncation_and_history(tmp_path):
    tool = ProbeTool()
    tool.execute = AsyncMock(return_value="executed")
    path = str(tmp_path / "attachment.png").replace("\\", "/")
    attachment = SimpleNamespace(to_path=AsyncMock(return_value=path))
    ref = {"type": MEDIA_REF_TYPE, "path": "session_media/a.png", "mime_type": "image/png"}
    override = ToolResult(text="cached", attachments=[attachment], media_refs=[ref])
    results = []

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            if ctx.tool_call_id == "call-1":
                ctx.set_result(override)

        async def on_tool_result(self, ctx, result):
            results.append(result)
            if result is override:
                result.text += "x" * 10000
            return True

    executor = _executor(
        tool, hooks=Hooks(), response=_response(2),
        tool_config=ToolExecutionConfig(max_tool_output_tokens=256),
    )
    steps = await _collect(executor)

    tool.execute.assert_awaited_once_with(value="input")
    assert results[0] is override
    assert results[1].text == "executed"
    attachment.to_path.assert_awaited_once()
    tool_results = steps[0].llm_response.tool_results
    assert [result["tool_call_id"] for result in tool_results] == ["call-1", "call-2"]
    text = tool_results[0]["content"][0]["text"]
    assert text.startswith("cached") and "Tool output truncated" in text
    assert path in text and len(text.encode("utf-8")) <= 256 * 4
    assert [message.role for message in executor.context.messages] == [
        "assistant", "tool", "tool", "user", "assistant",
    ]
    assert executor.context.messages[0].tool_calls == steps[0].llm_response.tool_calls
    assert executor.context.messages[1].tool_call_id == "call-1"
    assert executor.context.messages[3].content[1] is ref
    followup = executor.model_group[0].chat.await_args_list[1].args[0]
    assert followup.messages[1].content == text


@pytest.mark.anyio
async def test_im_hooks_use_context_and_first_result_wins(isolated_handlers):
    tool = ProbeTool()
    tool.execute = AsyncMock()
    received = []

    async def intercept(ctx):
        received.append(ctx)
        ctx.set_result(ToolResult(text="denied"))

    lower_priority = AsyncMock()

    async def result_hook(event, result):
        assert event is executor.context.event
        result.text += ":observed"

    event_handler_reg.register(EventHandler(EventType.ON_TOOL_CALL, Priority.LOW, lower_priority))
    event_handler_reg.register(EventHandler(EventType.ON_TOOL_CALL, Priority.HIGH, intercept))
    event_handler_reg.register(EventHandler(EventType.ON_TOOL_RESULT, Priority.MEDIUM, result_hook))
    executor = _executor(tool, im=True)
    steps = await _collect(executor)

    assert received[0].agent_context is executor.context
    assert received[0].agent_context.event is executor.context.event
    assert received[0].event is executor.context.event
    tool.execute.assert_not_awaited()
    lower_priority.assert_not_awaited()
    assert steps[0].llm_response.tool_results[0]["content"] == "denied:observed"
    assert steps[-1].llm_response.text_response == "complete"


@pytest.mark.anyio
@pytest.mark.parametrize("im", [False, True])
@pytest.mark.parametrize("failure", ["exception", "after_result", "invalid_result"])
async def test_hook_failure_never_executes_tool_and_returns_a_paired_result(
    isolated_handlers, im, failure,
):
    tool = ProbeTool()
    tool.execute = AsyncMock(return_value="executed")
    reported = []

    async def intercept(ctx):
        if ctx.tool_call_id != "call-1":
            return
        if failure == "invalid_result":
            ctx.set_result("invalid")
            return
        if failure == "after_result":
            ctx.set_result(ToolResult(text="must not survive an exception"))
        raise ValueError("approval service unavailable")

    async def report(event, error):
        reported.append((event, error))

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            await intercept(ctx)

    if im:
        event_handler_reg.register(EventHandler(EventType.ON_TOOL_CALL, Priority.MEDIUM, intercept))
        event_handler_reg.register(EventHandler(EventType.ON_EXCEPTION, Priority.MEDIUM, report))
    executor = _executor(tool, im=im, hooks=None if im else Hooks(), response=_response(2))
    steps = await _collect(executor)

    tool.execute.assert_awaited_once_with(*([executor.context.event] if im else []), value="input")
    results = steps[0].llm_response.tool_results
    assert [result["tool_call_id"] for result in results] == ["call-1", "call-2"]
    expected = "requires a ToolResult" if failure == "invalid_result" else "approval service unavailable"
    assert expected in results[0]["content"]
    assert "must not survive" not in results[0]["content"]
    assert results[1]["content"] == "executed"
    assert steps[-1].llm_response.text_response == "complete"
    if im:
        assert len(reported) == 1
        assert reported[0][0] is executor.context.event
        assert reported[0][1].stage == "on_tool_call"
        assert isinstance(reported[0][1].e, TypeError if failure == "invalid_result" else ValueError)


@pytest.mark.anyio
async def test_context_hook_exception_reports_none_for_non_im_context(isolated_handlers):
    async def fail(ctx):
        raise RuntimeError("failed")

    report = AsyncMock()
    event_handler_reg.register(EventHandler(EventType.ON_EXCEPTION, Priority.MEDIUM, report))
    handler = EventHandler(EventType.ON_TOOL_CALL, Priority.MEDIUM, fail)
    ctx = ToolCallContext("call-1", ProbeTool(), {}, agent_context=BaseAgentExecutionContext())

    with pytest.raises(RuntimeError, match="failed"):
        await handler.exec_handler(ctx)

    assert report.await_args.args[0] is None
    assert report.await_args.args[1].stage == "on_tool_call"


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
async def test_abort_during_approval_cleans_wait_and_never_executes_tool(driver):
    entered, cancelled = asyncio.Event(), asyncio.Event()
    tool = ProbeTool()
    tool.execute = AsyncMock()
    delivered = []

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    executor = _executor(tool, hooks=Hooks())

    async def on_result(step):
        delivered.append(step)

    executor.on_result = on_result
    task = executor.start() if driver == "start" else asyncio.create_task(_collect(executor))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert executor.state == "running"
        executor.queue("discard follow-up")
        assert executor.abort()
        value = await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    steps = delivered if driver == "start" else value
    assert cancelled.is_set()
    tool.execute.assert_not_awaited()
    assert len(steps) == 1 and steps[0].state == "stopped"
    assert steps[0].is_final and steps[0].llm_response is None
    assert executor.context.messages[0].tool_calls == []
    assert all(message.role != "tool" for message in executor.context.messages)
    executor.model_group[0].chat.assert_awaited_once()
    assert executor.state == "done"


@pytest.mark.anyio
async def test_task_cancellation_during_approval_cleans_hook_task():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    tool = ProbeTool()
    tool.execute = AsyncMock()

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    executor = _executor(tool, hooks=Hooks())
    task = executor.start()
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)

    assert cancelled.is_set()
    tool.execute.assert_not_awaited()
    assert executor.state == "done"


@pytest.mark.anyio
async def test_approval_wait_does_not_use_tool_execution_timeout():
    entered, approved = asyncio.Event(), asyncio.Event()
    tool = ProbeTool()
    tool.execute = AsyncMock(return_value="executed")

    class Hooks(AgentExecutionHooks):
        async def on_tool_call(self, ctx):
            entered.set()
            await approved.wait()

    executor = _executor(tool, hooks=Hooks(), tool_config=ToolExecutionConfig(tool_call_timeout=0.01))
    task = asyncio.create_task(_collect(executor))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        done, _ = await asyncio.wait({task}, timeout=0.03)
        assert not done
        tool.execute.assert_not_awaited()
        approved.set()
        steps = await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    tool.execute.assert_awaited_once_with(value="input")
    assert steps[0].llm_response.tool_results[0]["content"] == "executed"


@pytest.mark.anyio
async def test_tool_timeout_still_applies_after_approval():
    tool = ProbeTool()

    async def wait_forever(**kwargs):
        await asyncio.Event().wait()

    tool.execute = AsyncMock(side_effect=wait_forever)
    hook = AsyncMock()
    response = _response()
    await ToolExecutor().execute_tools(
        response, ToolSet([tool]), config=ToolExecutionConfig(tool_call_timeout=0.01),
        on_tool_call=hook,
    )

    hook.assert_awaited_once()
    assert hook.await_args.args[0].agent_context is None
    tool.execute.assert_awaited_once_with(value="input")
    assert "timed out after 0.01s" in response.tool_results[0]["content"]


@pytest.mark.anyio
async def test_missing_and_over_limit_tools_are_not_offered_for_approval():
    response = _response(3)
    response.tool_calls[0]["function"]["name"] = "missing"
    hook = AsyncMock()
    tool = ProbeTool()
    tool.execute = AsyncMock(return_value="executed")
    await ToolExecutor().execute_tools(
        response, ToolSet([tool]), config=ToolExecutionConfig(max_tool_calls_per_step=2),
        on_tool_call=hook,
    )

    hook.assert_awaited_once()
    assert hook.await_args.args[0].tool_call_id == "call-2"
    tool.execute.assert_awaited_once_with(value="input")
    assert "not implemented" in response.tool_results[0]["content"]
    assert response.tool_results[1]["content"] == "executed"
    assert "Tool call limit exceeded" in response.tool_results[2]["content"]
