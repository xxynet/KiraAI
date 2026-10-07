import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.adapter import AdapterContext, AdapterManager, BaseAdapter
from core.adapter.access import ListAccessPolicy
from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata
from core.chat.message_elements import Text
from core.chat.message_utils import (
    KiraIMMessage, KiraIMSentResult, KiraMessageEvent, MessageChain,
)
from core.chat.session import Group, User
from core.message_manager import MessageProcessor, SessionBufferManager
from core.plugin.plugin_context import PluginContext
from core.plugin import manager as manager_module
from core.plugin import registry
from tests.test_adapter_base import ExampleAdapter, make_adapter


def routed_adapter():
    return make_adapter(enable_qzone=True)


def message_event(adapter, group=False, target_id="123"):
    return KiraMessageEvent(
        supported_elements=list(adapter.im._supported_elements),
        timestamp=1, adapter=adapter.info,
        message=KiraIMMessage(
            message_id="1", self_id="bot", timestamp=1,
            chain=MessageChain([Text("hello")]), sender=User(target_id),
            group=Group(target_id) if group else None,
        ),
    )


def processor_for(adapter):
    processor = object.__new__(MessageProcessor)
    processor.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    processor.session_buffer = SessionBufferManager()
    processor.session_locks = {}
    processor.event_bus = SimpleNamespace(publish=AsyncMock())
    processor.session_manager = SimpleNamespace(
        get_session_info=lambda sid: SimpleNamespace(session_description=None),
    )
    return processor


def test_single_im_keeps_legacy_sid_and_explicit_metadata():
    adapter = make_adapter()
    event = message_event(adapter)
    adapter.im.publish(event)
    assert adapter.ctx.event_queue.get_nowait() is event
    assert event.session.sid == "example:dm:123"
    assert not hasattr(event, "capability_name")


def test_adapter_publish_preserves_event_fields():
    adapter = make_adapter()
    event = message_event(adapter)
    event.supported_elements = ["custom"]
    adapter.publish(event)
    assert adapter.ctx.event_queue.get_nowait() is event
    assert not hasattr(event, "capability_name")
    assert event.supported_elements == ["custom"]


def test_capability_publish_preserves_event_fields():
    adapter = routed_adapter()
    capability = adapter.get_capability(IMCapability)
    adapter.im._metadata = MessageFormatMetadata(["text", "emoji"])
    adapter.im._supported_elements = adapter.im._metadata.supported_elements
    event = message_event(adapter)
    event.supported_elements = ["custom"]
    event.session.session_id = "custom/id"
    capability.publish(event)
    assert not hasattr(event, "capability_name")
    assert event.adapter is adapter.info
    assert event.session.sid == "example:dm:custom/id"
    assert event.supported_elements == ["custom"]
    assert adapter.ctx.event_queue.get_nowait() is event


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_im_event_and_proactive_send_preserve_adapter_target_ids(group):
    adapter = routed_adapter()
    regular = message_event(adapter, group)
    channel = message_event(adapter, group, target_id="channel/123")
    adapter.im.publish(regular)
    adapter.get_capability(IMCapability).publish(channel)
    kind = "gm" if group else "dm"
    assert regular.session.sid == f"example:{kind}:123"
    assert channel.session.sid == f"example:{kind}:channel/123"
    assert channel.message.sender.user_id == "channel/123"
    processor = processor_for(adapter)
    assert processor.get_session_lock(regular.session.sid) is not processor.get_session_lock(channel.session.sid)
    assert processor.session_buffer.get_buffer(regular.session.sid) is not processor.session_buffer.get_buffer(channel.session.sid)
    await processor.send_message_chain(regular.session.sid, regular.message.chain)
    await processor.send_message_chain(channel.session.sid, channel.message.chain)
    assert [(capability_type, target) for capability_type, target, _ in adapter.sent] == [
        (IMCapability, "123"), (IMCapability, "channel/123"),
    ]


@pytest.mark.asyncio
async def test_sending_rejects_missing_im_capability_before_sending():
    adapter = make_adapter(enable_im=False, enable_qzone=True)
    with pytest.raises(ValueError, match="Expected one IMCapability, found 0"):
        await processor_for(adapter).send_message_chain(
            "example:dm:channel/123", MessageChain([Text("reply")]),
        )
    assert not adapter.sent


@pytest.mark.asyncio
async def test_single_im_send_uses_the_capability_registered_by_type():
    adapter = make_adapter(enable_qzone=True)
    chain = MessageChain([Text("reply")])
    await processor_for(adapter).send_message_chain("example:dm:123", chain)
    assert adapter.sent == [(IMCapability, "123", chain)]


def test_publishing_preserves_explicit_session_id_without_decoding():
    adapter = routed_adapter()
    event = message_event(adapter)
    event.session.session_id = "adapter-decided/opaque:target"
    adapter.get_capability(IMCapability).publish(event)
    assert event.session.sid == "example:dm:adapter-decided/opaque:target"
    assert event.message.sender.user_id == "123"


@pytest.mark.asyncio
async def test_target_survives_trigger_and_buffer_flush(monkeypatch):
    monkeypatch.setattr("core.message_manager.event_handler_reg.get_handlers", lambda **kw: [])
    adapter = routed_adapter()
    event = message_event(adapter, target_id="channel/123")
    adapter.get_capability(IMCapability).publish(event)
    processor = processor_for(adapter)
    event.trigger()
    await processor.handle_im_message(event)
    batch = processor.event_bus.publish.await_args.args[0]
    assert not hasattr(batch, "capability_name")
    assert batch.sid == "example:dm:channel/123"
    event.buffer()
    await processor.handle_im_message(event)
    assert await processor.flush_session_messages(event.session.sid)
    batch = processor.event_bus.publish.await_args.args[0]
    assert not hasattr(batch, "capability_name")
    assert batch.sid == "example:dm:channel/123"


@pytest.mark.asyncio
async def test_xml_reply_passes_history_provenance(monkeypatch):
    monkeypatch.setattr("core.message_manager.event_handler_reg.get_handlers", lambda **kw: [])
    from core.tag import TagSet
    adapter = routed_adapter()
    processor = processor_for(adapter)
    chain = MessageChain([Text("reply")])
    processor._parse_xml_msg = AsyncMock(return_value=[chain])
    processor.send_message_chain = AsyncMock(return_value=KiraIMSentResult())
    processor.min_message_delay = processor.max_message_delay = 0
    event = SimpleNamespace(sid="example:dm:channel/123")
    await processor.send_xml_messages(event, "<msg/>", TagSet())
    processor.send_message_chain.assert_awaited_once_with(
        event.sid, chain, source="llm", memory_message=None, self_id=None,
    )


@pytest.mark.asyncio
async def test_plugin_notice_preserves_opaque_target_without_capability_name():
    adapter = routed_adapter()
    adapter.im._metadata = MessageFormatMetadata(["text", "img"])
    adapter.im._supported_elements = adapter.im._metadata.supported_elements
    ctx = object.__new__(PluginContext)
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = SimpleNamespace(publish=AsyncMock())
    await ctx.publish_notice(
        "example:dm:channel/123", MessageChain([Text("notice")]),
    )
    event = ctx.event_bus.publish.await_args.args[0]
    assert not hasattr(event, "capability_name")
    assert event.session.sid == "example:dm:channel/123"
    assert event.message.sender.user_id == "channel/123"
    assert event.supported_elements == ["text", "img"]
    assert hasattr(type(adapter), "message_types")


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type", ["dm", "gm"])
async def test_sending_only_uses_im_capability(session_type):
    adapter = routed_adapter()
    adapter.send_direct_message = AsyncMock(side_effect=AssertionError("Adapter-level send must not be used"))
    adapter.send_group_message = AsyncMock(side_effect=AssertionError("Adapter-level send must not be used"))
    chain = MessageChain([Text("reply")])
    await processor_for(adapter).send_message_chain(f"example:{session_type}:opaque:123", chain)
    assert adapter.sent == [(IMCapability, "opaque:123", chain)]
    adapter.send_direct_message.assert_not_awaited()
    adapter.send_group_message.assert_not_awaited()


@pytest.fixture
def manager(monkeypatch):
    for field in ("_registry", "_manifests", "_manifest_dirs", "_schemas"):
        monkeypatch.setattr(AdapterManager, field, {})
    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = {}
    return manager


@pytest.mark.asyncio
async def test_manager_constructs_new_adapter_with_context_and_stops_it(manager, tmp_path):
    manager.register_adapter_type("qq", ExampleAdapter, {"name": "qq"}, tmp_path)
    info = make_adapter().info
    await manager.register_adapter(info)
    adapter = manager.get_adapter(info.name)
    assert isinstance(adapter.ctx, AdapterContext)
    assert adapter.ctx.info is info
    assert adapter.ctx.event_queue is manager.event_queue
    assert adapter.get_capability(IMCapability).adapter is adapter
    await manager.stop_adapter(info.name)
    assert manager.get_adapter(info.name) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("inherits_base", [False, True])
async def test_plugin_registration_requires_base_adapter(manager, monkeypatch, tmp_path, inherits_base):
    monkeypatch.setattr(registry, "_plugin_components", {})
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "new-platform"}), encoding="utf-8")
    module = ModuleType("plugin_adapter_example")
    module.BaseAdapter = BaseAdapter
    module.PluginAdapter = type("PluginAdapter", (ExampleAdapter if inherits_base else object,), {"__module__": module.__name__})
    plugins = object.__new__(manager_module.PluginManager)
    plugins.ctx = SimpleNamespace(adapter_mgr=manager, config={})
    monkeypatch.setattr(plugins, "_resolve_plugin_component_dir", lambda *args: tmp_path)
    monkeypatch.setattr(plugins, "_load_plugin_component_module", lambda *args: module)
    if inherits_base:
        assert await plugins.register_plugin_adapter("test-plugin", "adapter") == "new-platform"
        assert manager.get_adapter_class("new-platform") is module.PluginAdapter
    else:
        with pytest.raises(ValueError, match="No Adapter class inheriting from BaseAdapter"):
            await plugins.register_plugin_adapter("test-plugin", "adapter")
        assert manager.get_adapter_class("new-platform") is None
        assert not registry._ensure_components("test-plugin").adapters


@pytest.mark.parametrize("inherits_base", [False, True])
def test_directory_scan_requires_base_adapter(manager, tmp_path, monkeypatch, inherits_base):
    folder = tmp_path / "routing_test_adapter"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"name": "scan-test"}), encoding="utf-8")
    (folder / "adapter.py").write_text(
        "from core.adapter import BaseAdapter\n" +
        ("class ScannedAdapter(BaseAdapter):\n" if inherits_base else "class ScannedAdapter:\n") +
        "    async def start(self): pass\n"
        "    async def stop(self): pass\n"
        "    def get_client(self): return None\n",
        encoding="utf-8",
    )
    package_name = "core.adapter.src.routing_test_adapter"
    monkeypatch.setitem(sys.modules, package_name, ModuleType(package_name))
    manager.scan_adapters(str(tmp_path))
    if inherits_base:
        assert issubclass(manager.get_adapter_class("scan-test"), BaseAdapter)
    else:
        assert manager.get_adapter_class("scan-test") is None


@pytest.mark.parametrize("adapter_class", [object, object()])
def test_adapter_registration_rejects_non_base_types(manager, tmp_path, adapter_class):
    with pytest.raises(TypeError, match="Adapter class must inherit from BaseAdapter"):
        manager.register_adapter_type("invalid", adapter_class, {"name": "invalid"}, tmp_path)
    assert manager.get_adapter_class("invalid") is None
    assert manager.get_manifest("invalid") == {}


@pytest.mark.asyncio
async def test_cross_session_permission_uses_opaque_id_without_capability_name():
    from core.plugin.builtin_plugins.session_tools.main import SessionPlugin

    adapter = routed_adapter()
    adapter.access.set_policy(
        capability_type=IMCapability, permission="im.direct.receive",
        policy=ListAccessPolicy.from_lists("allow_list", allow_list=["channel/123"]),
    )
    ctx = SimpleNamespace(
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        publish_notice=AsyncMock(),
        config={"bot_config": {"bot": {}}},
    )
    plugin = SessionPlugin(ctx, {})
    event = SimpleNamespace(sid="source:dm:1")
    assert await plugin.session_send(event, "example:dm:channel/123", "hello") == "message sent"
    assert ctx.publish_notice.await_args.args[0] == "example:dm:channel/123"
    assert ctx.publish_notice.await_args.kwargs == {}
    assert "Permission denied" in await plugin.session_send(event, "example:dm:123", "hello")
    assert ctx.publish_notice.await_count == 1


@pytest.mark.asyncio
async def test_builtin_emoji_tag_uses_capability_metadata():
    from core.tag import TagSet

    main = importlib.import_module("core.plugin.builtin_plugins.kira-ai.main")
    adapter = routed_adapter()
    adapter.im._metadata = MessageFormatMetadata(["emoji"], emojis={"2": "adapter-emoji"})
    adapter.im._supported_elements = adapter.im._metadata.supported_elements
    channel = adapter.get_capability(IMCapability)
    assert not hasattr(channel, "message_types")
    assert not hasattr(channel, "emoji_dict")
    event = message_event(adapter)
    channel.publish(event)
    ctx = SimpleNamespace(
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        get_session_capabilities=lambda sid: {},
    )
    tags = TagSet()
    event.sid = event.session.sid
    await main.DefaultPlugin(ctx, {}).inject_builtin_tags(event, None, tags)
    assert "adapter-emoji" in tags.get("emoji").description

@pytest.mark.asyncio
@pytest.mark.parametrize("session_type", ["dm", "gm"])
@pytest.mark.parametrize("has_feed", [False, True])
async def test_cross_session_without_im_returns_denial_without_publishing(session_type, has_feed):
    from core.plugin.builtin_plugins.session_tools.main import SessionPlugin

    adapter = make_adapter(enable_im=False, enable_qzone=has_feed)
    ctx = SimpleNamespace(
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        publish_notice=AsyncMock(),
        config={"bot_config": {"bot": {}}},
    )
    plugin = SessionPlugin(ctx, {})
    result = await plugin.session_send(
        SimpleNamespace(sid="source:dm:1"), f"example:{session_type}:123", "hello",
    )
    assert result == "Permission denied: target session is not allowed by adapter example"
    ctx.publish_notice.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("session_type", ["dm", "gm"])
async def test_notice_without_im_can_enter_message_processing(monkeypatch, session_type):
    from tests.test_bilibili_adapter import make_adapter as make_bilibili

    monkeypatch.setattr("core.message_manager.event_handler_reg.get_handlers", lambda **kw: [])
    adapter = make_bilibili(enable_im=False)
    ctx = object.__new__(PluginContext)
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = SimpleNamespace(publish=AsyncMock())
    target = f"bili-test:{session_type}:opaque:123"
    chain = MessageChain([Text("background result")])
    await ctx.publish_notice(target, chain, is_mentioned=False)
    event = ctx.event_bus.publish.await_args.args[0]
    assert event.session.sid == target
    assert event.message.chain is chain
    assert event.is_notice
    assert not event.is_mentioned
    assert event.is_group_message() is (session_type == "gm")
    assert event.supported_elements == []
    assert hasattr(type(adapter), "message_types")
    event.buffer()
    processor = processor_for(adapter)
    await processor.handle_im_message(event)
    assert await processor.flush_session_messages(target)
    batch = processor.event_bus.publish.await_args.args[0]
    assert batch.sid == target
    assert batch.messages == [event.message]

@pytest.mark.asyncio
async def test_buffer_flush_preserves_event_supported_elements():
    adapter = make_adapter()
    event = message_event(adapter)
    event.supported_elements = ["custom"]
    processor = processor_for(adapter)
    processor.session_buffer.get_buffer(event.session.sid).add(event)
    assert await processor.flush_session_messages(event.session.sid)
    batch = processor.event_bus.publish.await_args.args[0]
    assert batch.supported_elements == ["custom"]
    assert batch.messages[0] is event.message
    assert batch.session is event.session
    assert batch.adapter is event.adapter
    assert not await processor.flush_session_messages(event.session.sid)


@pytest.mark.asyncio
@pytest.mark.parametrize("selected_ids", [None, {"0", "2"}, set()])
async def test_plugin_flush_filters_buffered_events_before_publishing(selected_ids):
    adapter = make_adapter()
    processor = processor_for(adapter)
    ctx = object.__new__(PluginContext)
    ctx.message_processor = processor
    events = [message_event(adapter) for _ in range(4)]
    for index, event in enumerate(events):
        event.message.message_id = str(index)
        event.supported_elements = [f"custom-{index}"]
    sid = events[0].session.sid
    buffer = ctx.get_buffer(sid)
    for event in events:
        buffer.add(event)

    if selected_ids is None:
        await ctx.flush_session_messages(sid)
        selected = events
    else:
        def select_event(event):
            assert buffer.lock.locked()
            return event.message.message_id in selected_ids

        await ctx.flush_session_messages(sid, filter_fn=select_event)
        selected = [event for event in events if event.message.message_id in selected_ids]

    assert buffer.buffer == [event for event in events if event not in selected]
    assert not buffer.lock.locked()
    if not selected:
        processor.event_bus.publish.assert_not_awaited()
        return

    processor.event_bus.publish.assert_awaited_once()
    batch = processor.event_bus.publish.await_args.args[0]
    assert batch.messages == [event.message for event in selected]
    assert batch.supported_elements == selected[-1].supported_elements
    assert batch.session is selected[-1].session
    assert batch.adapter is selected[-1].adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("include_extra", [False, True])
async def test_filtered_flush_applies_predicate_to_extra_event(include_extra):
    adapter = make_adapter()
    processor = processor_for(adapter)
    buffered = message_event(adapter)
    extra = message_event(adapter)
    buffer = processor.session_buffer.get_buffer(buffered.session.sid)
    buffer.add(buffered)

    flushed = await processor.flush_session_messages(
        buffered.session.sid,
        extra,
        filter_fn=lambda event: include_extra and event is extra,
    )

    assert flushed is include_extra
    assert buffer.buffer == ([buffered] if include_extra else [buffered, extra])
    if include_extra:
        processor.event_bus.publish.assert_awaited_once()
        batch = processor.event_bus.publish.await_args.args[0]
        assert batch.messages == [extra.message]
    else:
        processor.event_bus.publish.assert_not_awaited()
