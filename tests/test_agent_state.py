import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.provider import LLMResponse


def _executor(chat, **kwargs):
    model = SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_name="test"),
        chat=AsyncMock(side_effect=chat),
    )
    return BaseAgentExecutor([model], context=BaseAgentExecutionContext(), **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("driver", ["run", "start"])
async def test_state_covers_queued_turns_and_remains_done_after_completion(driver):
    seen = []

    async def chat(request):
        seen.append(executor.state)
        if len(seen) == 1:
            executor.queue("follow-up")
        return LLMResponse("done")

    async def on_result(result):
        assert executor.state == "running"

    executor = _executor(chat, on_result=on_result)
    assert executor.state == "idle"
    with pytest.raises(AttributeError):
        executor.state = "done"
    if driver == "start":
        task = executor.start()
        assert executor.state == "running"
        await task
    else:
        async for result in executor.run():
            await on_result(result)
    assert seen == ["running", "running"]
    assert executor._run_state is None
    assert executor.state == "done"
    task = executor.queue("another run")
    assert executor.state == "running"
    await task
    assert executor.state == "done"


@pytest.mark.anyio
async def test_abort_state_waits_for_call_to_finish():
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()
        return LLMResponse("done")

    executor = _executor(chat)
    task = executor.start()
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert executor.abort()
        assert executor.state == "stopping"
        assert not executor.abort()
        assert executor.state == "stopping"
        release.set()
        assert (await asyncio.wait_for(task, 2)).state == "stopped"
        assert executor.state == "done"
    finally:
        release.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.anyio
@pytest.mark.parametrize("before_start", [False, True])
async def test_cancelled_task_finishes_lifecycle(before_start):
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()

    executor = _executor(chat)
    task = executor.start()
    if not before_start:
        await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert executor.state == "done"


@pytest.mark.anyio
@pytest.mark.parametrize("phase", ["model", "callback"])
async def test_failures_finish_lifecycle_and_allow_reuse(monkeypatch, phase):
    from core.agent import base_agent_executor

    monkeypatch.setattr(base_agent_executor.logger, "error", Mock())

    async def chat(request):
        if phase == "model":
            raise ValueError("failed")
        return LLMResponse("done")

    executor = _executor(chat)
    if phase == "callback":
        executor.on_result = AsyncMock(side_effect=ValueError("failed"))
    with pytest.raises(ValueError, match="failed"):
        await executor.start()
    assert executor.state == "done"


@pytest.mark.anyio
async def test_task_creation_failure_restores_previous_lifecycle(monkeypatch):
    executor = _executor(lambda request: LLMResponse("done"))
    for expected in ("idle", "done"):
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "create_task", Mock(side_effect=RuntimeError("failed")))
            with pytest.raises(RuntimeError, match="failed"):
                executor.start()
        assert executor.state == expected
        await executor.start()


@pytest.mark.anyio
async def test_closing_foreground_iterator_finishes_lifecycle():
    executor = _executor(lambda request: LLMResponse("done"))
    iterator = executor.run()
    await anext(iterator)
    assert executor.state == "running"
    await iterator.aclose()
    assert executor.state == "done"
