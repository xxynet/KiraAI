"""Regression coverage for personal WeChat capability routing and lifecycle."""

import asyncio
import base64
import copy
import hashlib
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from Crypto.Cipher import AES

from core.adapter.adapter_info import AdapterInfo
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.adapter.src.weixin_oc import im as im_module
from core.adapter.src.weixin_oc.im import WeixinOCIMCapability
from core.adapter.src.weixin_oc.weixin_oc import WeixinOCAdapter
from core.adapter.src.weixin_oc.weixin_oc_client import WeixinOCClient
from core.chat import MessageChain
from core.chat.message_elements import Emoji, File, Image, Record, Sticker, Text, Video
from tests.test_adapter_routing import processor_for


pytestmark = pytest.mark.asyncio


class FakeClient:
    aes_padded_size = staticmethod(WeixinOCClient.aes_padded_size)

    def __init__(self):
        self.calls = []
        self.poll_started = asyncio.Event()
        self.poll_cancelled = asyncio.Event()
        self.close_count = 0
        self.responses = []
        self.downloads = []
        self.uploads = []

    async def request_json(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if endpoint == "ilink/bot/getupdates":
            self.poll_started.set()
            if self.responses:
                return self.responses.pop(0)
            try:
                await asyncio.Event().wait()
            finally:
                self.poll_cancelled.set()
        if endpoint == "ilink/bot/getuploadurl":
            return {"upload_param": "fake-upload"}
        return {}

    async def close(self):
        self.close_count += 1

    async def download_and_decrypt_media(self, param, key):
        self.downloads.append((param, key))
        return b"fake-media"

    async def download_cdn_bytes(self, param):
        self.downloads.append((param, None))
        return b"fake-media"

    async def upload_to_cdn(self, *args):
        self.uploads.append(args)
        return "fake-download"


def make_adapter(config=None, name="wechat"):
    settings = {
        "weixin_oc_token": "test-token",
        "weixin_oc_account_id": "test-account",
        "permission_mode": "deny_list",
    }
    settings.update(config or {})
    info = AdapterInfo(
        enabled=True, adapter_id=f"{name}-test", name=name,
        platform="weixin_oc", config=settings,
    )
    adapter = WeixinOCAdapter(AdapterContext(info, asyncio.Queue()))
    adapter.client = FakeClient()
    return adapter


def inbound(user="user:opaque/id", **kwargs):
    message = {
        "from_user_id": user,
        "context_token": "test-context",
        "message_id": "message-123",
        "create_time_ms": 1727000000123,
        "item_list": [{"type": 1, "text_item": {"text": " hello "}}],
    }
    message.update(kwargs)
    return message


async def test_registers_one_owned_im_and_preserves_metadata():
    first, second = make_adapter(), make_adapter(name="other")
    assert isinstance(first, BaseAdapter)
    assert not hasattr(first, "user_list")
    assert first.get_capability(IMCapability) is first.im
    assert isinstance(first.im, WeixinOCIMCapability)
    assert first.get_capabilities() == {IMCapability: first.im}
    assert first.im.adapter is first
    assert first.im is not second.im
    assert first.client is not second.client
    assert first.get_client() is first.client
    assert (await first.im.get_message_metadata()).supported_elements == ["text", "image", "video", "file", "record"]
    assert (await first.im.get_message_metadata()).emojis is None
    assert not first.im.is_allowed("group", permission="im.group.receive")


@pytest.mark.parametrize("mode,listed,expected", [
    ("allow_list", True, True), ("allow_list", False, False),
    ("deny_list", True, False), ("deny_list", False, True),
])
@pytest.mark.parametrize("entry", ["123", 123])
async def test_receive_permissions_use_normalized_ids(mode, listed, expected, entry):
    adapter = make_adapter({
        "permission_mode": mode,
        "user_allow_list": [entry] if listed else [],
        "user_deny_list": [entry] if listed else [],
    })
    await adapter.im._handle_inbound_message(inbound("123"))
    assert adapter.ctx.event_queue.empty() is (not expected)
    assert ("123" in adapter._context_tokens) is expected


@pytest.mark.parametrize("config", [
    {"permission_mode": "invalid", "user_allow_list": ["123"]},
    {"permission_mode": "ALLOW_LIST", "user_allow_list": ["123"]},
    {"permission_mode": "allow_list", "user_allow_list": "123"},
    {"permission_mode": "allow_list", "user_allow_list": None},
    {"permission_mode": "allow_list"},
])
async def test_invalid_or_empty_allow_policy_denies_inbound(config):
    adapter = make_adapter(config)
    await adapter.im._handle_inbound_message(inbound("123"))
    assert adapter.ctx.event_queue.empty()
    assert not adapter._context_tokens


@pytest.mark.parametrize("user", ["", "  ", None])
async def test_missing_sender_is_denied_before_media_download(user):
    adapter = make_adapter()
    await adapter.im._handle_inbound_message(inbound(user))
    assert adapter.ctx.event_queue.empty()
    assert not adapter._context_tokens
    assert not adapter.im.is_allowed(None, permission="im.direct.receive")


async def test_omitted_permission_mode_keeps_legacy_allow_list_default():
    info = AdapterInfo(
        enabled=True, adapter_id="default", name="wechat", platform="weixin_oc",
        config={"user_allow_list": ["123"]},
    )
    adapter = WeixinOCAdapter(AdapterContext(info, asyncio.Queue()))
    assert adapter.im.is_allowed("123", permission="im.direct.receive")
    assert not adapter.im.is_allowed("other", permission="im.direct.receive")


@pytest.mark.parametrize("timestamp,expected", [
    (1727000000123, 1727000000), (1727000000, 1727000000), (None, None),
])
async def test_inbound_event_keeps_native_ids_and_explicit_metadata(timestamp, expected):
    adapter = make_adapter()
    message = inbound(create_time_ms=timestamp)
    await adapter.im._handle_inbound_message(message)
    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == "wechat:dm:user:opaque/id"
    assert event.adapter is adapter.info
    assert event.supported_elements == list((await adapter.im.get_message_metadata()).supported_elements)
    assert event.message.message_id == "message-123"
    assert event.message.self_id == "test-account"
    assert event.message.sender.user_id == "user:opaque/id"
    assert event.message.is_mentioned is True
    assert event.message.extra is message
    assert event.message.chain[0].text == "hello"
    assert event.timestamp == event.message.timestamp
    if expected is not None:
        assert event.timestamp == expected
    else:
        assert event.timestamp > 0
    assert not hasattr(event, "capability_name")


@pytest.mark.parametrize("kind,element,field,filename", [
    (2, Image, "image_item", "image.jpg"),
    (3, Record, "voice_item", "voice.silk"),
    (4, File, "file_item", "report.txt"),
    (5, Video, "video_item", "video.mp4"),
])
async def test_inbound_media_conversion(kind, element, field, filename, tmp_path, monkeypatch):
    monkeypatch.setattr(im_module, "get_data_path", lambda: tmp_path)
    adapter = make_adapter()
    item = {
        "type": kind,
        field: {
            "media": {"encrypt_query_param": "param", "aes_key": "key"},
            "file_name": filename,
        },
    }
    await adapter.im._handle_inbound_message(inbound(item_list=[item]))
    event = adapter.ctx.event_queue.get_nowait()
    segment = event.message.chain[0]
    assert isinstance(segment, element)
    assert adapter.client.downloads == [("param", "key")]
    assert Path(await segment.to_path()).read_bytes() == b"fake-media"
    if kind == 4:
        assert segment.name == filename


@pytest.mark.parametrize("aeskey", ["", "00112233445566778899aabbccddeeff"])
async def test_inbound_image_supports_plain_cdn_and_hex_key(aeskey, tmp_path, monkeypatch):
    monkeypatch.setattr(im_module, "get_data_path", lambda: tmp_path)
    adapter = make_adapter()
    item = {
        "type": 2,
        "image_item": {"media": {"encrypt_query_param": "param"}, "aeskey": aeskey},
    }
    segment = await adapter.im._resolve_inbound_media(item)
    assert isinstance(segment, Image)
    expected_key = base64.b64encode(bytes.fromhex(aeskey)).decode() if aeskey else None
    assert adapter.client.downloads == [("param", expected_key)]


async def test_inbound_media_failure_skips_segment_without_logging_secrets(monkeypatch):
    adapter = make_adapter()
    adapter.logger = Mock()
    monkeypatch.setattr(
        adapter.client, "download_and_decrypt_media",
        AsyncMock(side_effect=RuntimeError("private-body secret-context")),
    )
    item = {
        "type": 2,
        "image_item": {"media": {"encrypt_query_param": "param", "aes_key": "key"}},
    }
    await adapter.im._handle_inbound_message(inbound(item_list=[item, {"type": 1, "text_item": {"text": "kept"}}]))
    event = adapter.ctx.event_queue.get_nowait()
    assert [segment.text for segment in event.message.chain] == ["kept"]
    logged = str(adapter.logger.mock_calls)
    assert "RuntimeError" in logged
    assert "private-body" not in logged
    assert "secret-context" not in logged


async def test_poll_dispatches_dict_messages_with_cursor_and_timeout():
    adapter = make_adapter({"weixin_oc_sync_buf": "previous"})
    adapter.client.responses.append({
        "get_updates_buf": "next", "msgs": [None, inbound(), "invalid"],
    })
    await adapter._poll_inbound_updates()
    event = adapter.ctx.event_queue.get_nowait()
    assert event.session.sid == "wechat:dm:user:opaque/id"
    assert adapter._sync_buf == "next"
    _, endpoint, kwargs = adapter.client.calls[0]
    assert endpoint == "ilink/bot/getupdates"
    assert kwargs["payload"]["get_updates_buf"] == "previous"
    assert kwargs["timeout_ms"] == adapter.long_poll_timeout_ms
    assert kwargs["token_required"] is True


async def test_expired_session_clears_credentials_and_persists_state(monkeypatch):
    adapter = make_adapter({"weixin_oc_sync_buf": "previous"})
    adapter._context_tokens["123"] = "old-context"
    saved = []
    monkeypatch.setattr(adapter, "_persist_account_state", lambda config: saved.append(config))
    adapter.client.responses.append({"ret": 0, "errcode": -14, "errmsg": "secret-response"})
    await adapter._poll_inbound_updates()
    assert adapter.token is None
    assert adapter.client.token is None
    assert adapter._sync_buf == ""
    assert not adapter._context_tokens
    assert saved[0]["weixin_oc_token"] == ""
    assert saved[0]["weixin_oc_sync_buf"] == ""
    assert "secret-response" not in adapter._last_inbound_error


async def test_outbound_text_emoji_merge_preserves_native_request():
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context-for-123"
    result = await adapter.im.send_direct_message(
        123, MessageChain([Text("hello "), Emoji("1", "smile"), Text("!")]),
    )
    assert result.ok
    assert result.message_id is None
    assert len(adapter.client.calls) == 1
    _, endpoint, kwargs = adapter.client.calls[0]
    msg = kwargs["payload"]["msg"]
    assert endpoint == "ilink/bot/sendmessage"
    assert msg["to_user_id"] == "123"
    assert msg["context_token"] == "context-for-123"
    assert msg["item_list"] == [{"type": 1, "text_item": {"text": "hello smile!"}}]
    assert msg["message_type"] == msg["message_state"] == 2
    assert msg["client_id"]


@pytest.mark.parametrize("element,upload_type,item_type", [
    (Image, 1, 2), (Sticker, 1, 2), (Video, 2, 5), (File, 3, 4),
])
async def test_outbound_media_flushes_text_in_order(element, upload_type, item_type, tmp_path):
    path = tmp_path / "media.bin"
    path.write_bytes(b"outgoing-media")
    segment = Sticker(sticker_id="test", sticker=str(path)) if element is Sticker else element(str(path))
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"
    result = await adapter.im.send_direct_message(
        "123", MessageChain([Text("before"), segment, Text("after")]),
    )
    assert result.ok
    calls = adapter.client.calls
    assert calls[0][1] == "ilink/bot/getuploadurl"
    upload = calls[0][2]["payload"]
    assert upload["media_type"] == upload_type
    assert upload["rawsize"] == len(b"outgoing-media")
    assert upload["rawfilemd5"] == hashlib.md5(b"outgoing-media").hexdigest()
    assert upload["filesize"] == WeixinOCClient.aes_padded_size(upload["rawsize"])
    sent = [call[2]["payload"]["msg"]["item_list"] for call in calls[1:]]
    assert [items[0]["type"] for items in sent] == [1, item_type, 1]
    assert sent[0][0]["text_item"]["text"] == "before"
    assert sent[2][0]["text_item"]["text"] == "after"
    assert len(adapter.client.uploads) == 1
    field = {2: "image_item", 4: "file_item", 5: "video_item"}[item_type]
    media_item = sent[1][0][field]
    assert media_item["media"]["encrypt_query_param"] == "fake-download"
    assert base64.b64decode(media_item["media"]["aes_key"]).decode() == upload["aeskey"]
    if item_type == 4:
        assert media_item["len"] == str(len(b"outgoing-media"))
        assert media_item["file_name"] == path.name


@pytest.mark.parametrize("scenario", ["no_login", "no_context", "empty", "unsupported"])
async def test_outbound_unavailable_content_returns_failure(scenario):
    adapter = make_adapter()
    if scenario == "no_login":
        adapter.token = None
    if scenario != "no_context":
        adapter._context_tokens["123"] = "context"
    chain = MessageChain([] if scenario == "empty" else [
        Emoji("1") if scenario == "unsupported" else Text("hello"),
    ])
    result = await adapter.im.send_direct_message("123", chain)
    assert not result.ok
    assert result.err
    assert not adapter.client.calls


async def test_outbound_error_result_does_not_expose_response_body(monkeypatch):
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"
    monkeypatch.setattr(
        adapter.client, "request_json", AsyncMock(side_effect=RuntimeError("private-body secret-token")),
    )
    result = await adapter.im.send_direct_message("123", MessageChain([Text("hello")]))
    assert not result.ok
    assert result.err == "RuntimeError"


async def test_group_send_preserves_unsupported_result():
    adapter = make_adapter()
    result = await adapter.im.send_group_message("group", MessageChain([Text("hello")]))
    assert not result.ok
    assert result.message_id is None
    assert result.err == "个人微信不支持群聊消息"
    assert not adapter.client.calls


async def test_adapter_send_entrypoints_delegate_to_owned_capability(monkeypatch):
    adapter = make_adapter()
    result = SimpleNamespace(ok=True)
    direct, group = AsyncMock(return_value=result), AsyncMock(return_value=result)
    monkeypatch.setattr(adapter.im, "send_direct_message", direct)
    monkeypatch.setattr(adapter.im, "send_group_message", group)
    chain = MessageChain([Text("hello")])
    assert await adapter.send_direct_message("123", chain) is result
    assert await adapter.send_group_message("456", chain) is result
    direct.assert_awaited_once_with("123", chain)
    group.assert_awaited_once_with("456", chain)


async def test_core_send_routes_opaque_target_through_im_capability():
    adapter = make_adapter()
    adapter._context_tokens["user:opaque/id"] = "context"
    results = await processor_for(adapter).send_message_chain(
        "wechat:dm:user:opaque/id", MessageChain([Text("hello")]),
    )
    assert results.ok
    assert adapter.client.calls[0][2]["payload"]["msg"]["to_user_id"] == "user:opaque/id"


async def test_start_is_immediate_and_duplicate_start_is_ignored():
    adapter = make_adapter()
    await adapter.start()
    first = adapter._run_task
    try:
        await asyncio.wait_for(adapter.client.poll_started.wait(), 1)
        await adapter.start()
        assert adapter._run_task is first
        assert not first.done()
    finally:
        await adapter.stop()
    assert first.done()
    assert adapter.client.poll_cancelled.is_set()
    assert adapter._run_task is None
    assert adapter.client.close_count == 1


async def test_stop_before_runner_executes_closes_client_once():
    adapter = make_adapter()
    await adapter.start()
    first = adapter._run_task
    await adapter.stop()
    assert first.done()
    assert adapter._run_task is None
    assert adapter.client.close_count == 1


async def test_stop_before_start_and_repeated_stop_are_safe():
    adapter = make_adapter()
    await adapter.stop()
    await adapter.stop()
    assert adapter.client.close_count == 1
    await adapter.start()
    try:
        await asyncio.wait_for(adapter.client.poll_started.wait(), 1)
        assert not adapter._run_task.done()
    finally:
        await adapter.stop()
    assert adapter.client.close_count == 2


async def test_restart_resets_shutdown_and_runs_new_poll_task():
    adapter = make_adapter()
    await adapter.start()
    await asyncio.wait_for(adapter.client.poll_started.wait(), 1)
    first = adapter._run_task
    await adapter.stop()
    adapter.client.poll_started.clear()
    await adapter.start()
    try:
        await asyncio.wait_for(adapter.client.poll_started.wait(), 1)
        assert adapter._run_task is not first
        assert not adapter._shutdown_event.is_set()
        assert adapter.client.close_count == 1
    finally:
        await adapter.stop()
    assert adapter.client.close_count == 2


async def test_stop_cancels_inbound_media_conversion_before_event_publish(monkeypatch):
    adapter = make_adapter()
    converting = asyncio.Event()
    cancelled = asyncio.Event()

    async def blocked_conversion(items):
        converting.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(adapter.im, "_item_list_to_components", blocked_conversion)
    adapter.client.responses.append({"msgs": [inbound()]})
    await adapter.start()
    await asyncio.wait_for(converting.wait(), 1)
    await adapter.stop()
    assert cancelled.is_set()
    assert adapter.ctx.event_queue.empty()
    assert adapter.client.close_count == 1


async def test_concurrent_stop_and_cancelled_waiter_join_same_cleanup(monkeypatch):
    adapter = make_adapter()
    closing = asyncio.Event()
    release = asyncio.Event()
    close_count = 0

    async def delayed_close():
        nonlocal close_count
        close_count += 1
        closing.set()
        await release.wait()

    monkeypatch.setattr(adapter.client, "close", delayed_close)
    await adapter.start()
    await asyncio.wait_for(adapter.client.poll_started.wait(), 1)
    waiter = asyncio.create_task(adapter.stop())
    await asyncio.wait_for(closing.wait(), 1)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    try:
        await adapter.start()
        assert adapter._shutdown_event.is_set()
        assert not adapter._stop_task.done()
    finally:
        release.set()
        await asyncio.gather(adapter.stop(), adapter.stop())
    assert adapter._run_task is None
    assert adapter._stop_task.done()
    assert close_count == 1


async def test_stopping_one_account_does_not_touch_other_account():
    first, second = make_adapter(), make_adapter(name="other")
    await first.start()
    await second.start()
    try:
        await asyncio.wait_for(first.client.poll_started.wait(), 1)
        await asyncio.wait_for(second.client.poll_started.wait(), 1)
        await first.im._handle_inbound_message(inbound("123"))
        assert not second._context_tokens
        await first.stop()
        assert first.client.close_count == 1
        assert second.client.close_count == 0
        assert not second._run_task.done()
    finally:
        await asyncio.gather(first.stop(), second.stop())


async def test_real_client_reopens_owned_http_session_after_close():
    client = WeixinOCClient(
        adapter_id="test", base_url="https://test.invalid", cdn_base_url="https://test.invalid",
        api_timeout_ms=1000,
    )
    await client.ensure_http_client()
    first = client._http_client
    await client.close()
    assert first.is_closed
    await client.ensure_http_client()
    try:
        assert client._http_client is not first
        assert not client._http_client.is_closed
    finally:
        await client.close()


async def test_cdn_crypto_and_json_requests_with_mock_transport(tmp_path):
    requests = []
    raw = b"media-content"
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    ciphertext = AES.new(key, AES.MODE_ECB).encrypt(WeixinOCClient.pkcs7_pad(raw))

    def respond(request):
        requests.append(request)
        if request.url.path.endswith("/upload"):
            assert request.content == ciphertext
            return httpx.Response(200, headers={"x-encrypted-param": "download-param"})
        if request.url.path.endswith("/download"):
            return httpx.Response(200, content=ciphertext)
        return httpx.Response(200, json={"ret": 0})

    client = WeixinOCClient(
        adapter_id="test", base_url="https://test.invalid",
        cdn_base_url="https://cdn.invalid", api_timeout_ms=1234, token="test-token",
    )
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    path = tmp_path / "media.bin"
    path.write_bytes(raw)
    try:
        param = await client.upload_to_cdn("", "upload-param", "file-key", key.hex(), path)
        assert param == "download-param"
        key_b64 = base64.b64encode(key).decode()
        assert await client.download_and_decrypt_media(param, key_b64) == raw
        assert await client.request_json("POST", "ilink/bot/sendmessage", payload={"test": 1}, token_required=True) == {"ret": 0}
        assert requests[-1].headers["Authorization"] == "Bearer test-token"
        assert requests[-1].extensions["timeout"]["read"] == 1.234
    finally:
        await client.close()


@pytest.mark.parametrize("operation", ["upload", "download", "json"])
async def test_client_http_errors_do_not_expose_response_content(operation, tmp_path, monkeypatch):
    client = WeixinOCClient(
        adapter_id="test", base_url="https://test.invalid",
        cdn_base_url="https://cdn.invalid", api_timeout_ms=1000,
    )
    client._http_client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(403, text="private-response secret-key"),
    ))
    path = tmp_path / "media.bin"
    path.write_bytes(b"data")
    try:
        with pytest.raises(RuntimeError) as error:
            if operation == "upload":
                await client.upload_to_cdn("", "param", "key", "00" * 16, path)
            elif operation == "download":
                await client.download_cdn_bytes("param")
            else:
                await client.request_json("POST", "ilink/bot/sendmessage")
        assert "403" in str(error.value)
        assert "private-response" not in str(error.value)
        assert "secret-key" not in str(error.value)
    finally:
        await client.close()

async def test_denied_media_message_does_not_download_or_cache_context():
    adapter = make_adapter({"permission_mode": "allow_list", "user_allow_list": ["allowed"]})
    await adapter.im._handle_inbound_message(inbound(
        "denied",
        item_list=[{"type": 2, "image_item": {
            "media": {"encrypt_query_param": "param", "aes_key": "key"},
        }}],
    ))
    assert not adapter.client.downloads
    assert not adapter._context_tokens
    assert adapter.ctx.event_queue.empty()


async def test_invalidated_account_stops_runner_and_closes_once(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(adapter, "_persist_account_state", Mock())
    adapter.client.responses.append({"errcode": -14})
    await adapter.start()
    task = adapter._run_task
    await asyncio.wait_for(asyncio.shield(task), 1)
    assert adapter.token is None
    assert adapter.client.close_count == 1
    await adapter.stop()
    assert adapter.client.close_count == 1


async def test_stop_during_long_poll_timeout_retry(monkeypatch):
    adapter = make_adapter()
    retry_started = asyncio.Event()
    calls = 0

    async def timeout_then_wait():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise asyncio.TimeoutError
        retry_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(adapter, "_poll_inbound_updates", timeout_then_wait)
    await adapter.start()
    await asyncio.wait_for(retry_started.wait(), 1)
    await adapter.stop()
    assert calls == 2
    assert adapter.client.close_count == 1


async def test_stop_interrupts_error_backoff_without_logging_raw_exception(monkeypatch):
    adapter = make_adapter()
    adapter.logger = Mock()
    failed = asyncio.Event()

    async def fail_poll():
        failed.set()
        raise RuntimeError("private-body secret-token")

    monkeypatch.setattr(adapter, "_poll_inbound_updates", fail_poll)
    await adapter.start()
    await asyncio.wait_for(failed.wait(), 1)
    await adapter.stop()
    logged = str(adapter.logger.mock_calls)
    assert "RuntimeError" in logged
    assert "private-body" not in logged
    assert "secret-token" not in logged
    assert adapter.client.close_count == 1


async def test_account_state_save_failure_keeps_client_in_sync(monkeypatch):
    adapter = make_adapter()
    adapter.token = None
    adapter.logger = Mock()
    monkeypatch.setattr(
        adapter, "_persist_account_state", Mock(side_effect=RuntimeError("secret-response")),
    )
    await adapter._save_account_state()
    assert adapter.client.token is None
    assert adapter.info.config["weixin_oc_token"] == ""
    assert "secret-response" not in str(adapter.logger.mock_calls)


async def test_concurrent_account_saves_preserve_both_accounts(monkeypatch):
    from core.config import config_loader

    first, second = make_adapter(), make_adapter(name="other")
    stored = {"adapters": {
        first.info.adapter_id: {"config": {}},
        second.info.adapter_id: {"config": {}},
    }}
    first_loaded, release = Event(), Event()
    second_entered, second_loaded = Event(), Event()

    class FakeConfig(dict):
        def __init__(self):
            super().__init__(copy.deepcopy(stored))
            if first_loaded.is_set():
                second_loaded.set()
            else:
                first_loaded.set()
                if not release.wait(5):
                    raise RuntimeError("test save timed out")

        def save_config(self):
            stored.update(copy.deepcopy(self))

    monkeypatch.setattr(config_loader, "KiraConfig", FakeConfig)
    persist_second = second._persist_account_state

    def second_worker(config):
        second_entered.set()
        persist_second(config)

    monkeypatch.setattr(second, "_persist_account_state", second_worker)
    first_task = asyncio.create_task(first._save_account_state())
    second_task = None
    try:
        assert await asyncio.to_thread(first_loaded.wait, 1)
        second_task = asyncio.create_task(second._save_account_state())
        assert await asyncio.to_thread(second_entered.wait, 1)
        assert not second_loaded.is_set()
    finally:
        release.set()
        await asyncio.gather(*[task for task in (first_task, second_task) if task])
    assert second_loaded.is_set()
    assert stored["adapters"][first.info.adapter_id]["config"] == first.info.config
    assert stored["adapters"][second.info.adapter_id]["config"] == second.info.config


@pytest.mark.parametrize("element", [Image, Sticker, Video, File])
@pytest.mark.parametrize("failure", ["resolve", "prepare"])
async def test_failed_media_keeps_pending_text(element, failure, tmp_path, monkeypatch):
    path = tmp_path / "media.bin"
    path.write_bytes(b"media")
    segment = Sticker(sticker_id="test", sticker=str(path)) if element is Sticker else element(str(path))
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"
    if failure == "resolve":
        path.unlink()
    else:
        monkeypatch.setattr(
            adapter.im, "_prepare_media_item",
            AsyncMock(side_effect=RuntimeError("fake upload failure")),
        )

    result = await adapter.im.send_direct_message("123", MessageChain([Text("see this"), segment]))

    assert result.ok
    sent = [call[2]["payload"]["msg"]["item_list"] for call in adapter.client.calls
            if call[1] == "ilink/bot/sendmessage"]
    assert sent == [[{"type": 1, "text_item": {"text": "see this"}}]]


async def test_failed_media_preserves_text_and_emoji_for_trailing_flush(tmp_path):
    path = tmp_path / "missing-image.jpg"
    path.write_bytes(b"image")
    segment = Image(str(path))
    path.unlink()
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"

    result = await adapter.im.send_direct_message(
        "123", MessageChain([Text("before "), segment, Emoji("1", "smile"), Text(" after")]),
    )

    assert result.ok
    sent = [call[2]["payload"]["msg"]["item_list"] for call in adapter.client.calls]
    assert sent == [[{"type": 1, "text_item": {"text": "before smile after"}}]]


async def test_failed_media_keeps_text_after_earlier_success(tmp_path):
    first_path = tmp_path / "first.jpg"
    first_path.write_bytes(b"image")
    missing_path = tmp_path / "missing.jpg"
    missing_path.write_bytes(b"image")
    missing = Image(str(missing_path))
    missing_path.unlink()
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"

    result = await adapter.im.send_direct_message(
        "123", MessageChain([Image(str(first_path)), Text("keep this"), missing]),
    )

    assert result.ok
    sent = [call[2]["payload"]["msg"]["item_list"] for call in adapter.client.calls
            if call[1] == "ilink/bot/sendmessage"]
    assert [items[0]["type"] for items in sent] == [2, 1]
    assert sent[1][0]["text_item"]["text"] == "keep this"


async def test_sent_text_is_not_repeated_when_media_context_disappears(tmp_path, monkeypatch):
    path = tmp_path / "media.jpg"
    path.write_bytes(b"image")
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"
    request_json = adapter.client.request_json
    uploads = 0

    async def change_context(method, endpoint, **kwargs):
        nonlocal uploads
        if endpoint == "ilink/bot/getuploadurl":
            uploads += 1
            if uploads == 2:
                adapter._context_tokens["123"] = "new-context"
        result = await request_json(method, endpoint, **kwargs)
        if endpoint == "ilink/bot/sendmessage":
            items = kwargs["payload"]["msg"]["item_list"]
            if items[0]["type"] == 1:
                adapter._context_tokens.pop("123")
        return result

    monkeypatch.setattr(adapter.client, "request_json", change_context)

    result = await adapter.im.send_direct_message(
        "123", MessageChain([Text("only once"), Image(str(path)), Image(str(path))]),
    )

    assert result.ok
    sent = [call[2]["payload"]["msg"]["item_list"] for call in adapter.client.calls
            if call[1] == "ilink/bot/sendmessage"]
    assert [items[0]["type"] for items in sent] == [1, 2]
    assert sent[0][0]["text_item"]["text"] == "only once"


async def test_sent_text_counts_as_success_when_token_expires_before_media(tmp_path, monkeypatch):
    path = tmp_path / "media.jpg"
    path.write_bytes(b"image")
    adapter = make_adapter()
    adapter._context_tokens["123"] = "context"
    request_json = adapter.client.request_json

    async def expire_after_text(method, endpoint, **kwargs):
        result = await request_json(method, endpoint, **kwargs)
        if endpoint == "ilink/bot/sendmessage":
            adapter.token = None
        return result

    monkeypatch.setattr(adapter.client, "request_json", expire_after_text)

    result = await adapter.im.send_direct_message(
        "123", MessageChain([Text("sent"), Image(str(path))]),
    )

    assert result.ok
    sent = [call[2]["payload"]["msg"]["item_list"] for call in adapter.client.calls
            if call[1] == "ilink/bot/sendmessage"]
    assert sent == [[{"type": 1, "text_item": {"text": "sent"}}]]
