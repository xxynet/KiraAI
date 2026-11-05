import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.agent.config import AgentExecutionConfig
from core.agent.hooks import AgentExecutionHooks
from core.agent.message import OpenAIMessage
from core.provider import LLMRequest, LLMResponse


def _model(callback):
    return SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_name="test", model_id="test"),
        chat=AsyncMock(side_effect=callback),
    )


def _context(executor, model):
    executor.model_group = [model]
    executor.context.messages[:] = [OpenAIMessage(role="user", content="original task")]
    executor.context.new_messages = []
    return executor.context


async def _collect(executor, context):
    assert executor.context is context
    return [step async for step in executor.run()]


def _tool_response():
    return LLMResponse("working", tool_calls=[{
        "id": "call-1", "function": {"name": "missing", "arguments": "{}"},
    }])


@pytest.mark.parametrize("literal_hint", [False, True])
@pytest.mark.anyio
async def test_idle_queue_resumes_clean_history_and_callback_with_new_turn_messages(literal_hint):
    seen, delivered = [], []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=1), context=BaseAgentExecutionContext())
    hint = executor._get_final_step_hint() + "\n"

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        return LLMResponse(f"reply {len(seen)}")

    async def on_result(result):
        delivered.append(result)

    context = _context(executor, _model(chat))
    if literal_hint:
        context.messages.insert(0, OpenAIMessage(role="user", content=hint))
    executor.on_result = on_result
    first = await executor.start()
    assert context.new_messages is first.new_messages
    task = executor.queue(OpenAIMessage(role="user", content="follow-up"))
    assert isinstance(task, asyncio.Task)
    second = await task

    assert delivered == [first, second]
    assert first.step_index == second.step_index == 1
    assert first.is_final and second.is_final
    assert seen[1][-2:] == [
        {"role": "user", "content": "follow-up"},
        {"role": "user", "content": hint},
    ]
    assert {"role": "assistant", "content": "reply 1"} in seen[1]
    assert sum(message["content"] == hint for message in seen[1]) == (2 if literal_hint else 1)
    assert [message.content for message in first.new_messages] == ["reply 1"]
    assert [message.content for message in second.new_messages] == ["follow-up", "reply 2"]
    assert first.new_messages is not second.new_messages
    assert context.new_messages is second.new_messages
    assert any(first.new_messages[0] is message for message in context.messages)
    assert [message.content for message in context.messages][-3:] == ["reply 1", "follow-up", "reply 2"]


@pytest.mark.anyio
async def test_active_queue_waits_fifo_and_refreshes_budget_without_changing_current_turn():
    started, release = asyncio.Event(), asyncio.Event()
    seen, delivered = [], []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=2), context=BaseAgentExecutionContext())

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        if len(seen) == 1:
            started.set()
            await release.wait()
        return _tool_response()

    async def on_result(result):
        delivered.append(result)

    context = _context(executor, _model(chat))
    executor.on_result = on_result
    task = executor.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert executor.queue("first follow-up") is task
        assert executor.queue("second follow-up") is task
        assert executor.steer("steer current turn")
        executor.config = AgentExecutionConfig(max_steps=3)
        assert context.messages[1:] == []
        release.set()
        result = await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert result is delivered[-1]
    assert [step.step_index for step in delivered] == [1, 2, 1, 2, 3, 1, 2, 3]
    assert [step.is_final for step in delivered] == [False, True, False, False, True, False, False, True]
    assert {"role": "user", "content": "steer current turn"} in seen[1]
    assert all(message["content"] != "first follow-up" for message in seen[1])
    assert {"role": "user", "content": "first follow-up"} in seen[2]
    assert all(message["content"] != "second follow-up" for message in seen[4])
    assert {"role": "user", "content": "second follow-up"} in seen[5]
    assert delivered[1].new_messages is not delivered[2].new_messages
    assert delivered[4].new_messages is not delivered[5].new_messages
    assert context.new_messages is result.new_messages
    assert len(delivered[1].new_messages) == 5
    assert [message.content for message in delivered[1].new_messages if message.role == "user"] == [
        "steer current turn",
    ]
    for index, messages in enumerate(seen):
        hints = [message for message in messages if "final model call" in str(message["content"])]
        assert len(hints) == (1 if index in (1, 4, 7) else 0)


@pytest.mark.anyio
async def test_queue_from_final_callback_runs_another_turn_in_same_task():
    delivered = []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=1), context=BaseAgentExecutionContext())

    async def on_result(result):
        delivered.append(result)
        if len(delivered) == 1:
            assert executor.queue("from callback") is asyncio.current_task()

    _context(executor, _model(lambda request: LLMResponse("complete")))
    executor.on_result = on_result
    result = await executor.start()

    assert len(delivered) == 2
    assert all(step.is_final and step.step_index == 1 for step in delivered)
    assert result is delivered[-1]
    assert delivered[-1].new_messages[0].content == "from callback"


@pytest.mark.anyio
async def test_queue_before_initial_start_copies_inputs_and_uses_configured_context():
    delivered = []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=1), context=BaseAgentExecutionContext())

    async def on_result(result):
        delivered.append(result)

    context = _context(executor, _model(lambda request: LLMResponse("complete")))
    executor.on_result = on_result
    message = OpenAIMessage(role="user", content=[{"type": "text", "text": "queued before start"}])
    task = executor.queue(message)
    assert isinstance(task, asyncio.Task)
    message.content[0]["text"] = "changed by caller"
    result = await task
    assert delivered == [result]
    assert result.new_messages is context.new_messages
    assert result.new_messages[0].content == [{"type": "text", "text": "queued before start"}]


@pytest.mark.anyio
async def test_caller_driven_run_drains_queue_and_preserves_registered_callback():
    callback = AsyncMock()
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=1), on_result=callback, context=BaseAgentExecutionContext())
    calls = 0

    async def chat(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            assert executor.queue("follow-up during run") is None
        return LLMResponse("complete")

    context = _context(executor, _model(chat))
    steps = await _collect(executor, context)
    assert len(steps) == 2
    assert steps[1].new_messages[0].content == "follow-up during run"
    callback.assert_not_awaited()
    assert executor.on_result is callback
    result = await executor.queue("after run")
    assert result.new_messages[0].content == "after run"
    assert callback.await_count == 1


@pytest.mark.anyio
async def test_queued_turn_takes_latest_config_after_zero_step_initial_turn():
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=0), context=BaseAgentExecutionContext())
    model = _model(lambda request: LLMResponse("complete"))
    _context(executor, model)
    task = executor.start()
    assert executor.queue("queued work") is task
    executor.config = AgentExecutionConfig(max_steps=1)
    result = await task
    assert result.is_final and result.step_index == 1
    assert result.new_messages[0].content == "queued work"
    model.chat.assert_awaited_once()


@pytest.mark.parametrize("outcome", ["cancel", "exception"])
@pytest.mark.anyio
async def test_aborted_background_task_discards_waiting_followups(monkeypatch, outcome):
    from core.agent import base_agent_executor

    monkeypatch.setattr(base_agent_executor.logger, "error", Mock())
    started, release = asyncio.Event(), asyncio.Event()
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=2), context=BaseAgentExecutionContext())

    async def chat(request):
        started.set()
        await release.wait()
        raise TypeError("model failed")

    model = _model(chat)
    _context(executor, model)
    task = executor.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        executor.queue("discard on abort")
        if outcome == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            release.set()
            with pytest.raises(TypeError, match="model failed"):
                await task
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    model.chat.assert_awaited_once()
    fresh = _context(executor, _model(lambda request: LLMResponse("fresh")))
    result = await executor.start()
    assert result.new_messages == fresh.messages[1:]
    assert [message.content for message in fresh.messages[1:]] == ["fresh"]


@pytest.mark.anyio
async def test_stopped_turn_discards_followups_queued_by_result_callback():
    class StopHooks(AgentExecutionHooks):
        async def on_llm_response(self, ctx, response):
            return True

    executor = BaseAgentExecutor([], context=BaseAgentExecutionContext(), hooks=StopHooks())
    delivered = []

    async def on_result(result):
        delivered.append(result)
        executor.queue("discard on stop")

    model = _model(lambda request: LLMResponse("stop"))
    executor.on_result = on_result
    _context(executor, model)
    result = await executor.start()
    assert result.state == "stopped"
    assert len(delivered) == 1
    model.chat.assert_awaited_once()


@pytest.mark.anyio
async def test_closing_foreground_generator_discards_waiting_followups():
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=2), context=BaseAgentExecutionContext())
    _context(executor, _model(lambda request: _tool_response()))
    iterator = executor.run()
    try:
        assert not (await anext(iterator)).is_final
        assert executor.queue("discard on close") is None
    finally:
        await iterator.aclose()

    fresh = _context(executor, _model(lambda request: LLMResponse("fresh")))
    result = await executor.start()
    assert result.new_messages == fresh.messages[1:]
    assert [message.content for message in fresh.messages[1:]] == ["fresh"]


@pytest.mark.anyio
async def test_idle_queue_before_old_done_callback_does_not_release_new_task():
    loop = asyncio.get_running_loop()
    next_task = loop.create_future()
    started, release = asyncio.Event(), asyncio.Event()
    delivered = []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=2), context=BaseAgentExecutionContext())
    calls = 0

    async def chat(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            started.set()
            await release.wait()
        return LLMResponse("complete")

    def enqueue():
        next_task.set_result(executor.queue("scheduled follow-up"))

    async def on_result(result):
        delivered.append(result)
        if len(delivered) == 1:
            loop.call_soon(enqueue)

    _context(executor, _model(chat))
    executor.on_result = on_result
    await executor.start()
    task = await next_task
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        with pytest.raises(RuntimeError, match="already running"):
            executor.start()
        assert executor.steer("still belongs to new task")
        release.set()
        await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls == 3
    assert delivered[-1].new_messages[2].content == "still belongs to new task"


@pytest.mark.parametrize("message, error", [
    (None, TypeError), (123, TypeError),
    ("", ValueError), ("   ", ValueError),
    (OpenAIMessage(role="assistant", content="wrong role"), ValueError),
])
def test_queue_validates_user_instructions(message, error):
    with pytest.raises(error):
        BaseAgentExecutor([], context=BaseAgentExecutionContext()).queue(message)


@pytest.mark.anyio
async def test_im_foreground_context_retains_event_and_prepared_request_options(monkeypatch):
    from core.agent.agent_executor import AgentExecutionContext, AgentExecutor
    from core.agent.tool import ToolSet
    from core.plugin.handlers import EventType, event_handler_reg

    event = SimpleNamespace(sid="test:dm:user", is_stopped=False)
    hook = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=hook)] if event_type == EventType.ON_LLM_RESPONSE else []
    ))
    requests = []

    async def chat(request):
        requests.append(request)
        return LLMResponse("complete")

    tools = ToolSet()
    request = LLMRequest(messages=[OpenAIMessage(role="user", content="original task")],
                          tool_set=tools, tool_choice="none")
    context = AgentExecutionContext(event=event, messages=request.messages)
    executor = AgentExecutor([_model(chat)], context=context, request=request, config=AgentExecutionConfig(max_steps=1))
    first = [step async for step in executor.run()]
    context.append_messages(OpenAIMessage(role="user", content="next task"))
    second = [step async for step in executor.run()]

    assert len(first) == len(second) == 1
    assert second[0].new_messages[0].content == "complete"
    assert requests[0] is not request and requests[1] is not requests[0]
    assert requests[1].tool_set.tools == tools.tools
    assert requests[1].tool_choice == "none"
    assert hook.await_count == 2
    assert all(call.args[0] is event for call in hook.await_args_list)
    assert all("final model call" not in str(message.content) for message in context.messages)


@pytest.mark.anyio
async def test_queue_during_final_model_call_runs_next_turn_with_fresh_budget():
    started, release = asyncio.Event(), asyncio.Event()
    seen, delivered = [], []
    executor = BaseAgentExecutor([], config=AgentExecutionConfig(max_steps=1), context=BaseAgentExecutionContext())

    async def chat(request):
        seen.append(deepcopy([message.to_dict() for message in request.messages]))
        if len(seen) == 1:
            started.set()
            await release.wait()
        return LLMResponse("complete")

    async def on_result(result):
        delivered.append(result)

    executor.on_result = on_result
    _context(executor, _model(chat))
    task = executor.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not executor.steer("cannot extend current turn")
        assert executor.queue("next turn") is task
        release.set()
        result = await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert result is delivered[-1]
    assert len(delivered) == 2
    assert all(step.is_final and step.step_index == 1 for step in delivered)
    assert all(message["content"] != "next turn" for message in seen[0])
    assert seen[1][-2] == {"role": "user", "content": "next turn"}


@pytest.mark.anyio
async def test_cancelling_followup_turn_releases_slot_and_keeps_completed_session_history():
    started, release = asyncio.Event(), asyncio.Event()
    delivered = []
    calls = 0

    async def chat(request):
        nonlocal calls
        calls += 1
        if calls == 2:
            started.set()
            await release.wait()
        return LLMResponse("complete")

    async def on_result(result):
        delivered.append(result)
        if len(delivered) == 1:
            executor.queue("cancel this follow-up")
            executor.queue("must not execute")

    context = BaseAgentExecutionContext(messages=[OpenAIMessage(role="user", content="original task")])
    executor = BaseAgentExecutor([_model(chat)], context=context, config=AgentExecutionConfig(max_steps=1), on_result=on_result)
    task = executor.start()
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls == 2
    assert len(delivered) == 1
    assert [message.content for message in context.messages] == [
        "original task", "complete", "cancel this follow-up",
    ]
    assert all("final model call" not in str(message.content) for message in context.messages)
    executor.model_group = [_model(lambda request: LLMResponse("resumed"))]
    result = await executor.queue("resume")
    assert result.new_messages is context.new_messages
    assert [message.content for message in result.new_messages] == ["resume", "resumed"]
    assert [message.content for message in context.messages][-2:] == ["resume", "resumed"]
