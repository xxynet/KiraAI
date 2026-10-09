import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.image_desc_cache import ImageDescCache
from core.chat.session_buffer import SessionBufferManager
from core.workflow.src.im.message_delivery import MessageDeliveryService
from core.chat.message_elements import Forward, Image, Reply, Sticker, Text
from core.workflow.src.im.message_formatter import MessageFormatter
from core.chat.message_history import MessageHistoryService
from core.workflow.src.im.native_content import MessageMediaService
from core.chat.message_utils import KiraIMMessage, KiraMessageEvent, MessageChain
from core.chat.session import User
from core.config.config_loader import KiraConfig
from core.message_manager import MessageProcessor
from core.plugin.plugin_context import PluginContext
from core.workflow.src.im.batching import publish_buffered_messages


def test_delivery_delays_follow_config_changes():
    config = dict.__new__(KiraConfig)
    delivery = MessageDeliveryService(config, Mock())

    assert delivery.min_message_delay == 0.8
    assert delivery.max_message_delay == 1.5

    config["bot_config"] = {"bot": {"min_message_delay": "0.1", "max_message_delay": "0.2"}}
    assert delivery.min_message_delay == 0.1
    assert delivery.max_message_delay == 0.2

    config["bot_config"]["bot"] = {"min_message_delay": 0, "max_message_delay": 0.5}
    assert delivery.min_message_delay == 0
    assert delivery.max_message_delay == 0.5


def test_plugin_context_exposes_services_without_processor_dependency():
    history = MessageHistoryService(Mock(), Mock())
    prompt_manager, skills_manager, mcp_manager = Mock(), Mock(), Mock()
    cache = ImageDescCache(history.db)
    context = PluginContext(
        db=history.db, config=Mock(), event_bus=Mock(), provider_mgr=Mock(),
        tool_mgr=Mock(), adapter_mgr=Mock(), persona_mgr=Mock(),
        sticker_mgr=Mock(), session_mgr=history.session_manager,
        message_processor=SimpleNamespace(), message_history=history,
        prompt_mgr=prompt_manager, skills_mgr=skills_manager, mcp_mgr=mcp_manager,
        image_desc_cache=cache,
    )

    assert context.image_desc_cache is cache
    assert context.message_history is history
    assert context.prompt_mgr is prompt_manager
    assert context.skills_mgr is skills_manager
    assert context.mcp_mgr is mcp_manager
    assert context.sticker_manager is context.sticker_mgr


def make_event(identity="one"):
    return KiraMessageEvent(
        supported_elements=["text"], timestamp=1,
        adapter=AdapterInfo(True, "test", "adapter", "test"),
        message=KiraIMMessage(
            message_id=identity, self_id="bot", timestamp=1,
            sender=User("user"), chain=MessageChain([Text(identity)]),
        ),
    )


@pytest.mark.anyio
async def test_compatibility_entry_points_share_buffer_and_send_lock():
    config = dict.__new__(KiraConfig)
    config.update({"bot_config": {"bot": {
        "max_message_interval": 1,
        "max_buffer_messages": 10,
        "min_message_delay": 0.1,
        "max_message_delay": 0.2,
    }}})
    history = MessageHistoryService(Mock(), Mock())
    cache = ImageDescCache(history.db)
    processor = MessageProcessor(Mock(), config, Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock(),
                                 message_history=history, image_desc_cache=cache)
    processor.event_bus = SimpleNamespace(publish=AsyncMock())
    services = processor.im_workflow.ctx
    event = make_event()
    sid = event.session.sid

    assert services.message_buffer is processor.session_buffer
    assert services.message_formatter is processor.message_formatter
    assert services.message_formatter.image_desc_cache is processor.image_desc_cache is cache
    assert processor.message_history is history
    assert services.message_history is history
    assert services.message_delivery.message_history is history
    assert not hasattr(services, "processor")
    assert processor.message_delivery.min_message_delay == 0.1
    config["bot_config"]["bot"]["max_message_delay"] = 0
    assert services.message_delivery.max_message_delay == 0

    services.message_buffer.get_buffer(sid).add(event)
    assert processor.get_session_buffer_length(sid) == 1
    assert await processor.flush_session_messages(sid)
    assert processor.get_session_buffer_length(sid) == 0
    assert processor.event_bus.publish.await_args.args[0].messages == [event.message]

    acquired = asyncio.Event()

    async def service_sender():
        async with services.message_delivery.get_session_lock(sid):
            acquired.set()

    lock = processor.get_session_lock(sid)
    assert lock is processor.session_locks[sid]
    async with lock:
        task = asyncio.create_task(service_sender())
        await asyncio.sleep(0)
        assert not acquired.is_set()
    await asyncio.wait_for(task, timeout=1)
    assert acquired.is_set()


@pytest.mark.anyio
async def test_buffer_filter_preserves_remaining_events_and_uses_last_matched_metadata():
    manager = SessionBufferManager()
    first, second, third = (make_event(name) for name in ("first", "second", "third"))
    sid = first.session.sid
    for event in (first, second):
        manager.get_buffer(sid).add(event)
    bus = SimpleNamespace(publish=AsyncMock())

    assert await publish_buffered_messages(
        manager, bus, sid, extra_event=third, filter_fn=lambda event: event is not second,
    )
    published = bus.publish.await_args.args[0]
    assert published.messages == [first.message, third.message]
    assert published.session is third.session
    assert manager.get_buffer(sid).buffer == [second]
    assert not await publish_buffered_messages(manager, bus, sid, filter_fn=lambda event: False)
    assert bus.publish.await_count == 1


@pytest.mark.anyio
async def test_formatter_native_mode_recurses_without_calling_vlm():
    config = SimpleNamespace(get_config=lambda key, default=None: default)
    provider = Mock()
    cache = SimpleNamespace(get=AsyncMock(), set=AsyncMock())
    formatter = MessageFormatter(config, provider_mgr=provider, image_desc_cache=cache)
    image, sticker = Image("data:image/png;base64,aGVsbG8="), Sticker(sticker="data:image/png;base64,aGVsbG8=")
    chain = MessageChain([
        Reply("quoted", chain=MessageChain([image])),
        Forward(chains=[MessageChain([sticker])]),
    ])

    result = await formatter.format_to_text(chain, capabilities={"image_recognition": {"mode": "native"}})

    assert "[Reply ID: quoted content: [Image attached]]" in result
    assert "[Forward [Sticker attached]]" in result
    provider.get_default_vlm.assert_not_called()
    cache.get.assert_not_awaited()


@pytest.mark.anyio
async def test_formatter_reuses_cached_description_without_calling_vlm(tmp_path):
    config = SimpleNamespace(get_config=lambda key, default=None: default)
    provider = Mock()
    cache = SimpleNamespace(get=AsyncMock(return_value="cached caption"), set=AsyncMock())
    formatter = MessageFormatter(config, provider_mgr=provider, image_desc_cache=cache)
    image = Image("data:image/png;base64,aGVsbG8=")
    image.hash_image = AsyncMock(return_value="hash")
    image.to_path = AsyncMock(return_value=str(tmp_path / "image.png"))

    result = await formatter.format_to_text(MessageChain([image]))

    assert "cached caption" in result
    cache.get.assert_awaited_once_with("hash")
    provider.get_default_vlm.assert_not_called()
    cache.set.assert_not_awaited()


@pytest.mark.anyio
async def test_native_media_keeps_nested_order_and_continues_after_one_failure(monkeypatch):
    first, second, third = (Image("data:image/png;base64,aGVsbG8=") for _ in range(3))
    message = SimpleNamespace(
        message_id="message-id", message_str="text",
        chain=MessageChain([
            first, Reply("reply", chain=MessageChain([second])),
            Forward(chains=[MessageChain([third])]),
        ]),
    )
    refs = [{"type": "kira_image_ref", "path": name} for name in ("first", "third")]
    persist = AsyncMock(side_effect=[refs[0], ValueError("unavailable"), refs[1]])
    monkeypatch.setattr("core.workflow.src.im.native_content.store_session_media", persist)

    result = await MessageMediaService().build_native_content(message, "adapter:dm:user")

    assert result == [{"type": "text", "text": "text"}, *refs]
    assert [call.args[0] for call in persist.await_args_list] == [first, second, third]


@pytest.mark.anyio
async def test_incoming_archive_failure_is_nonfatal_but_cancellation_propagates():
    history = MessageHistoryService(Mock(), Mock())
    history.record_incoming = AsyncMock(side_effect=RuntimeError("database unavailable"))
    assert await history.record_incoming_safely(object(), "adapter:dm:user", "test") is None

    history.record_incoming.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await history.record_incoming_safely(object(), "adapter:dm:user", "test")


@pytest.mark.anyio
async def test_image_desc_cache_preserves_counts_and_ignores_empty_values():
    db = SimpleNamespace(
        get_image_desc_cache=AsyncMock(return_value={"count": 4, "description": "cached"}),
        update_image_desc_cache=AsyncMock(),
        add_image_desc_cache=AsyncMock(),
    )
    cache = ImageDescCache(db)

    await cache.set("hash", "")
    db.get_image_desc_cache.assert_not_awaited()
    assert await cache.get("hash") == "cached"
    assert db.update_image_desc_cache.await_args.kwargs["count"] == 5
    await cache.set("hash", "updated")
    assert db.update_image_desc_cache.await_args.kwargs["count"] == 4
    assert db.update_image_desc_cache.await_args.kwargs["description"] == "updated"
    db.add_image_desc_cache.assert_not_awaited()
