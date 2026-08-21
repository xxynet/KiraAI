import asyncio
from types import SimpleNamespace

import pytest

from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin


def _chat_plugin(flushed: list[str]) -> DefaultChatPlugin:
    async def flush_session_messages(sid: str) -> None:
        flushed.append(sid)

    ctx = SimpleNamespace(
        config={"bot_config": {"bot": {"max_message_interval": 0.01, "max_buffer_messages": 3}}},
        message_processor=SimpleNamespace(
            get_session_buffer_length=lambda sid: 1,
            flush_session_messages=flush_session_messages,
        ),
    )
    return DefaultChatPlugin(ctx, {})


@pytest.mark.anyio
async def test_terminate_cancels_debounce_tasks_and_clears_sessions():
    flushed: list[str] = []
    plugin = _chat_plugin(flushed)

    for sid in ("test:dm:1", "test:group:2"):
        plugin.session_events[sid] = asyncio.Event()
        plugin.session_tasks[sid] = asyncio.create_task(plugin._debounce_loop(sid))
    await asyncio.sleep(0)
    tasks = list(plugin.session_tasks.values())

    await plugin.terminate()

    assert plugin.session_tasks == {}
    assert plugin.session_events == {}
    assert all(task.done() for task in tasks)


@pytest.mark.anyio
async def test_terminate_stops_pending_flush():
    flushed: list[str] = []
    plugin = _chat_plugin(flushed)
    sid = "test:dm:1"
    plugin.session_events[sid] = asyncio.Event()
    plugin.session_tasks[sid] = asyncio.create_task(plugin._debounce_loop(sid))
    plugin.session_events[sid].set()
    await asyncio.sleep(0)

    await plugin.terminate()
    await asyncio.sleep(0.05)

    assert flushed == []


@pytest.mark.anyio
async def test_repeated_terminate_is_safe():
    plugin = _chat_plugin([])
    plugin.session_events["test:dm:1"] = asyncio.Event()
    plugin.session_tasks["test:dm:1"] = asyncio.create_task(plugin._debounce_loop("test:dm:1"))

    await plugin.terminate()
    await plugin.terminate()

    assert plugin.session_tasks == {}
