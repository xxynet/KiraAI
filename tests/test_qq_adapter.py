"""Tests for the OneBot QQ adapter's IM capability and lifecycle.

Focus: a failing sticker download or a missing quoted message must degrade
that one segment/event instead of aborting the whole incoming message.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import core.utils.common_utils as common_utils
from core.adapter.adapter_info import AdapterInfo
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.adapter.src.qq import qq as qq_module
from core.adapter.src.qq.im import QQIMCapability
from core.adapter.src.qq.napcat_client import NapCatWebSocketClient
from core.chat import KiraIMSentResult, MessageChain
from core.adapter.src.qq.qq import QQAdapter
from core.chat.message_elements import At, Emoji, File, Forward, Image, Poke, Reply, Text, Video

pytestmark = pytest.mark.asyncio


def make_adapter(config: dict = None) -> QQAdapter:
    info = AdapterInfo(
        enabled=True, adapter_id="qq-test", name="qq", platform="QQ",
        config=config or {},
    )
    return QQAdapter(AdapterContext(info=info, event_queue=asyncio.Queue()))


async def test_sticker_download_failure_skips_sticker_and_keeps_rest(monkeypatch: pytest.MonkeyPatch):
    adapter = make_adapter()

    async def boom(image_path: str) -> str:
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(common_utils, "image_to_base64", boom)

    chain = await adapter.im.process_incoming_message({
        "message_type": "group",
        "group_id": 123,
        "message": [
            {"type": "image", "data": {"url": "https://expired.example/a.jpg", "sub_type": 1, "summary": "[动画表情]"}},
            {"type": "text", "data": {"text": "after"}},
        ],
    })

    # The failed sticker is logged and skipped; the following segments survive.
    assert len(chain) == 1
    assert isinstance(chain[0], Text)
    assert chain[0].text == "after"


async def test_empty_url_sticker_is_skipped_without_mock():
    """An empty sticker url hits the real image_to_base64 open('') path; the
    branch must still skip the segment instead of raising out of the loop."""
    adapter = make_adapter()

    chain = await adapter.im.process_incoming_message({
        "message_type": "private",
        "message": [
            {"type": "image", "data": {"url": "", "summary": "[动画表情]"}},
        ],
    })

    assert len(chain) == 0


async def test_regular_image_skips_download(monkeypatch: pytest.MonkeyPatch):
    adapter = make_adapter()

    async def boom(image_path: str) -> str:
        raise AssertionError("regular image must not be downloaded at receive time")

    monkeypatch.setattr(common_utils, "image_to_base64", boom)

    chain = await adapter.im.process_incoming_message({
        "message_type": "group",
        "group_id": 123,
        "message": [
            {"type": "image", "data": {"url": "https://example.com/pic.jpg", "sub_type": 0, "summary": "[图片]"}},
        ],
    })

    assert len(chain) == 1
    assert isinstance(chain[0], Image)


async def test_mention_check_survives_missing_quoted_message():
    """get_msg failing for the quoted message only skips the mention check;
    the message itself must still be processed and published."""
    adapter = make_adapter(config={"group_allow_list": ["123"]})
    adapter.bot = AsyncMock()
    adapter.bot.get_msg = AsyncMock(side_effect=TimeoutError("请求 get_msg 超时"))
    adapter.bot.get_user_info = AsyncMock(return_value={"data": {"nickname": "u"}})
    adapter.bot.get_group_info = AsyncMock(return_value={"data": {"group_name": "g"}})

    await adapter.im._on_group_message({
        "message_type": "group",
        "group_id": 123,
        "user_id": 456,
        "self_id": 10000,
        "time": 1700000000,
        "message_id": "m1",
        "sender": {"nickname": "alice"},
        "message": [
            {"type": "reply", "data": {"id": "999"}},
            {"type": "text", "data": {"text": "hi"}},
        ],
    })

    event = adapter._event_queue.get_nowait()
    chain_repr = "".join(ele.repr for ele in event.message.chain)
    assert "hi" in chain_repr


async def test_registers_only_one_im_with_capability_metadata():
    adapter = make_adapter()
    assert isinstance(adapter, BaseAdapter)
    assert isinstance(adapter.get_capability(IMCapability), QQIMCapability)
    assert adapter.get_capabilities() == {IMCapability: adapter.im}
    assert adapter.im.adapter is adapter
    assert adapter.get_client() is adapter.bot
    assert (await adapter.im.get_message_metadata()).emojis
    assert not hasattr(adapter.im, "emoji_dict")
    assert not hasattr(adapter.im, "message_types")


@pytest.mark.parametrize("scope, permission", [
    ("group", "im.group.receive"), ("user", "im.direct.receive"),
])
@pytest.mark.parametrize("mode", ["allow_list", "deny_list"])
@pytest.mark.parametrize("entry", [123, "123"])
async def test_permissions_normalize_ids_and_keep_scope_isolation(scope, permission, mode, entry):
    adapter = make_adapter({"permission_mode": mode, f"{scope}_{mode}": [entry]})
    assert adapter.im.is_allowed(123, permission=permission) is (mode == "allow_list")
    assert adapter.im.is_allowed("123", permission=permission) is (mode == "allow_list")
    assert adapter.im.is_allowed("other", permission=permission) is (mode == "deny_list")
    assert not adapter.im.is_allowed(None, permission=permission)
    other = "im.direct.receive" if scope == "group" else "im.group.receive"
    assert adapter.im.is_allowed("123", permission=other) is (mode == "deny_list")


@pytest.mark.parametrize("config", [
    {},
    {"permission_mode": "invalid", "user_allow_list": ["123"], "group_allow_list": ["123"]},
    {"permission_mode": "ALLOW_LIST", "user_allow_list": ["123"]},
    {"user_allow_list": "123", "group_allow_list": "123"},
    {"user_allow_list": None, "group_allow_list": None},
])
async def test_invalid_permission_config_keeps_default_denial(config):
    adapter = make_adapter(config)
    assert not adapter.im.is_allowed("123", permission="im.direct.receive")
    assert not adapter.im.is_allowed("123", permission="im.group.receive")


def inbound_message(group=False, target=123):
    return {
        "message_type": "group" if group else "private",
        "group_id": target if group else None,
        "user_id": 456 if group else target,
        "self_id": 10000,
        "time": 1700000000,
        "message_id": 789,
        "sender": {"nickname": "alice"},
        "message": [{"type": "text", "data": {"text": "hello"}}],
    }


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("mode, listed, allowed", [
    ("allow_list", True, True),
    ("allow_list", False, False),
    ("deny_list", True, False),
    ("deny_list", False, True),
])
async def test_inbound_permissions_and_session_metadata(group, mode, listed, allowed):
    scope = "group" if group else "user"
    adapter = make_adapter({"permission_mode": mode, f"{scope}_{mode}": [123] if listed else []})
    adapter.bot = AsyncMock()
    adapter.bot.get_group_info.return_value = {"data": {"group_name": "group"}}
    msg = inbound_message(group)
    handler = adapter.im._on_group_message if group else adapter.im._on_private_message
    await handler(msg)
    if not allowed:
        assert adapter.ctx.event_queue.empty()
        adapter.bot.get_group_info.assert_not_awaited()
        return
    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == f"qq:{'gm' if group else 'dm'}:123"
    assert event.message.message_id == "789"
    assert event.message.self_id == "10000"
    assert event.message.raw_message is msg
    assert event.message.timestamp == 1700000000
    assert event.message.chain[0].text == "hello"
    assert event.supported_elements == list((await adapter.im.get_message_metadata()).supported_elements)
    assert not hasattr(event, "capability_name")


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("allowed", [False, True])
@pytest.mark.parametrize("style", ["napcat", "onebot"])
async def test_poke_notice_permissions_and_native_text(group, allowed, style):
    scope = "group" if group else "user"
    adapter = make_adapter({f"{scope}_allow_list": [123] if allowed else []})
    adapter.bot = AsyncMock()
    adapter.bot.get_group_info.return_value = {"data": {"group_name": "group"}}
    adapter.bot.get_user_info.return_value = {"data": {"nickname": "alice"}}
    msg = {
        "notice_type": "notify", "sub_type": "poke", "self_id": 10000,
        "target_id": "10000", "user_id": 456 if group else 123,
        "group_id": 123 if group else None, "time": 1700000000,
    }
    if style == "napcat":
        msg["raw_info"] = [{}, {}, {"txt": "nudged"}, {}, {"txt": "gently"}]
    else:
        msg.update(action="nudged", suffix="gently")
    await adapter.im._on_notice_message(msg)
    if not allowed:
        assert adapter.ctx.event_queue.empty()
        return
    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == f"qq:{'gm' if group else 'dm'}:123"
    assert event.message.is_notice
    assert event.message.is_mentioned
    assert "nudged" in event.message.chain[0].text
    assert "gently" in event.message.chain[0].text
    assert event.message.raw_message is msg


@pytest.mark.parametrize("group", [False, True])
async def test_send_text_and_native_segments_preserves_result(group):
    adapter = make_adapter()
    adapter.bot = AsyncMock()
    operation = adapter.bot.send_group_message if group else adapter.bot.send_direct_message
    operation.return_value = {"status": "ok", "data": {"message_id": 789}}
    chain = MessageChain([Reply("old"), Text("hello"), At("456"), Emoji("14"), Image("https://example.test/a.png")])
    sender = adapter.im.send_group_message if group else adapter.im.send_direct_message
    result = await sender("123", message=chain)
    assert result.ok and result.message_id == "789"
    call = operation.await_args
    assert call.kwargs["group_id" if group else "user_id"] == "123"
    assert call.kwargs["msg"].to_list() == [
        {"type": "reply", "data": {"id": "old"}},
        {"type": "text", "data": {"text": "hello"}},
        {"type": "at", "data": {"qq": "456"}},
        {"type": "text", "data": {"text": " "}},
        {"type": "face", "data": {"id": 14}},
        {"type": "image", "data": {"file": "https://example.test/a.png", "summary": "[图片]"}},
    ]


@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("kind", ["file", "video", "forward", "poke"])
async def test_special_sends_use_native_client_operations(group, kind):
    adapter = make_adapter()
    adapter.bot = AsyncMock()
    target_key = "group_id" if group else "user_id"
    if kind == "file":
        element = File("https://example.test/a.txt", name="a.txt")
        method = adapter.bot.upload_group_file if group else adapter.bot.upload_private_file
        expected = {target_key: "123", "file": element.file, "name": "a.txt"}
    elif kind == "video":
        element = Video("https://example.test/a.mp4", name="a.mp4")
        method = adapter.bot.send_group_segments if group else adapter.bot.send_direct_segments
        expected = {target_key: "123", "message": [{"type": "video", "data": {"file": element.file, "name": "a.mp4"}}]}
    elif kind == "forward":
        element = Forward(message_id=["old-1", "old-2"])
        method = adapter.bot.send_group_segments if group else adapter.bot.send_direct_segments
        expected = {target_key: "123", "message": [
            {"type": "node", "data": {"id": "old-1"}},
            {"type": "node", "data": {"id": "old-2"}},
        ]}
    else:
        element = Poke("456")
        method = adapter.bot.send_poke
        expected = {"user_id": "456", **({"group_id": "123"} if group else {})}
    method.return_value = {"status": "ok", "data": {"message_id": 789}}
    sender = adapter.im.send_group_message if group else adapter.im.send_direct_message
    result = await sender("123", MessageChain([element]))
    method.assert_awaited_once_with(**expected)
    assert result.ok
    assert result.is_notice is (kind == "poke")
    assert result.message_id == (None if kind == "poke" else "789")


@pytest.mark.parametrize("group", [False, True])
async def test_empty_and_failed_sends_keep_error_contract(group):
    adapter = make_adapter()
    adapter.bot = AsyncMock()
    method = adapter.bot.send_group_message if group else adapter.bot.send_direct_message
    sender = adapter.im.send_group_message if group else adapter.im.send_direct_message
    result = await sender("123", MessageChain())
    assert not result.ok
    method.assert_not_awaited()
    method.return_value = {"status": "failed", "retcode": 1200}
    result = await sender("123", MessageChain([Text("hello")]))
    assert not result.ok and result.message_id is None
    assert result.err


@pytest.mark.parametrize("group", [False, True])
async def test_legacy_send_entry_only_forwards_to_registered_im(group):
    adapter = make_adapter()
    sender = "send_group_message" if group else "send_direct_message"
    result = KiraIMSentResult("sent")
    capability_sender = AsyncMock(return_value=result)
    setattr(adapter.im, sender, capability_sender)
    chain = MessageChain([Text("hello")])
    assert await getattr(adapter, sender)("123", send_message_obj=chain) is result
    capability_sender.assert_awaited_once_with("123", chain)


@pytest.mark.parametrize("group", [False, True])
async def test_core_sending_uses_qq_capability_and_preserves_opaque_target(group):
    from tests.test_adapter_routing import processor_for
    adapter = make_adapter()
    adapter_sender = "send_group_message" if group else "send_direct_message"
    setattr(adapter, adapter_sender, AsyncMock(side_effect=AssertionError("must use capability")))
    capability_sender = AsyncMock(return_value=KiraIMSentResult("sent"))
    setattr(adapter.im, adapter_sender, capability_sender)
    chain = MessageChain([Text("hello")])
    result = await processor_for(adapter).send_message_chain(
        f"qq:{'gm' if group else 'dm'}:opaque:123", chain,
    )
    assert result.message_id == "sent"
    capability_sender.assert_awaited_once_with("opaque:123", chain)


@pytest.mark.parametrize("group", [False, True])
async def test_cross_session_plugin_uses_qq_permission_policy(group):
    from core.plugin.builtin_plugins.session_tools.main import SessionPlugin
    scope = "group" if group else "user"
    adapter = make_adapter({f"{scope}_allow_list": [123]})
    ctx = SimpleNamespace(
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        publish_notice=AsyncMock(), config={"bot_config": {"bot": {}}},
    )
    plugin = SessionPlugin(ctx, {})
    event = SimpleNamespace(sid="source:dm:1")
    target = f"qq:{'gm' if group else 'dm'}:123"
    assert await plugin.session_send(event, target, "hello") == "message sent"
    assert "Permission denied" in await plugin.session_send(event, target.replace("123", "456"), "hello")
    assert ctx.publish_notice.await_count == 1
    assert ctx.publish_notice.await_args.args[0] == target


async def test_debug_log_contains_only_structural_metadata():
    adapter = make_adapter({"debug_mode": True, "user_allow_list": [123]})
    adapter.logger = Mock()
    msg = inbound_message()
    msg["message"][0]["data"]["text"] = "private conversation"
    await adapter.im._on_private_message(msg)
    assert adapter.logger.debug.call_count == 1
    assert adapter.logger.debug.call_args.args == ("QQ inbound message: segments=1",)


class FakeQQClient(NapCatWebSocketClient):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.run_calls = 0
        self.close_calls = 0

    async def run(self, **kwargs):
        self.run_calls += 1
        self.entered.set()
        await self.release.wait()

    async def close(self):
        self.close_calls += 1
        await super().close()
        self.release.set()


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(qq_module, "NapCatWebSocketClient", FakeQQClient)


def lifecycle_adapter():
    return make_adapter({"bot_pid": "10000", "ws_uri": "ws://example.test", "ws_token": ""})


async def wait_until_started(adapter):
    await asyncio.wait_for(adapter.bot.entered.wait(), timeout=1)


async def test_start_stop_restart_owns_runner_and_rebinds_callbacks(fake_client):
    adapter = lifecycle_adapter()
    old_client = adapter.bot
    await adapter.start()
    task = adapter._client_task
    try:
        await wait_until_started(adapter)
        await adapter.start()
        assert adapter._client_task is task
        assert old_client.run_calls == 1
        assert len(old_client.event_callbacks["group"]) == 1
        old_client.on_permanent_disconnect()
        assert adapter.permanently_disconnected
    finally:
        await adapter.stop()
    assert task.done()
    assert adapter._client_task is None
    assert old_client.shutdown_event.is_set()
    assert old_client.close_calls == 1
    await adapter.start()
    try:
        await wait_until_started(adapter)
        assert adapter.bot is not old_client
        assert not adapter.permanently_disconnected
        old_client.on_permanent_disconnect()
        assert not adapter.permanently_disconnected
        assert len(adapter.bot.event_callbacks["group"]) == 1
        await old_client.event_callbacks["private"][0](inbound_message())
        assert adapter.ctx.event_queue.empty()
    finally:
        await adapter.stop()


async def test_stop_before_runner_starts_is_complete_and_idempotent(fake_client):
    adapter = lifecycle_adapter()
    await adapter.start()
    task = adapter._client_task
    await adapter.stop()
    await adapter.stop()
    assert task.done()
    assert adapter.bot.shutdown_event.is_set()
    assert not adapter._event_tasks
    assert adapter.bot.close_calls == 1


async def test_stop_cancels_inflight_handlers_and_rejects_late_callbacks(fake_client):
    adapter = lifecycle_adapter()
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def handler(msg):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    adapter.im._on_private_message = handler
    await adapter.start()
    task = None
    try:
        await wait_until_started(adapter)
        task = asyncio.create_task(adapter.bot.event_callbacks["private"][0](inbound_message()))
        await asyncio.wait_for(entered.wait(), timeout=1)
        assert task in adapter._event_tasks
    finally:
        await adapter.stop()
    assert cancelled.is_set()
    assert task.cancelled()
    assert not adapter._event_tasks
    adapter.im._on_private_message = AsyncMock()
    await adapter.bot.event_callbacks["private"][0](inbound_message())
    adapter.im._on_private_message.assert_not_awaited()


async def test_runner_failure_closes_client_and_is_observed_without_sensitive_details(fake_client):
    adapter = lifecycle_adapter()
    adapter.logger = Mock()
    adapter.bot.run = AsyncMock(side_effect=RuntimeError("sensitive-token"))
    await adapter.start()
    task = adapter._client_task
    try:
        await asyncio.wait({task}, timeout=1)
        await asyncio.sleep(0)
        assert task.done()
        assert adapter.bot.shutdown_event.is_set()
        assert adapter.logger.error.call_args.args == ("QQ client stopped with an error (RuntimeError)",)
    finally:
        await adapter.stop()


async def test_stop_preserves_callers_cancellation_and_finishes_cleanup(fake_client):
    adapter = lifecycle_adapter()
    await adapter.start()
    await wait_until_started(adapter)
    runner = adapter._client_task
    close_entered = asyncio.Event()
    original_close = adapter.bot.close
    close_release = asyncio.Event()

    async def close():
        close_entered.set()
        await close_release.wait()
        await original_close()

    adapter.bot.close = close
    stopping = asyncio.create_task(adapter.stop())
    await asyncio.wait_for(close_entered.wait(), timeout=1)
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done()
    assert not adapter._client_close_task.cancelled()
    close_release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(stopping, timeout=1)
    assert runner.done()
    assert adapter._client_task is None
    assert adapter.bot.shutdown_event.is_set()
    assert adapter.bot.close_calls == 1


async def test_two_instances_keep_clients_permissions_and_lifecycle_independent(fake_client):
    first = lifecycle_adapter()
    second = make_adapter({
        "bot_pid": "20000", "ws_uri": "ws://example.test", "ws_token": "",
        "user_allow_list": [123],
    })
    second.info.name = "qq-second"
    assert first.bot is not second.bot
    assert first.im is not second.im
    assert (await first.im.get_message_metadata()).emojis is not (await second.im.get_message_metadata()).emojis
    assert first._event_tasks is not second._event_tasks
    assert not first.im.is_allowed(123, permission="im.direct.receive")
    assert second.im.is_allowed(123, permission="im.direct.receive")
    await first.start()
    await second.start()
    try:
        await wait_until_started(first)
        await wait_until_started(second)
        await first.stop()
        assert not second._client_task.done()
        assert not second.bot.shutdown_event.is_set()
        await second.bot.event_callbacks["private"][0](inbound_message())
        assert second.ctx.event_queue.get_nowait().session.sid == "qq-second:dm:123"
        assert first.ctx.event_queue.empty()
    finally:
        await first.stop()
        await second.stop()


async def test_manager_constructs_and_stops_real_qq_adapter(fake_client, monkeypatch, tmp_path):
    from core.adapter.adapter_registry import AdapterManager
    for field in ("_registry", "_manifests", "_manifest_dirs", "_schemas"):
        monkeypatch.setattr(AdapterManager, field, {})
    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = {}
    manager.register_adapter_type("QQ", QQAdapter, {"name": "QQ"}, tmp_path)
    info = lifecycle_adapter().info
    await manager.register_adapter(info)
    adapter = manager.get_adapter("qq")
    try:
        await wait_until_started(adapter)
        assert adapter.ctx.info is info
        assert adapter.ctx.event_queue is manager.event_queue
        assert adapter.get_capability(IMCapability).adapter is adapter
    finally:
        await manager.stop_adapter("qq")
    assert manager.get_adapter("qq") is None
    assert adapter._client_task is None
    assert adapter.bot.shutdown_event.is_set()


@pytest.mark.parametrize("group", [False, True])
async def test_plugin_notice_keeps_qq_metadata_and_session_target(group):
    from core.plugin.plugin_context import PluginContext
    adapter = make_adapter()
    ctx = object.__new__(PluginContext)
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = SimpleNamespace(publish=AsyncMock())
    target = f"qq:{'gm' if group else 'dm'}:123"
    await ctx.publish_notice(target, MessageChain([Text("notice")]))
    event = ctx.event_bus.publish.await_args.args[0]
    assert event.session.sid == target
    assert event.message.is_notice
    assert event.supported_elements == list((await adapter.im.get_message_metadata()).supported_elements)
    assert hasattr(type(adapter), "message_types")


@pytest.mark.parametrize("group", [False, True])
async def test_inbound_file_video_voice_card_and_forward_keep_native_conversion(group):
    from core.chat.message_elements import Json, Record
    adapter = make_adapter()
    adapter.bot = AsyncMock()
    adapter.bot.get_group_file_url.return_value = {"data": {"url": "https://example.test/a.txt"}}
    adapter.bot.get_private_file_url.return_value = {"data": {"url": "https://example.test/a.txt"}}
    adapter.bot.get_record.return_value = {"data": {"base64": "YXVkaW8="}}
    adapter.bot.get_forward_msg.return_value = {"data": {"messages": [{
        "message_type": "private", "user_id": 123, "time": 1700000000,
        "sender": {"nickname": "alice"},
        "message": [{"type": "text", "data": {"text": "forwarded"}}],
    }]}}
    msg = inbound_message(group)
    msg["message"] = [
        {"type": "file", "data": {"file": "a.txt", "file_id": "file-id", "file_size": "5"}},
        {"type": "video", "data": {"file": "a.mp4", "url": "https://example.test/a.mp4", "file_size": "10"}},
        {"type": "record", "data": {"file": "voice-id"}},
        {"type": "json", "data": {"data": '{"app":"card","meta":{"news":{"title":"title"}}}'}},
        {"type": "forward", "data": {"id": "forward-id"}},
    ]
    chain = await adapter.im.process_incoming_message(msg)
    assert [type(element) for element in chain] == [File, Video, Record, Json, Forward]
    assert chain[0].file == "https://example.test/a.txt"
    assert chain[1].name == "a.mp4"
    assert chain[3].data["title"] == "title"
    assert chain[4].chains[0][-1].text == "forwarded"
    operation = adapter.bot.get_group_file_url if group else adapter.bot.get_private_file_url
    expected = {"file_id": "file-id", **({"group_id": 123} if group else {})}
    operation.assert_awaited_once_with(**expected)
    adapter.bot.get_record.assert_awaited_once_with("voice-id", output_format="mp3")


@pytest.mark.parametrize("group", [False, True])
async def test_real_client_dispatch_reaches_im_and_stop_waits_for_its_handler(fake_client, group):
    adapter = lifecycle_adapter()
    handler_started = asyncio.Event()
    handler_stopped = asyncio.Event()

    async def handler(msg):
        handler_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            handler_stopped.set()

    if group:
        adapter.im._on_group_message = handler
    else:
        adapter.im._on_private_message = handler
    await adapter.start()
    try:
        await wait_until_started(adapter)
        msg = inbound_message(group)
        msg["post_type"] = "message"
        await adapter.bot.handle_message(msg)
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        assert len(adapter._event_tasks) == 1
    finally:
        await adapter.stop()
    assert handler_stopped.is_set()
    assert not adapter._event_tasks


async def test_runner_return_also_cleans_up_handlers(fake_client):
    adapter = lifecycle_adapter()
    handler_started = asyncio.Event()

    async def handler(msg):
        handler_started.set()
        await asyncio.Event().wait()

    adapter.im._on_private_message = handler
    await adapter.start()
    task = adapter._client_task
    callback = None
    try:
        await wait_until_started(adapter)
        callback = asyncio.create_task(adapter.bot.event_callbacks["private"][0](inbound_message()))
        await asyncio.wait_for(handler_started.wait(), timeout=1)
        adapter.bot.release.set()
        await asyncio.wait_for(task, timeout=1)
        assert callback.cancelled()
        assert adapter.bot.shutdown_event.is_set()
        assert not adapter._event_tasks
    finally:
        await adapter.stop()


@pytest.mark.parametrize("group_info", [
    None,
    {},
    {"data": None},
    {"data": {}},
    {"data": {"group_name": None}},
    {"data": {"group_name": ""}},
])
async def test_group_notice_survives_missing_group_lookup_data(group_info):
    adapter = make_adapter({"group_allow_list": [123]})
    adapter.bot = AsyncMock()
    adapter.bot.get_group_info.return_value = group_info
    adapter.bot.get_user_info.return_value = {"data": {"nickname": "alice"}}
    msg = {
        "notice_type": "notify", "sub_type": "poke",
        "self_id": 10000, "target_id": "10000",
        "user_id": 456, "group_id": 123, "time": 1700000000,
        "action": "nudged", "suffix": "gently",
    }

    await adapter.im._on_notice_message(msg)

    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == "qq:gm:123"
    assert event.message.group.group_name == "123"
    assert event.message.is_notice
    assert event.message.is_mentioned
    assert "nudged" in event.message.chain[0].text
    assert "gently" in event.message.chain[0].text
    assert event.message.raw_message is msg
    adapter.bot.get_group_info.assert_awaited_once_with(group_id=123)


async def test_webui_stop_with_real_client_logs_one_stop_without_disconnect_warning(monkeypatch):
    from core.adapter.src.qq.napcat_client import client as napcat_client
    from tests.test_napcat_ws_client import (
        YieldingCloseWebSocket, lifecycle_meta_frame, patch_ws_factory, wait_until,
    )
    adapter = lifecycle_adapter()
    adapter.bot.close = AsyncMock(wraps=adapter.bot.close)
    ws = YieldingCloseWebSocket([lifecycle_meta_frame()])
    calls = patch_ws_factory(monkeypatch, ws)
    logs = Mock()
    monkeypatch.setattr(napcat_client, "logger", logs)
    await adapter.start()
    runner = adapter._client_task
    try:
        await wait_until(lambda: bool(ws.actions))
        echo = ws.actions[0]["echo"]
        ws.push(json.dumps({
            "status": "ok", "retcode": 0,
            "data": {"user_id": 10000}, "echo": echo,
        }))
        await wait_until(lambda: any("登录成功" in call.args[0] for call in logs.info.call_args_list))
        await adapter.stop()
        await adapter.stop()
        assert runner.done()
        assert adapter._client_task is None
        assert adapter.bot._listening_task.done()
        assert not adapter._event_tasks
        assert calls and len(calls) == 1
        assert ws.close_count == 1
        adapter.bot.close.assert_awaited_once()
        logs.warning.assert_not_called()
        logs.error.assert_not_called()
        stopped = [call for call in logs.info.call_args_list if "已停止监听" in call.args[0]]
        assert len(stopped) == 1
    finally:
        await adapter.stop()
