import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.chat import KiraCommentEvent, KiraMessageEvent
from core.chat.message_elements import Text
from core.event_bus import EventBus
from core.chat.session_buffer import SessionBuffer


def _make_buffer(messages):
    buffer = SessionBuffer()
    for message in messages:
        buffer.add(message)
    return buffer


def test_session_buffer_flush_with_filter():
    buffer = _make_buffer([1, 2, 3, 4])

    flushed = buffer.flush(filter_fn=lambda message: message % 2 == 0)

    assert flushed == [2, 4]
    assert buffer.buffer == [1, 3]


def test_session_buffer_filter_takes_precedence_over_count():
    buffer = _make_buffer([1, 2, 3, 4, 6])

    flushed = buffer.flush(count=2, filter_fn=lambda message: message % 2 == 0)

    assert flushed == [2, 4, 6]
    assert buffer.buffer == [1, 3]


def test_session_buffer_flush_with_count_when_filter_is_missing():
    buffer = _make_buffer([1, 2, 3, 4])

    flushed = buffer.flush(count=2)

    assert flushed == [1, 2]
    assert buffer.buffer == [3, 4]


def test_session_buffer_flushes_all_by_default():
    buffer = _make_buffer([1, 2, 3])

    flushed = buffer.flush()

    assert flushed == [1, 2, 3]
    assert buffer.buffer == []


def test_session_buffer_flush_with_filter_keeps_buffer_when_none_match():
    buffer = _make_buffer([1, 3, 5])

    flushed = buffer.flush(filter_fn=lambda message: message % 2 == 0)

    assert flushed == []
    assert buffer.buffer == [1, 3, 5]


def _comment_event():
    return KiraCommentEvent(
        platform="test", adapter_name="test", commenter_id="user",
        commenter_nickname="User", self_id="bot", timestamp=1,
        comment_id="comment", comment_content=[Text("hello")], target=None,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("is_comment", [False, True])
async def test_event_bus_records_telemetry_only_for_im(is_comment):
    db = SimpleNamespace(add_telemetry_message=AsyncMock())
    bus = EventBus(Mock(), asyncio.Queue(), db=db)
    event = _comment_event() if is_comment else object.__new__(KiraMessageEvent)
    if not is_comment:
        event.adapter = SimpleNamespace(platform="test")
    dispatched = asyncio.Event()

    async def handler(received):
        assert received is event
        dispatched.set()

    bus.subscribe(type(event), handler)
    await bus.publish(event)
    task = asyncio.create_task(bus.dispatch())
    try:
        await asyncio.wait_for(dispatched.wait(), timeout=2)
    finally:
        await bus.stop()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert bus.total_messages_stats["total_messages"] == 1
    if is_comment:
        db.add_telemetry_message.assert_not_awaited()
    else:
        db.add_telemetry_message.assert_awaited_once()
        assert db.add_telemetry_message.await_args.args[1] == "test"


@pytest.mark.anyio
@pytest.mark.parametrize("already_stopped", [False, True])
async def test_comment_subscription_respects_stop_and_releases_shared_limit(monkeypatch, already_stopped):
    from core.message_manager import MessageProcessor
    from core.plugin.handlers import EventType, event_handler_reg

    semaphore = asyncio.Semaphore(1)
    processor = MessageProcessor(SimpleNamespace(message_processing_semaphore=semaphore))
    event = _comment_event()
    if already_stopped:
        event.stop()

    async def stop(received):
        assert semaphore.locked()
        received.stop()

    first = AsyncMock(side_effect=stop)
    second = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=first), SimpleNamespace(exec_handler=second)]
        if event_type == EventType.ON_COMMENT else []
    ))
    bus = EventBus(Mock(), asyncio.Queue())
    bus.subscribe(KiraCommentEvent, processor.handle_cmt_event)
    await bus._process_event(event)

    assert first.await_count == (0 if already_stopped else 1)
    second.assert_not_awaited()
    assert not semaphore.locked()
    assert bus.event_bus_stats["errors"] == 0
