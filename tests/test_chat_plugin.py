import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin


def _plugin():
    processor = SimpleNamespace(
        get_session_buffer_length=lambda _sid: 1,
        flush_session_messages=AsyncMock(),
    )
    ctx = SimpleNamespace(
        config={"bot_config": {"bot": {}}},
        message_processor=processor,
    )
    plugin = DefaultChatPlugin(ctx, {})
    plugin.debounce_interval = 0
    return plugin


@pytest.mark.anyio
async def test_terminate_cancels_pending_debounce_tasks():
    plugin = _plugin()
    sid = "test:dm:1"
    event = asyncio.Event()
    task = asyncio.create_task(plugin._debounce_loop(sid, event))
    plugin.session_events[sid] = event
    plugin.session_tasks[sid] = task
    await asyncio.sleep(0)

    await plugin.terminate()

    assert task.done()
    assert task.cancelled()
    assert plugin.session_tasks == {}
    assert plugin.session_events == {}


@pytest.mark.anyio
async def test_completed_debounce_task_releases_session_state():
    plugin = _plugin()
    sid = "test:dm:1"
    event = asyncio.Event()
    event.set()
    task = asyncio.create_task(plugin._debounce_loop(sid, event))
    plugin.session_events[sid] = event
    plugin.session_tasks[sid] = task

    await task

    plugin.ctx.message_processor.flush_session_messages.assert_awaited_once_with(sid)
    assert sid not in plugin.session_tasks
    assert sid not in plugin.session_events


@pytest.mark.anyio
async def test_terminate_rejects_messages_arriving_during_cleanup():
    plugin = _plugin()
    sid = "test:dm:1"
    cancellation_received = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_termination():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_received.set()
            await release.wait()
            raise

    task = asyncio.create_task(wait_for_termination())
    plugin.session_events[sid] = asyncio.Event()
    plugin.session_tasks[sid] = task
    terminate_task = asyncio.create_task(plugin.terminate())
    await cancellation_received.wait()

    event = SimpleNamespace(buffer=Mock(), flush=Mock())
    try:
        await plugin.handle_msg(event)
        event.buffer.assert_not_called()
        event.flush.assert_not_called()
        assert plugin.session_tasks == {}
        assert plugin.session_events == {}
    finally:
        release.set()

    await terminate_task
