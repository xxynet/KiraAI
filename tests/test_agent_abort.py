import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig
from core.agent.hooks import AgentExecutionHooks
from core.agent.message import OpenAIMessage
from core.agent.tool import ToolSet
from core.provider import LLMRequest, LLMResponse, ProviderAPIError
from core.utils.tool_utils import BaseTool


def _model(callback):
    return SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_name="test", model_id="test"),
        chat=AsyncMock(side_effect=callback),
    )


def _tool_response():
    return LLMResponse("working", tool_calls=[
        {"id": f"call-{index}", "function": {"name": "probe", "arguments": "{}"}}
        for index in range(2)
    ])


async def _collect(executor):
    return [step async for step in executor.run()]


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
@pytest.mark.parametrize("phase", ["model", "tool", "provider_error"])
async def test_abort_waits_for_call_discards_pending_work_and_allows_reuse(driver, phase):
    started, release = asyncio.Event(), asyncio.Event()
    calls, delivered = [], []

    class ProbeTool(BaseTool):
        name = "probe"

        async def execute(self):
            calls.append("tool")
            started.set()
            await release.wait()
            calls.append("tool finished")
            return "tool result"

    async def chat(request):
        if phase == "tool":
            return _tool_response()
        started.set()
        await release.wait()
        calls.append("model finished")
        if phase == "provider_error":
            raise ProviderAPIError("failed during abort")
        return _tool_response()

    async def on_result(result):
        delivered.append(result)

    context = BaseAgentExecutionContext(messages=[OpenAIMessage(role="user", content="initial")])
    primary, fallback = _model(chat), _model(lambda request: LLMResponse("fallback"))
    executor = BaseAgentExecutor(
        [primary, fallback], context=context, request=LLMRequest(tool_set=ToolSet([ProbeTool()])),
        config=AgentExecutionConfig(max_steps=3), on_result=on_result,
    )
    assert not executor.abort()
    task = executor.start() if driver == "start" else asyncio.create_task(_collect(executor))
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert executor.steer("discard steering")
        executor.queue("discard follow-up")
        assert executor.abort()
        assert not executor.abort()
        assert not executor.steer("rejected")
        with pytest.raises(RuntimeError, match="stopping"):
            executor.queue("rejected follow-up")
        with pytest.raises(RuntimeError, match="already running"):
            executor.start()
        assert not task.done()
        release.set()
        value = await asyncio.wait_for(task, 2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    steps = delivered if driver == "start" else value
    assert len(steps) == 1
    stopped = steps[0]
    assert stopped.state == "stopped" and stopped.is_final
    assert stopped.step_index == 1
    assert stopped.llm_response is None
    assert stopped.new_messages is context.new_messages
    assert stopped.model is primary.model
    primary.chat.assert_awaited_once()
    fallback.chat.assert_not_awaited()
    if phase == "tool":
        assert calls == ["tool", "tool finished"]
        assert [message.role for message in context.new_messages] == ["assistant", "tool"]
        assert len(context.new_messages[0].tool_calls) == 1
        assert context.new_messages[1].tool_call_id == "call-0"
    else:
        assert calls == ["model finished"]
        assert context.new_messages == []
    assert all("discard" not in str(message.content) for message in context.messages)
    assert not executor.abort()
    executor.model_group = [_model(lambda request: LLMResponse("fresh"))]
    result = await executor.queue("new task")
    assert result.state == "success"
    assert [message.content for message in result.new_messages] == ["new task", "fresh"]


@pytest.mark.anyio
@pytest.mark.parametrize("max_steps", [0, 1, 3])
async def test_abort_before_background_start_emits_stopped_without_model_call(max_steps):
    model = _model(lambda request: LLMResponse("unexpected"))
    callback = AsyncMock()
    executor = BaseAgentExecutor(
        [model], context=BaseAgentExecutionContext(), on_result=callback,
        config=AgentExecutionConfig(max_steps=max_steps),
    )
    task = executor.start()
    assert executor.abort()
    result = await task
    assert result.state == "stopped" and result.step_index == 0
    assert result.is_final and result.llm_response is None
    callback.assert_awaited_once_with(result)
    model.chat.assert_not_awaited()


@pytest.mark.anyio
async def test_abort_event_wakes_waiters_and_is_fresh_for_next_run():
    executor = BaseAgentExecutor(
        [_model(lambda request: LLMResponse("done"))], context=BaseAgentExecutionContext(),
    )
    task = executor.start()
    signal = executor._run_state.abort_requested
    assert isinstance(signal, asyncio.Event)
    assert not signal.is_set()
    waiter = asyncio.create_task(signal.wait())
    try:
        assert executor.abort()
        assert await asyncio.wait_for(waiter, 2)
        assert (await task).state == "stopped"

        next_task = executor.start()
        next_signal = executor._run_state.abort_requested
        assert next_signal is not signal
        assert not next_signal.is_set()
        assert (await next_task).state == "success"
        assert signal.is_set()
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
async def test_abort_between_steps_does_not_start_next_model_or_queued_turn(driver):
    model = _model(lambda request: _tool_response())
    executor = BaseAgentExecutor([model], context=BaseAgentExecutionContext())
    delivered = []

    async def on_result(result):
        delivered.append(result)
        if result.state == "success":
            executor.queue("discard")
            assert executor.abort()

    if driver == "start":
        executor.on_result = on_result
        result = await executor.start()
        assert result is delivered[-1]
    else:
        async for result in executor.run():
            await on_result(result)
    assert [result.state for result in delivered] == ["success", "stopped"]
    assert delivered[-1].step_index == 1
    model.chat.assert_awaited_once()


@pytest.mark.anyio
async def test_im_abort_preserves_event_and_finishes_current_tool(monkeypatch):
    from core.plugin.handlers import event_handler_reg

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *args, **kwargs: [])
    event = SimpleNamespace(sid="test:dm:user", is_stopped=False)
    calls = []

    class EventTool(BaseTool):
        name = "probe"

        async def execute(self, current_event):
            assert current_event is event
            calls.append("tool")
            assert executor.abort()
            return "done"

    context = AgentExecutionContext(event=event)
    executor = AgentExecutor(
        [_model(lambda request: _tool_response())], context=context,
        request=LLMRequest(tool_set=ToolSet([EventTool()])),
    )
    result = await executor.start()
    assert result.state == "stopped" and result.is_final
    assert calls == ["tool"]
    assert context.new_messages[-1].content == "done"
    assert not event.is_stopped


@pytest.mark.anyio
@pytest.mark.parametrize("hook_result", [False, True])
async def test_abort_from_response_hook_does_not_deliver_response_or_execute_tools(hook_result):
    class AbortHooks(AgentExecutionHooks):
        async def on_llm_response(self, ctx, response):
            assert executor.abort()
            return hook_result

    tool = AsyncMock(return_value="unexpected")
    executor = BaseAgentExecutor(
        [_model(lambda request: _tool_response())], context=BaseAgentExecutionContext(),
        hooks=AbortHooks(),
        request=LLMRequest(tool_set=ToolSet([SimpleNamespace(name="probe", execute=tool, get_schema=dict)])),
    )
    result = await executor.start()
    assert result.state == "stopped" and result.llm_response is None
    assert executor.context.messages == []
    tool.assert_not_awaited()


@pytest.mark.anyio
async def test_abort_during_result_callback_waits_for_callback_completion():
    entered, release = asyncio.Event(), asyncio.Event()
    delivered = []

    async def on_result(result):
        delivered.append(result)
        if result.state == "success":
            entered.set()
            await release.wait()

    executor = BaseAgentExecutor(
        [_model(lambda request: LLMResponse("done"))],
        context=BaseAgentExecutionContext(), on_result=on_result,
    )
    task = executor.start()
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert executor.abort()
        assert not task.done()
        release.set()
        result = await asyncio.wait_for(task, 2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert [item.state for item in delivered] == ["success", "stopped"]
    assert result is delivered[-1]
    assert executor.context.messages[0].content == "done"


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
@pytest.mark.parametrize("request_abort", [False, True])
async def test_abort_after_hook_stopped_result_emits_response_free_terminal_result(driver, request_abort):
    class StopHooks(AgentExecutionHooks):
        async def on_llm_response(self, ctx, response):
            return True

    response = _tool_response()
    model = _model(lambda request: response)
    delivered = []

    async def on_result(result):
        delivered.append(result)
        if len(delivered) == 1 and request_abort:
            assert executor.abort()
            assert executor.state == "stopping"

    executor = BaseAgentExecutor(
        [model], context=BaseAgentExecutionContext(), hooks=StopHooks(), on_result=on_result,
    )
    if driver == "start":
        final = await executor.start()
    else:
        async for final in executor.run():
            await on_result(final)

    assert delivered[0].state == "stopped"
    assert delivered[0].llm_response is response
    assert len(delivered) == (2 if request_abort else 1)
    assert final is delivered[-1]
    assert final.llm_response is (None if request_abort else response)
    assert final.state == "stopped" and final.is_final
    assert final.model is model.model and final.step_index == 1
    assert executor.context.messages == []
    assert response.tool_results == []
    assert executor.state == "done"
    model.chat.assert_awaited_once()
