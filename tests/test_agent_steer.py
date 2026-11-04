import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig
from core.agent.message import OpenAIMessage
from core.agent.tool import ToolSet
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


def _tool_response():
    return LLMResponse("working", tool_calls=[{
        "id": "call-1", "type": "function",
        "function": {"name": "probe", "arguments": "{}"},
    }])


async def _collect(executor, context):
    return [step async for step in executor.run(context)]


@asynccontextmanager
async def _running(executor, context, started, release):
    task = asyncio.create_task(_collect(executor, context))
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        yield task
    finally:
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), timeout=2)


@pytest.mark.anyio
async def test_steer_waits_for_model_then_records_ordered_copied_instructions():
    started, release = asyncio.Event(), asyncio.Event()
    seen = []
    late_accepted = []
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        if len(seen) == 1:
            started.set()
            await release.wait()
            return LLMResponse("initial response")
        late_accepted.append(executor.steer("too late"))
        return LLMResponse("steered response")

    context = _context(_model(chat))
    instruction = OpenAIMessage(role="user", content=[{"type": "text", "text": "second instruction"}])
    async with _running(executor, context, started, release) as task:
        assert executor.steer("first instruction")
        assert executor.steer(instruction)
        instruction.content[0]["text"] = "changed by caller"
        assert len(context.request.messages) == 1
        assert context.new_messages == []
        assert not task.done()

    steps = task.result()
    assert [step.is_final for step in steps] == [False, True]
    assert [message.role for message in context.new_messages] == ["assistant", "user", "user", "assistant"]
    assert seen[0] == [{"role": "user", "content": "original task"}]
    assert seen[1][1:4] == [
        {"role": "assistant", "content": "initial response"},
        {"role": "user", "content": "first instruction"},
        {"role": "user", "content": [{"type": "text", "text": "second instruction"}]},
    ]
    assert "final model call" in seen[1][-1]["content"]
    assert context.new_messages[1] is context.request.messages[2]
    assert late_accepted == [False]
    assert not executor.steer("after completion")


@pytest.mark.anyio
async def test_steer_during_tool_waits_for_paired_tool_result():
    started, release = asyncio.Event(), asyncio.Event()
    seen = []

    class ProbeTool(BaseTool):
        name = "probe"
        description = "Return a result."

        async def execute(self):
            started.set()
            await release.wait()
            return "tool result"

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        return _tool_response() if len(seen) == 1 else LLMResponse("complete")

    model = _model(chat)
    context = _context(model)
    executor = BaseAgentExecutor(ToolSet([ProbeTool()]), config=AgentExecutionConfig(max_steps=2))
    async with _running(executor, context, started, release) as task:
        assert executor.steer("new direction")
        assert not task.done()
        assert context.new_messages == []

    steps = task.result()
    assert len(steps) == 2
    assert [message.role for message in context.new_messages] == ["assistant", "tool", "user", "assistant"]
    assert seen[1][1]["tool_calls"][0]["id"] == seen[1][2]["tool_call_id"] == "call-1"
    assert seen[1][2]["content"] == "tool result"
    assert seen[1][3] == {"role": "user", "content": "new direction"}


@pytest.mark.anyio
async def test_steer_is_consumed_by_fallback_model():
    started, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def primary(request):
        started.set()
        await release.wait()
        raise ProviderAPIError("primary unavailable")

    async def fallback(request):
        seen.extend(deepcopy([message.to_dict() for message in request.messages]))
        return LLMResponse("complete")

    context = _context(_model(primary))
    context.model_group.append(_model(fallback))
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    async with _running(executor, context, started, release) as task:
        assert executor.steer("use the new direction")

    assert len(task.result()) == 1
    assert seen[-1] == {"role": "user", "content": "use the new direction"}
    assert context.new_messages[0].content == "use the new direction"


@pytest.mark.parametrize("same_context", [False, True])
@pytest.mark.anyio
async def test_one_executor_rejects_overlapping_runs_and_allows_serial_reuse(same_context):
    started, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        started.set()
        await release.wait()
        return LLMResponse("complete")

    context = _context(_model(chat))
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    async with _running(executor, context, started, release) as task:
        other = context if same_context else _context(_model(lambda request: LLMResponse("other")))
        with pytest.raises(RuntimeError, match="already running"):
            await _collect(executor, other)
        assert executor.steer("continue original")

    assert len(task.result()) == 2
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    steps = await _collect(executor, fresh)
    assert len(steps) == 1
    assert [message.content for message in fresh.new_messages] == ["fresh"]


@pytest.mark.parametrize("failure", ["provider", "programming", "cancel"])
@pytest.mark.anyio
async def test_steer_state_is_cleared_after_failure_or_cancellation(failure):
    started, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        started.set()
        await release.wait()
        if failure == "provider":
            raise ProviderAPIError("provider failed")
        raise TypeError("programming error")

    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    context = _context(_model(chat))
    async with _running(executor, context, started, release) as task:
        assert executor.steer("must not leak")
        if failure == "cancel":
            task.cancel()

    if failure == "provider":
        assert task.result()[0].state == "error"
    elif failure == "programming":
        with pytest.raises(TypeError, match="programming error"):
            task.result()
    else:
        assert task.cancelled()
    assert not executor.steer("inactive")
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    await _collect(executor, fresh)
    assert [message.content for message in fresh.new_messages] == ["fresh"]
    assert all(message.content != "must not leak" for message in fresh.request.messages)


@pytest.mark.anyio
async def test_steer_between_steps_and_generator_close_discard_pending_messages():
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    context = _context(_model(lambda request: _tool_response()))
    iterator = executor.run(context)
    try:
        first = await anext(iterator)
        assert not first.is_final
        assert executor.steer("discard when closed")
    finally:
        await iterator.aclose()

    assert not executor.steer("inactive")
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert len(await _collect(executor, fresh)) == 1
    assert all(message.content != "discard when closed" for message in fresh.request.messages)


@pytest.mark.anyio
async def test_steer_between_steps_is_applied_before_last_step_hint():
    responses = iter([_tool_response(), LLMResponse("complete")])
    context = _context(_model(lambda request: next(responses)))
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=2))
    iterator = executor.run(context)
    try:
        assert not (await anext(iterator)).is_final
        assert executor.steer("between steps")
        assert (await anext(iterator)).is_final
        assert not executor.steer("after final result")
    finally:
        await iterator.aclose()

    contents = [message.content for message in context.request.messages]
    assert contents[-3] == "between steps"
    assert "final model call" in contents[-2]
    assert contents[-1] == "complete"


@pytest.mark.anyio
async def test_steer_rejects_final_step_without_extending_budget():
    started, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        started.set()
        await release.wait()
        return LLMResponse("complete")

    model = _model(chat)
    context = _context(model)
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=1))
    async with _running(executor, context, started, release) as task:
        assert not executor.steer("no budget left")

    assert len(task.result()) == model.chat.await_count == 1
    assert [message.content for message in context.new_messages] == ["complete"]


@pytest.mark.parametrize("message, error", [
    (None, TypeError), (123, TypeError), ({"role": "user", "content": "text"}, TypeError),
    ("", ValueError), ("   ", ValueError),
    (OpenAIMessage(role="assistant", content="wrong role"), ValueError),
    (OpenAIMessage(role="user", content=[]), ValueError),
])
def test_steer_validates_instruction(message, error):
    with pytest.raises(error):
        BaseAgentExecutor().steer(message)


@pytest.mark.anyio
async def test_steer_does_not_queue_for_idle_or_zero_step_runs():
    executor = BaseAgentExecutor(config=AgentExecutionConfig(max_steps=0))
    model = _model(lambda request: LLMResponse("complete"))
    context = _context(model)
    assert not executor.steer("before start")
    assert await _collect(executor, context) == []
    assert not executor.steer("after completion")
    model.chat.assert_not_awaited()
    assert context.new_messages == []


@pytest.mark.anyio
async def test_stop_hook_discards_pending_steering_and_releases_executor():
    started, release = asyncio.Event(), asyncio.Event()

    class StopOnceExecutor(BaseAgentExecutor):
        async def _on_llm_response(self, ctx, response):
            return response.text_response == "stop"

    async def chat(request):
        started.set()
        await release.wait()
        return LLMResponse("stop")

    executor = StopOnceExecutor(config=AgentExecutionConfig(max_steps=2))
    context = _context(_model(chat))
    async with _running(executor, context, started, release) as task:
        assert executor.steer("discard on stop")

    assert task.result()[0].state == "stopped"
    assert context.new_messages == []
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert (await _collect(executor, fresh))[0].state == "success"
    assert [message.content for message in fresh.new_messages] == ["fresh"]


@pytest.mark.anyio
async def test_invalid_model_group_releases_executor_for_next_run():
    executor = BaseAgentExecutor()
    with pytest.raises(ValueError, match="model_group"):
        await _collect(executor, BaseAgentExecutionContext(request=LLMRequest(), model_group=[]))

    assert not executor.steer("inactive")
    fresh = _context(_model(lambda request: LLMResponse("fresh")))
    assert len(await _collect(executor, fresh)) == 1
