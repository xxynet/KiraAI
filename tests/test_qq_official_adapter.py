import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.adapter_lifecycle import start_adapter

from core.adapter.adapter_info import AdapterInfo
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.adapter.src.qq_official import im as im_module
from core.adapter.src.qq_official.im import QQOfficialIMCapability
from core.adapter.src.qq_official import qq_official
from core.adapter.src.qq_official.qq_official import QQOfficialAdapter
from core.chat import MessageChain
from core.chat.message_elements import At, Emoji, File, Image, Record, Reply, Text


def test_qq_official_schema_starts_with_setup_info():
    schema_path = Path(__file__).parents[1] / "core" / "adapter" / "src" / "qq_official" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    key, field = next(iter(schema.items()))

    assert key == "setup_info"
    assert field["type"] == "info"
    assert field["level"] == "info"


def make_adapter(permission_mode="allow_list", **config_overrides):
    config = {
        "app_id": "test-app",
        "app_secret": "test-secret",
        "permission_mode": permission_mode,
        "group_allow_list": ["group-openid"],
        "user_allow_list": ["user-openid"],
        "group_deny_list": ["group-denied"],
        "user_deny_list": ["user-denied"],
    }
    config.update(config_overrides)
    info = AdapterInfo(
        adapter_id="qq-official-test", enabled=True, name="qq_official",
        platform="QQ Official", config=config,
    )
    return QQOfficialAdapter(AdapterContext(info=info, event_queue=asyncio.Queue()))


def test_qq_official_defers_botpy_client_creation():
    adapter = make_adapter()

    assert adapter.client is None


def test_qq_official_bounds_reply_state_per_conversation(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION", 2)
    target_id = "user-openid"
    raw_message_ids = ["message-1", "message-2", "message-3"]
    display_message_ids = []
    for raw_message_id in raw_message_ids:
        display_message_ids.append(
            adapter.im._remember_reply_id(False, target_id, raw_message_id)
        )
        adapter.im._send_locks[(False, target_id, raw_message_id)] = object()

    expired_key = (False, target_id, raw_message_ids[0])
    assert (False, target_id, display_message_ids[0]) not in adapter.im._reply_id_aliases
    assert expired_key not in adapter.im._reply_msg_seqs
    assert expired_key not in adapter.im._send_locks
    assert (False, target_id, display_message_ids[1]) in adapter.im._reply_id_aliases
    assert (False, target_id, display_message_ids[2]) in adapter.im._reply_id_aliases


@pytest.mark.asyncio
async def test_qq_official_allow_list_uses_openids():
    adapter = make_adapter()

    assert adapter.im.is_allowed("group-openid", permission="im.group.receive")
    assert adapter.im.is_allowed("user-openid", permission="im.direct.receive")
    assert not adapter.im.is_allowed("other-group", permission="im.group.receive")
    assert not adapter.im.is_allowed("other-user", permission="im.direct.receive")


@pytest.mark.asyncio
async def test_qq_official_deny_list_uses_openids():
    adapter = make_adapter(permission_mode="deny_list")

    assert adapter.im.is_allowed("other-group", permission="im.group.receive")
    assert adapter.im.is_allowed("other-user", permission="im.direct.receive")
    assert not adapter.im.is_allowed("group-denied", permission="im.group.receive")
    assert not adapter.im.is_allowed("user-denied", permission="im.direct.receive")


def test_qq_official_text_content_omits_reply_metadata():
    content = QQOfficialIMCapability._text_content(
        MessageChain([Reply("message-id"), Text("Hello "), At("u1", "Alice"), Emoji("1", "!"), Text(".")])
    )

    assert content == 'Hello <qqbot-at-user id="u1" />!.'


@pytest.mark.asyncio
async def test_qq_official_maps_amr_attachment_to_record():
    message = SimpleNamespace(
        content="",
        attachments=[
            SimpleNamespace(
                url="https://example.com/voice.amr",
                filename="voice.amr",
                content_type="application/octet-stream",
                size=4273,
            )
        ],
    )

    chain = make_adapter().im._message_chain(message, is_group=False, target_id="user-openid")

    assert isinstance(chain.message_list[0], Record)
    assert not isinstance(chain.message_list[0], Image)


@pytest.mark.asyncio
async def test_qq_official_increments_msg_seq_for_multiple_replies():
    adapter = make_adapter()
    sent_payloads = []

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": f"sent-{len(sent_payloads)}"}

    adapter.client = SimpleNamespace(api=SimpleNamespace(post_c2c_message=post_c2c_message))
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter.im._direct_reply_ids["user-openid"] = "incoming-message-id"

    first_result = await adapter.send_direct_message("user-openid", MessageChain([Text("first")]))
    await adapter.send_direct_message("user-openid", MessageChain([Text("second")]))

    assert [payload["msg_seq"] for payload in sent_payloads] == [1, 2]
    assert all(payload["msg_id"] == "incoming-message-id" for payload in sent_payloads)
    assert first_result.message_id.startswith("qqo-")
    assert adapter.im._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(first_result.message_id), Text("reply")]),
    ) == "incoming-message-id"


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_local_file():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "file-uuid", "file_info": "file-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-file"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter.im._direct_reply_ids["user-openid"] = "incoming-message-id"
    file_path = str(Path(__file__).resolve())

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([File(file_path, name="test.py")])
    )

    assert result.ok
    assert uploads[0]["file_type"] == 4
    assert uploads[0]["file_name"] == "test.py"
    assert uploads[0]["file_data"]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "file-info"}
    assert sent_payloads[0]["content"] is None


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_local_image():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "image-uuid", "file_info": "image-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-image"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter.im._direct_reply_ids["user-openid"] = "incoming-message-id"

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([Image(str(Path(__file__).resolve()), name="image.jpg")])
    )

    assert result.ok
    assert uploads[0]["file_type"] == 1
    assert uploads[0]["file_name"] == "image.jpg"
    assert uploads[0]["file_data"]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "image-info"}


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_image_url():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def post_c2c_file(**payload):
        uploads.append(payload)
        return {"file_uuid": "image-uuid", "file_info": "image-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-image"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            post_c2c_file=post_c2c_file,
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter.im._direct_reply_ids["user-openid"] = "incoming-message-id"

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([Image("https://example.com/image.png")])
    )

    assert result.ok
    assert uploads == [{
        "openid": "user-openid",
        "file_type": 1,
        "url": "https://example.com/image.png",
        "srv_send_msg": False,
    }]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "image-info"}
    assert sent_payloads[0]["content"] is None

@pytest.mark.asyncio
async def test_qq_official_group_file_keeps_reply_message_id():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "file-uuid", "file_info": "file-info", "ttl": 60}

    async def post_group_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-group-file"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_group_message=post_group_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter.im._group_reply_ids["group-openid"] = "incoming-group-message-id"

    result = await adapter.send_group_message(
        "group-openid", MessageChain([File(str(Path(__file__).resolve()), name="test.py")])
    )

    assert result.ok
    assert uploads[0]["group_openid"] == "group-openid"
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["msg_id"] == "incoming-group-message-id"
    assert sent_payloads[0]["media"] == {"file_info": "file-info"}

@pytest.mark.asyncio
async def test_qq_official_uses_short_message_id_alias_for_llm_and_reply():
    adapter = make_adapter()
    raw_message_id = "ROBOT1.0_" + "x" * 300
    message = SimpleNamespace(
        id=raw_message_id,
        content="hello",
        attachments=[],
        author=SimpleNamespace(user_openid="user-openid"),
    )

    await adapter.im._handle_direct_message(message)

    event = adapter._event_queue.get_nowait()
    display_message_id = event.message.message_id
    assert display_message_id.startswith("qqo-")
    assert len(display_message_id) == 14
    assert raw_message_id not in display_message_id
    assert adapter.im._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(display_message_id), Text("reply")]),
    ) == raw_message_id


@pytest.mark.asyncio
async def test_qq_official_reads_quoted_message_with_short_reply_id():
    adapter = make_adapter()
    raw_quote_id = "ROBOT1.0_" + "q" * 300
    message = SimpleNamespace(
        id="incoming-message-id",
        content="我的回复",
        attachments=[],
        author=SimpleNamespace(user_openid="user-openid"),
        message_type=103,
        message_reference=SimpleNamespace(message_id=raw_quote_id),
        msg_elements=[
            SimpleNamespace(
                id=raw_quote_id,
                content="被引用的内容",
                attachments=[],
            )
        ],
    )

    await adapter.im._handle_direct_message(message)

    event = adapter._event_queue.get_nowait()
    reply, text = event.message.chain.message_list
    assert isinstance(reply, Reply)
    assert reply.message_id.startswith("qqo-")
    assert raw_quote_id not in reply.message_id
    assert isinstance(reply.chain.message_list[0], Text)
    assert reply.chain.message_list[0].text == "被引用的内容"
    assert isinstance(text, Text)
    assert text.text == "我的回复"
    assert adapter.im._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(reply.message_id), Text("reply")]),
    ) == "incoming-message-id"


@pytest.mark.asyncio
async def test_qq_official_empty_credentials_do_not_start_adapter(monkeypatch):
    adapter = make_adapter()
    adapter.app_id = ""
    adapter.app_secret = ""
    monkeypatch.setattr(qq_official, "botpy", object())

    with pytest.raises(ValueError, match="AppID and AppSecret"):
        await adapter.start()

    assert adapter.client is None
    assert adapter._client_task is None
    assert not hasattr(adapter, "_login_task")


def sdk_message(group, target_id, sender_id="user-openid"):
    sdk = pytest.importorskip("botpy.message")
    payload = {"id": "incoming-id", "content": "hello", "attachments": []}
    if group:
        payload.update(group_openid=target_id, author={"member_openid": sender_id})
        return sdk.GroupMessage(None, "event-id", payload)
    payload["author"] = {"user_openid": target_id}
    return sdk.C2CMessage(None, "event-id", payload)


async def dispatch_sdk_message(adapter, group, message):
    bridge = SimpleNamespace(adapter=adapter, _closing=False)
    adapter.client = bridge
    callback = (
        qq_official._QQOfficialClient.on_group_at_message_create
        if group else qq_official._QQOfficialClient.on_c2c_message_create
    )
    await callback(bridge, message)


def test_qq_official_registers_a_single_owned_im_capability():
    adapter = make_adapter()
    assert isinstance(adapter, BaseAdapter)
    assert adapter.get_capability(IMCapability) is adapter.im
    assert adapter.im.adapter is adapter
    assert adapter.get_capabilities() == {IMCapability: adapter.im}
    assert not hasattr(adapter, "group_list")
    assert not hasattr(adapter, "user_list")


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("mode,listed,allowed", [
    ("allow_list", True, True), ("allow_list", False, False),
    ("deny_list", True, False), ("deny_list", False, True),
])
async def test_sdk_callback_checks_access_before_publishing_or_caching(group, mode, listed, allowed):
    target_id = "opaque:target/123"
    scope = "group" if group else "user"
    adapter = make_adapter(mode, **{
        f"{scope}_allow_list": [target_id] if listed else [],
        f"{scope}_deny_list": [target_id] if listed else [],
    })
    await dispatch_sdk_message(adapter, group, sdk_message(group, target_id))
    reply_ids = adapter.im._group_reply_ids if group else adapter.im._direct_reply_ids
    if allowed:
        event = adapter.ctx.event_queue.get_nowait()
        kind = "gm" if group else "dm"
        assert event.session.sid == f"qq_official:{kind}:{target_id}"
        assert event.supported_elements == list((await adapter.im.get_message_metadata()).supported_elements)
        assert event.message.self_id == adapter.app_id
        assert reply_ids[target_id] == "incoming-id"
    else:
        assert adapter.ctx.event_queue.empty()
        assert reply_ids == {}
        assert adapter.im._reply_id_aliases == {}
        assert adapter.im._reply_msg_seqs == {}


@pytest.mark.asyncio
async def test_empty_group_whitelist_rejects_even_a_whitelisted_private_sender():
    adapter = make_adapter(group_allow_list=[])
    await dispatch_sdk_message(adapter, True, sdk_message(True, "unlisted-group"))
    assert adapter.ctx.event_queue.empty()
    assert adapter.im._group_reply_ids == {}
    assert adapter.im.is_allowed("user-openid", permission="im.direct.receive")


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_numeric_list_entries_match_sdk_string_ids(group):
    scope = "group" if group else "user"
    adapter = make_adapter(**{f"{scope}_allow_list": [123]})
    await dispatch_sdk_message(adapter, group, sdk_message(group, "123"))
    assert not adapter.ctx.event_queue.empty()


@pytest.mark.parametrize("mode", ["invalid", "ALLOW_LIST", None, [], {}])
def test_invalid_permission_mode_keeps_legacy_default_denial(mode):
    adapter = make_adapter(mode)
    assert not adapter.im.is_allowed("group-openid", permission="im.group.receive")
    assert not adapter.im.is_allowed("user-openid", permission="im.direct.receive")


@pytest.mark.parametrize("value", [None, "group-openid", {"group-openid": True}, 123])
def test_non_list_permission_entries_do_not_grant_access(value):
    adapter = make_adapter(group_allow_list=value)
    assert not adapter.im.is_allowed("group-openid", permission="im.group.receive")


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_sdk_callback_rejects_missing_target_in_deny_mode(group):
    adapter = make_adapter("deny_list")
    await dispatch_sdk_message(adapter, group, sdk_message(group, ""))
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_core_and_legacy_sending_reach_the_same_im_capability(group):
    from unittest.mock import AsyncMock
    from tests.test_adapter_routing import processor_for
    from core.chat import KiraIMSentResult

    adapter = make_adapter()
    method = "send_group_message" if group else "send_direct_message"
    capability_send = AsyncMock(return_value=KiraIMSentResult(message_id="sent-id"))
    setattr(adapter.im, method, capability_send)
    processor = processor_for(adapter)
    chain = MessageChain([Text("reply")])
    kind = "gm" if group else "dm"
    target_id = "opaque:target/123"
    await processor.send_message_chain(f"qq_official:{kind}:{target_id}", chain)
    await getattr(adapter, method)(target_id, chain)
    assert capability_send.await_count == 2
    capability_send.assert_awaited_with(target_id, chain)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_cross_session_tool_uses_qq_official_receive_policy(group):
    from unittest.mock import AsyncMock
    from core.plugin.builtin_plugins.session_tools.main import SessionPlugin

    adapter = make_adapter()
    ctx = SimpleNamespace(
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        publish_notice=AsyncMock(), config={"bot_config": {"bot": {}}},
    )
    plugin = SessionPlugin(ctx, {})
    kind = "gm" if group else "dm"
    target_id = "group-openid" if group else "user-openid"
    event = SimpleNamespace(sid="source:dm:1")
    target = f"qq_official:{kind}:{target_id}"
    assert await plugin.session_send(event, target, "hello") == "message sent"
    assert ctx.publish_notice.await_args.args[0] == target
    assert "Permission denied" in await plugin.session_send(event, f"qq_official:{kind}:unlisted", "hello")
    assert ctx.publish_notice.await_count == 1


@pytest.mark.asyncio
async def test_manager_reload_applies_empty_group_whitelist_and_stops_previous_client(monkeypatch):
    from core.adapter.adapter_registry import AdapterManager

    original_client = qq_official._QQOfficialClient

    class FakeClient:
        on_group_at_message_create = original_client.on_group_at_message_create

        def __init__(self, adapter):
            self.adapter = adapter
            self.closed = False
            self._closing = False
            self.release = asyncio.Event()

        async def start(self, **kwargs):
            await self.release.wait()

        async def close(self):
            self.closed = True
            self._closing = True
            self.release.set()

    class SavingConfig(dict):
        def save_config(self):
            pass

    monkeypatch.setattr(qq_official, "_QQOfficialClient", FakeClient)
    monkeypatch.setattr(qq_official, "botpy", object())
    monkeypatch.setattr(AdapterManager, "_registry", {"QQ Official": QQOfficialAdapter})
    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = SavingConfig({"adapters": {"qq-official-test": {
        "enabled": True, "name": "qq_official", "platform": "QQ Official",
        "config": make_adapter("deny_list").config,
    }}})
    manager.adas_config = manager.kira_config["adapters"]
    try:
        await manager.register_adapter(manager.get_adapter_info("qq-official-test"))
        previous = manager.get_adapter("qq_official")
        previous_client = previous.client
        previous_task = previous._client_task
        await previous_client.on_group_at_message_create(sdk_message(True, "unlisted-group"))
        assert manager.event_queue.get_nowait().session.sid == "qq_official:gm:unlisted-group"

        await manager.update_adapter("qq-official-test", config={
            "permission_mode": "allow_list", "group_allow_list": [],
        })
        current = manager.get_adapter("qq_official")
        assert current is not previous
        assert previous_client.closed
        assert previous_task.done()
        await current.client.on_group_at_message_create(sdk_message(True, "unlisted-group"))
        assert manager.event_queue.empty()
        current_task = current._client_task
        current_client = current.client
    finally:
        await manager.stop_adapter("qq_official")
    assert current_client.closed
    assert current_task.done()
    assert not manager._adapters
    assert not manager._adapter_tasks


@pytest.fixture
def sdk_gateway(monkeypatch):
    from unittest.mock import AsyncMock
    from botpy.connection import ConnectionSession
    from botpy.gateway import BotWebSocket

    opened = asyncio.Queue()
    records = []

    async def login(client, token):
        client._ws_ap = {
            "shards": 1, "url": "wss://example.invalid",
            "session_start_limit": {"remaining": 10, "max_concurrency": 5},
        }
        client._connection = ConnectionSession(
            max_async=5, connect=client.bot_connect, dispatch=client.ws_dispatch,
            loop=asyncio.get_running_loop(), api=client.api,
        )
        client.http.close = AsyncMock()

    async def heartbeat(gateway, interval):
        await asyncio.Event().wait()

    async def connect(gateway):
        socket = SimpleNamespace(closed=False)
        gateway._conn = socket
        heartbeat_task = gateway._connection.loop.create_task(gateway._send_heart(30))
        record = SimpleNamespace(
            task=asyncio.current_task(), heartbeat=heartbeat_task, socket=socket,
        )
        records.append(record)
        try:
            await asyncio.sleep(0)
            opened.put_nowait(record)
            await asyncio.Event().wait()
        finally:
            socket.closed = True

    monkeypatch.setattr(qq_official.botpy.Client, "_bot_login", login)
    monkeypatch.setattr(BotWebSocket, "ws_connect", connect)
    monkeypatch.setattr(BotWebSocket, "_send_heart", heartbeat)
    return SimpleNamespace(opened=opened, records=records)


async def cleanup_sdk_gateway(records):
    tasks = [task for record in records for task in (record.task, record.heartbeat)]
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_real_sdk_stop_cancels_independent_gateway_and_heartbeat(sdk_gateway):
    adapter = make_adapter()
    client = None
    try:
        await start_adapter(adapter)
        client = adapter.client
        record = await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        await adapter.stop()
        assert record.task.done(), "SDK gateway runner survived adapter.stop()"
        assert record.heartbeat.done(), "SDK heartbeat survived adapter.stop()"
        assert record.socket.closed
        await client.on_c2c_message_create(sdk_message(False, "user-openid"))
        assert adapter.ctx.event_queue.empty(), "Stopped client still published an event"
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_real_sdk_reload_revokes_removed_target_and_blocks_old_callbacks(monkeypatch, sdk_gateway, group):
    from core.adapter.adapter_registry import AdapterManager

    class SavingConfig(dict):
        def save_config(self):
            pass

    monkeypatch.setattr(AdapterManager, "_registry", {"QQ Official": QQOfficialAdapter})
    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = SavingConfig({"adapters": {"qq-official-test": {
        "enabled": True, "name": "qq_official", "platform": "QQ Official",
        "config": make_adapter().config,
    }}})
    manager.adas_config = manager.kira_config["adapters"]
    target_id = "group-openid" if group else "user-openid"
    callback_name = "on_group_at_message_create" if group else "on_c2c_message_create"
    try:
        await manager.register_adapter(manager.get_adapter_info("qq-official-test"))
        previous = manager.get_adapter("qq_official")
        previous_client = previous.client
        previous_gateway = await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        await getattr(previous_client, callback_name)(sdk_message(group, target_id))
        assert manager.event_queue.qsize() == 1
        manager.event_queue.get_nowait()

        scope = "group" if group else "user"
        await manager.update_adapter("qq-official-test", config={f"{scope}_allow_list": []})
        current = manager.get_adapter("qq_official")
        await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        await getattr(previous_client, callback_name)(sdk_message(group, target_id))
        await getattr(current.client, callback_name)(sdk_message(group, target_id))
        assert manager.event_queue.empty(), "Removed target reached the queue through an old client"
        assert previous_gateway.task.done()
        assert previous_gateway.heartbeat.done()
        assert previous_gateway.socket.closed
        assert current.im._group_reply_ids == {}
        assert current.im._direct_reply_ids == {}
    finally:
        await manager.stop_adapter("qq_official")
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
async def test_real_sdk_stop_drains_already_scheduled_message_callback(monkeypatch, sdk_gateway):
    adapter = make_adapter()
    entered = asyncio.Event()
    published = []
    handler_tasks = []

    async def delayed_handler(message):
        handler_tasks.append(asyncio.current_task())
        entered.set()
        await asyncio.Event().wait()
        published.append(message)

    monkeypatch.setattr(adapter.im, "_handle_direct_message", delayed_handler)
    try:
        await start_adapter(adapter)
        client = adapter.client
        await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        client.ws_dispatch("c2c_message_create", sdk_message(False, "user-openid"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        await adapter.stop()
        assert handler_tasks[0].done()
        assert published == []
        assert client._tasks == set()
        client.ws_dispatch("c2c_message_create", sdk_message(False, "user-openid"))
        await asyncio.sleep(0)
        assert len(handler_tasks) == 1
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
async def test_real_sdk_restart_uses_fresh_client_and_only_current_callback_publishes(sdk_gateway):
    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        previous_client = adapter.client
        await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        await adapter.stop()
        await start_adapter(adapter)
        current_client = adapter.client
        await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        assert current_client is not previous_client
        previous_client.ws_dispatch("c2c_message_create", sdk_message(False, "user-openid"))
        current_client.ws_dispatch("c2c_message_create", sdk_message(False, "user-openid"))
        await asyncio.sleep(0)
        assert adapter.ctx.event_queue.qsize() == 1
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
async def test_real_sdk_http_close_failure_still_cleans_gateway_tasks(sdk_gateway):
    from unittest.mock import AsyncMock

    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        record = await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        adapter.client.http.close = AsyncMock(side_effect=RuntimeError("simulated HTTP close failure"))
        await adapter.stop()
        assert record.task.done()
        assert record.heartbeat.done()
        assert record.socket.closed
        assert adapter.client is None
        assert adapter._client_task is None
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["stop", "reload"])
@pytest.mark.parametrize("group", [False, True])
async def test_real_sdk_stopping_or_reloading_one_instance_keeps_other_instance_alive(monkeypatch, sdk_gateway, action, group):
    from core.adapter.adapter_registry import AdapterManager

    class SavingConfig(dict):
        def save_config(self):
            pass

    monkeypatch.setattr(AdapterManager, "_registry", {"QQ Official": QQOfficialAdapter})
    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = SavingConfig({"adapters": {
        "instance-a": {
            "enabled": True, "name": "official-a", "platform": "QQ Official",
            "config": make_adapter(
                app_id="app-a", user_allow_list=["user-a"], group_allow_list=["group-a"],
            ).config,
        },
        "instance-b": {
            "enabled": True, "name": "official-b", "platform": "QQ Official",
            "config": make_adapter(
                app_id="app-b", user_allow_list=["user-b"], group_allow_list=["group-b"],
            ).config,
        },
    }})
    manager.adas_config = manager.kira_config["adapters"]
    try:
        await manager.register_adapter(manager.get_adapter_info("instance-a"))
        gateway_a = await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        adapter_a = manager.get_adapter("official-a")
        client_a = adapter_a.client
        await manager.register_adapter(manager.get_adapter_info("instance-b"))
        gateway_b = await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)
        adapter_b = manager.get_adapter("official-b")
        client_b = adapter_b.client
        task_b = adapter_b._client_task
        assert client_a is not client_b
        assert client_a._tasks.isdisjoint(client_b._tasks)
        assert client_a.http is not client_b.http

        if action == "stop":
            await manager.stop_adapter("official-a")
        else:
            await manager.update_adapter("instance-a", config={
                "user_allow_list": [], "group_allow_list": [],
            })
            await asyncio.wait_for(sdk_gateway.opened.get(), timeout=2)

        assert gateway_a.task.done()
        assert gateway_a.heartbeat.done()
        assert gateway_a.socket.closed
        assert manager.get_adapter("official-b") is adapter_b
        assert adapter_b.client is client_b
        assert adapter_b._client_task is task_b
        assert not task_b.done()
        assert not gateway_b.task.done()
        assert not gateway_b.heartbeat.done()
        assert not gateway_b.socket.closed
        client_b.http.close.assert_not_awaited()

        target_b = "group-b" if group else "user-b"
        event_name = "group_at_message_create" if group else "c2c_message_create"
        client_a.ws_dispatch(event_name, sdk_message(group, target_b))
        client_b.ws_dispatch(event_name, sdk_message(group, target_b))
        await asyncio.sleep(0)
        assert manager.event_queue.qsize() == 1
        event = manager.event_queue.get_nowait()
        kind = "gm" if group else "dm"
        assert event.session.sid == f"official-b:{kind}:{target_b}"
        assert event.message.self_id == "app-b"
        client_b.ws_dispatch(event_name, sdk_message(group, "unlisted"))
        await asyncio.sleep(0)
        assert manager.event_queue.empty()
    finally:
        await manager.stop_adapter("official-a")
        await manager.stop_adapter("official-b")
        await cleanup_sdk_gateway(sdk_gateway.records)
