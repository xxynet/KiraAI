import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin


def _plugin():
    ctx = SimpleNamespace(
        config={"bot_config": {"bot": {"max_message_interval": 0}}},
        get_buffer=lambda _sid: SimpleNamespace(get_length=lambda: 1),
        flush_session_messages=AsyncMock(),
    )
    plugin = DefaultChatPlugin(ctx, {})
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

    plugin.ctx.flush_session_messages.assert_awaited_once_with(sid)
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

@pytest.mark.anyio
async def test_buffer_threshold_uses_updated_bot_config():
    plugin = _plugin()
    event = SimpleNamespace(
        message=SimpleNamespace(chain=[]), is_mentioned=True,
        session=SimpleNamespace(sid="test:dm:1"), buffer=Mock(), flush=Mock(),
    )
    try:
        await plugin.handle_msg(event)
        event.flush.assert_not_called()
        plugin.ctx.config["bot_config"]["bot"] = {"max_buffer_messages": 2}
        await plugin.handle_msg(event)
        event.flush.assert_called_once()
    finally:
        await plugin.terminate()


@pytest.mark.anyio
async def test_debounce_uses_current_interval_when_wait_begins(monkeypatch):
    plugin = _plugin()
    sid = "test:dm:1"
    trigger = asyncio.Event()
    task = asyncio.create_task(plugin._debounce_loop(sid, trigger))
    plugin.session_events[sid] = trigger
    plugin.session_tasks[sid] = task
    await asyncio.sleep(0)
    plugin.ctx.config["bot_config"]["bot"] = {"max_message_interval": "0.25"}
    sleep = AsyncMock()
    monkeypatch.setattr("core.plugin.builtin_plugins.chat.main.asyncio.sleep", sleep)
    trigger.set()
    await task

    sleep.assert_awaited_once_with(0.25)
    plugin.ctx.flush_session_messages.assert_awaited_once_with(sid)


@pytest.mark.parametrize("name,value", [
    ("max_unmentioned_messages", 2),
    ("receive_unmentioned", False),
    ("group_chat_prompt", "updated"),
    ("group_proactive_chat", True),
    ("group_proactive_chat_probability", 0.75),
    ("waking_words", ["wake"]),
])
def test_chat_properties_use_replaced_plugin_config(name, value):
    plugin = _plugin()
    plugin.plugin_cfg = {name: value}
    assert getattr(plugin, name) == value
