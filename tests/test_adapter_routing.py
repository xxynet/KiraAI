import asyncio
import importlib
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.adapter import AdapterContext, AdapterManager, BaseAdapter
from core.adapter.access import ListAccessPolicy
from core.adapter.capabilities import FeedCapability, IMCapability
from core.chat.message_elements import Text
from core.chat.message_utils import (
    KiraCommentEvent, KiraIMMessage, KiraIMSentResult, KiraMessageEvent, MessageChain,
)
from core.chat.session import Group, User
from core.message_manager import MessageProcessor, SessionBufferManager
from core.plugin.plugin_context import PluginContext
from core.plugin import plugin_registry
from tests.test_adapter_base import ExampleAdapter, make_adapter


def routed_adapter():
    return make_adapter(enable_qzone=True)


def message_event(adapter, group=False, target_id="123"):
    return KiraMessageEvent(
        message_types=list(adapter.message_types),
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
    event.message_types = ["custom"]
    adapter.publish(event)
    assert adapter.ctx.event_queue.get_nowait() is event
    assert not hasattr(event, "capability_name")
    assert event.message_types == ["custom"]


def test_capability_publish_preserves_event_fields():
    adapter = routed_adapter()
    capability = adapter.get_capability(IMCapability)
    adapter.message_types = ["text", "emoji"]
    event = message_event(adapter)
    event.message_types = ["custom"]
    event.session.session_id = "custom/id"
    capability.publish(event)
    assert not hasattr(event, "capability_name")
    assert event.adapter is adapter.info
    assert event.session.sid == "example:dm:custom/id"
    assert event.message_types == ["custom"]
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
async def test_xml_reply_only_passes_target_and_chain(monkeypatch):
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
        event.sid, chain,
    )


@pytest.mark.asyncio
async def test_plugin_notice_preserves_opaque_target_without_capability_name():
    adapter = routed_adapter()
    adapter.message_types = ["text", "img"]
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
    assert event.message_types == ["text", "img"]
    assert event.message_types is not adapter.message_types


@pytest.mark.asyncio
async def test_comment_reply_uses_the_only_feed():
    adapter = routed_adapter()
    event = KiraCommentEvent(
        "qq", adapter.info.name, "user", "user", "bot", 1, "post", [Text("comment")],
    )
    adapter.get_capability(FeedCapability).publish(event)
    assert not hasattr(event, "capability_name")
    processor = processor_for(adapter)
    processor.prompt_manager = SimpleNamespace(get_comment_prompt=AsyncMock(return_value="prompt"))
    client = SimpleNamespace(chat=AsyncMock(return_value=SimpleNamespace(text_response="reply")))
    processor.provider_mgr = SimpleNamespace(get_default_llm=lambda: client)
    await processor.handle_cmt_message(event)
    assert adapter.sent == [(FeedCapability, "post", ("reply", None))]


@pytest.mark.asyncio
async def test_legacy_sending_still_calls_adapter_directly():
    legacy = SimpleNamespace(send_direct_message=AsyncMock(return_value=KiraIMSentResult()))
    chain = MessageChain([Text("legacy")])
    await processor_for(legacy).send_message_chain("old:dm:123", chain)
    legacy.send_direct_message.assert_awaited_once_with("123", chain)


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
async def test_plugin_registration_accepts_new_base(manager, monkeypatch, tmp_path):
    monkeypatch.setattr(plugin_registry, "_plugin_components", {})
    (tmp_path / "manifest.json").write_text(json.dumps({"name": "new-platform"}), encoding="utf-8")
    module = ModuleType("plugin_adapter_example")
    module.BaseAdapter = BaseAdapter
    module.PluginAdapter = type("PluginAdapter", (ExampleAdapter,), {"__module__": module.__name__})
    plugins = object.__new__(plugin_registry.PluginManager)
    plugins.ctx = SimpleNamespace(adapter_mgr=manager, config={})
    monkeypatch.setattr(plugins, "_resolve_plugin_component_dir", lambda *args: tmp_path)
    monkeypatch.setattr(plugins, "_load_plugin_component_module", lambda *args: module)
    assert await plugins.register_plugin_adapter("test-plugin", "adapter") == "new-platform"
    assert manager.get_adapter_class("new-platform") is module.PluginAdapter


def test_directory_scan_discovers_new_adapter(manager, tmp_path, monkeypatch):
    folder = tmp_path / "routing_test_adapter"
    folder.mkdir()
    (folder / "manifest.json").write_text(json.dumps({"name": "scan-test"}), encoding="utf-8")
    (folder / "adapter.py").write_text(
        "from core.adapter import BaseAdapter\n"
        "class ScannedAdapter(BaseAdapter):\n"
        "    async def start(self): pass\n"
        "    async def stop(self): pass\n"
        "    def get_client(self): return None\n",
        encoding="utf-8",
    )
    package_name = "core.adapter.src.routing_test_adapter"
    monkeypatch.setitem(sys.modules, package_name, ModuleType(package_name))
    manager.scan_adapters(str(tmp_path))
    assert issubclass(manager.get_adapter_class("scan-test"), BaseAdapter)


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
async def test_builtin_emoji_tag_uses_adapter_dictionary():
    from core.tag import TagSet

    main = importlib.import_module("core.plugin.builtin_plugins.kira-ai.main")
    adapter = routed_adapter()
    adapter.emoji_dict = {"2": "adapter-emoji"}
    adapter.message_types = ["emoji"]
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
