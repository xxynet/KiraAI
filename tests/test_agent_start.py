import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig
from core.agent.tool import ToolSet
from core.plugin.handlers import EventType, event_handler_reg
from core.provider import LLMRequest, LLMResponse, ProviderAPIError
from core.utils.tool_utils import BaseTool


def _model(callback):
    return SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_name="test", model_id="test"),
        chat=AsyncMock(side_effect=callback),
    )


def _context(model):
    return BaseAgentExecutionContext(
        request=LLMRequest(messages=[{"role": "user", "content": "original task"}]),
        model_group=[model],
    )


async def _collect(executor, context):
    return [step async for step in executor.run(context)]


@pytest.mark.anyio
async def test_start_returns_task_and_accepts_steer_before_first_model_call():
    seen = []
    delivered = []

    async def chat(request):
        seen.extend(deepcopy([message.to_dict() for message in request.messages]))
        return LLMResponse("complete")

    async def on_result(result):
        delivered.append(result)

    model = _model(chat)
    context = _context(model)
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=1))
    task = executor.start(context, on_result=on_result)
    try:
        assert isinstance(task, asyncio.Task)
        model.chat.assert_not_awaited()
        assert executor.steer("focus on performance")
        assert context.new_messages == []
        result = await asyncio.wait_for(task, timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert len(delivered) == 1
    assert delivered[0] is result
    assert result.is_final and result.state == "success"
    assert seen[1] == {"role": "user", "content": "focus on performance"}
    assert "final model call" in seen[2]["content"]
    assert [message.content for message in context.new_messages] == ["focus on performance", "complete"]
    assert not executor.steer("after completion")


@pytest.mark.anyio
async def test_background_results_are_ordered_and_callback_can_steer_next_step():
    delivered, seen = [], []
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        if len(seen) == 1:
            return LLMResponse("working", tool_calls=[{
                "id": "call-1", "type": "function",
                "function": {"name": "missing", "arguments": "{}"},
            }])
        assert delivered[0].step_index == 1
        return LLMResponse("complete")

    async def on_result(result):
        delivered.append(result)
        if not result.is_final:
            assert executor.steer("direction from callback")
        else:
            assert not executor.steer("already finished")

    result = await executor.start(_context(_model(chat)), on_result=on_result)

    assert [step.step_index for step in delivered] == [1, 2]
    assert [step.is_final for step in delivered] == [False, True]
    assert result is delivered[-1]
    assert seen[1][-2] == {"role": "user", "content": "direction from callback"}


@pytest.mark.anyio
async def test_start_reserves_single_run_until_result_callback_finishes():
    callback_started, release = asyncio.Event(), asyncio.Event()
    executor = BaseAgentExecutor()
    context = _context(_model(lambda request: LLMResponse("complete")))

    async def on_result(result):
        callback_started.set()
        await release.wait()

    task = executor.start(context, on_result=on_result)
    try:
        with pytest.raises(RuntimeError, match="already running"):
            executor.start(context)
        with pytest.raises(RuntimeError, match="already running"):
            await _collect(executor, context)
        await asyncio.wait_for(callback_started.wait(), timeout=2)
        assert not task.done()
        with pytest.raises(RuntimeError, match="already running"):
            executor.start(context)
        with pytest.raises(RuntimeError, match="already running"):
            await _collect(executor, context)
    finally:
        release.set()
        await asyncio.wait_for(task, timeout=2)

    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert (await executor.start(fresh)).llm_response.text_response == "fresh"


@pytest.mark.anyio
async def test_foreground_run_rejects_background_start():
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    context = _context(_model(lambda request: LLMResponse("", tool_calls=[{
        "id": "call-1", "function": {"name": "missing", "arguments": "{}"},
    }])))
    iterator = executor.run(context)
    try:
        assert not (await anext(iterator)).is_final
        with pytest.raises(RuntimeError, match="already running"):
            executor.start(context)
    finally:
        await iterator.aclose()

    assert (await executor.start(_context(_model(lambda request: LLMResponse("fresh"))))).is_final


@pytest.mark.parametrize("phase", ["before_start", "model", "callback"])
@pytest.mark.anyio
async def test_background_cancellation_releases_reservation_and_pending_steering(phase):
    started, release = asyncio.Event(), asyncio.Event()
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))

    async def chat(request):
        if phase == "model":
            started.set()
            await release.wait()
        return LLMResponse("complete")

    async def on_result(result):
        started.set()
        await release.wait()

    context = _context(_model(chat))
    task = executor.start(context, on_result=on_result)
    try:
        assert executor.steer("must not leak")
        if phase != "before_start":
            await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert not executor.steer("inactive")
    if phase == "before_start":
        context.model_group[0].chat.assert_not_awaited()
        assert context.new_messages == []
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert (await executor.start(fresh)).llm_response.text_response == "fresh"
    assert all(message.content != "must not leak" for message in fresh.request.messages)


@pytest.mark.parametrize("phase", ["model", "callback"])
@pytest.mark.anyio
async def test_background_failures_remain_on_task_and_are_logged(monkeypatch, phase):
    from core.agent import base_agent_executor

    error = TypeError(f"{phase} failure")
    log = Mock()
    monkeypatch.setattr(base_agent_executor.logger, "error", log)
    executor = BaseAgentExecutor()

    async def chat(request):
        if phase == "model":
            raise error
        return LLMResponse("complete")

    async def on_result(result):
        raise error

    task = executor.start(_context(_model(chat)), on_result=on_result)
    with pytest.raises(TypeError) as captured:
        await task

    assert captured.value is error
    log.assert_called_once()
    assert log.call_args.kwargs["exc_info"][1] is error
    assert log.call_args.kwargs["exc_info"][2] is not None
    assert not executor.steer("inactive")
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert len(await _collect(executor, fresh)) == 1


@pytest.mark.anyio
async def test_provider_error_is_delivered_as_an_agent_step_result():
    error = ProviderAPIError("provider unavailable")
    delivered = []

    async def chat(request):
        raise error

    async def on_result(result):
        delivered.append(result)

    result = await BaseAgentExecutor().start(_context(_model(chat)), on_result=on_result)

    assert delivered == [result]
    assert result.state == "error" and result.is_final
    assert "provider unavailable" in result.err


@pytest.mark.anyio
async def test_zero_step_background_run_has_no_results_or_callbacks():
    model = _model(lambda request: LLMResponse("complete"))
    callback = AsyncMock()
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=0))
    task = executor.start(_context(model), on_result=callback)
    assert not executor.steer("no steps")
    assert await task is None
    model.chat.assert_not_awaited()
    callback.assert_not_awaited()


@pytest.mark.anyio
async def test_start_captures_config_before_task_is_scheduled():
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=1))
    model = _model(lambda request: LLMResponse("complete"))
    task = executor.start(_context(model))
    executor.config = AgentExecutionConfig(max_steps=0)
    result = await task
    assert result.is_final
    model.chat.assert_awaited_once()
    assert await executor.start(_context(model)) is None


@pytest.mark.anyio
async def test_task_creation_failure_rolls_back_run_reservation(monkeypatch):
    loop = asyncio.get_running_loop()
    executor = BaseAgentExecutor()
    context = _context(_model(lambda request: LLMResponse("complete")))
    with monkeypatch.context() as patch:
        patch.setattr(loop, "create_task", Mock(side_effect=RuntimeError("task creation failed")))
        with pytest.raises(RuntimeError, match="task creation failed"):
            executor.start(context)

    assert not executor.steer("inactive")
    assert (await executor.start(context)).is_final


def test_start_requires_running_event_loop_without_reserving_executor():
    executor = BaseAgentExecutor()
    context = _context(_model(lambda request: LLMResponse("complete")))
    with pytest.raises(RuntimeError, match="running event loop"):
        executor.start(context)
    assert not executor.steer("inactive")


@pytest.mark.anyio
async def test_background_im_executor_preserves_event_tools_and_hooks(monkeypatch):
    event = SimpleNamespace(sid="test:dm:parent", is_stopped=False)
    llm_hook, tool_hook = AsyncMock(), AsyncMock()
    hooks = {
        EventType.ON_LLM_RESPONSE: [SimpleNamespace(exec_handler=llm_hook)],
        EventType.ON_TOOL_RESULT: [SimpleNamespace(exec_handler=tool_hook)],
    }
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: hooks.get(event_type, []))

    class ProbeTool(BaseTool):
        name = "probe"
        description = "Return a result."

        async def execute(self, current_event):
            assert current_event is event
            return "tool result"

    responses = iter([LLMResponse("", tool_calls=[{
        "id": "call-1", "function": {"name": "probe", "arguments": "{}"},
    }]), LLMResponse("complete")])
    model = _model(lambda request: next(responses))
    context = AgentExecutionContext(event, LLMRequest(), [], [model])
    executor = AgentExecutor(ToolSet([ProbeTool()]), config=AgentExecutionConfig(max_steps=2))
    on_result = AsyncMock()

    result = await executor.start(context, on_result=on_result)

    assert result.llm_response.text_response == "complete"
    assert on_result.await_count == llm_hook.await_count == 2
    assert tool_hook.await_count == 1
    assert all(call.args[0] is event for call in llm_hook.await_args_list + tool_hook.await_args_list)
