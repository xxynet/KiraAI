import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from bilibili_api.session import EventType
from core.adapter.capabilities import FeedCapability, IMCapability
from core.chat import MessageChain
from core.chat.message_elements import Emoji, Image, Text
from core.config.config_field import build_fields
from tests.test_adapter_routing import processor_for
from tests.test_bilibili_adapter import make_adapter, sdk_client

adapter_module = importlib.import_module("core.adapter.src.bilibili.bilibili")
im_module = importlib.import_module("core.adapter.src.bilibili.im")
session_module = importlib.import_module("bilibili_api.session")


def make_im_adapter(**config):
    return make_adapter(**{"sessdata": "test-session", "bot_uid": "99", **config})


def raw_event(content="hello", sender=123):
    return SimpleNamespace(sender_uid=sender, content=content, timestamp=10, msg_key=456)


@pytest.mark.asyncio
async def test_im_enabled_by_default_and_correct_credential_field():
    adapter = make_im_adapter(sessdata="test-session")
    assert set(adapter.capabilities) == {FeedCapability, IMCapability}
    assert adapter.get_capability(IMCapability) is adapter.im
    assert adapter.im.adapter is adapter
    assert adapter.credential.sessdata == "test-session"
    assert (await adapter.im.get_message_metadata()).supported_elements == ["text", "img", "at", "reply", "emoji", "share_video"]
    assert (await adapter.im.get_message_metadata()).emojis["510"] == "[打call]"
    assert make_adapter(enable_im=False).im is None
    assert make_im_adapter(sessdata="", sesdata="misspelled-session").credential.sessdata is None


def test_schema_exposes_translated_im_settings_and_enabled_default():
    schema = json.loads(Path(adapter_module.__file__).with_name("schema.json").read_text(encoding="utf-8"))
    fields = {field.key: field for field in build_fields(schema)}
    assert fields["enable_im"].default is True
    for key in ("enable_im", "permission_mode", "user_allow_list", "user_deny_list"):
        assert schema[key]["name"] and schema[key]["hint"]
        assert set(schema[key]["locales"]["zh"]) == {"name", "hint"}


@pytest.mark.parametrize("config,allowed", [
    ({}, False),
    ({"user_allow_list": [123]}, True),
    ({"user_allow_list": ["123"]}, True),
    ({"user_allow_list": [456]}, False),
    ({"permission_mode": "deny_list"}, True),
    ({"permission_mode": "deny_list", "user_deny_list": [123]}, False),
    ({"permission_mode": "invalid"}, False),
])
@pytest.mark.asyncio
async def test_incoming_permissions_and_unchanged_target(config, allowed):
    adapter = make_im_adapter(**config)
    nickname = AsyncMock(return_value="test-user")
    adapter.im._get_user_nickname = nickname
    await adapter.im._handle_incoming_event(raw_event(), "text")
    assert adapter.im.is_allowed("123", permission="im.direct.receive") is allowed
    assert not adapter.im.is_allowed(None, permission="im.direct.receive")
    assert not adapter.im.is_allowed("123", permission="im.group.receive")
    if allowed:
        event = adapter.ctx.event_queue.get_nowait()
        assert event.session.sid == "bili-test:dm:123"
        assert event.message.message_id == "456"
        assert event.message.self_id == "99"
        assert event.message.chain[0].text == "hello"
        assert event.message.sender.nickname == "test-user"
        assert event.timestamp == 10
        assert event.is_mentioned
        assert event.supported_elements == list((await adapter.im.get_message_metadata()).supported_elements)
        assert not hasattr(event, "capability_name")
    else:
        nickname.assert_not_awaited()
        assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_incoming_picture_and_video_preserve_plugin_behavior():
    adapter = make_im_adapter(permission_mode="deny_list")
    adapter.im._get_user_nickname = AsyncMock(return_value="user")
    data_url = "data:image/png;base64,aW1hZ2U="
    adapter.im._download_image_as_base64_url = AsyncMock(return_value=data_url)
    await adapter.im._handle_incoming_event(raw_event(SimpleNamespace(url="https://image.test/a")), "picture")
    assert isinstance(adapter.ctx.event_queue.get_nowait().message.chain[0], Image)
    adapter.im._download_image_as_base64_url.return_value = ""
    await adapter.im._handle_incoming_event(raw_event(SimpleNamespace(url="https://image.test/a")), "picture")
    assert adapter.ctx.event_queue.get_nowait().message.chain[0].text == "[Picture download failed]"
    video = im_module.BiliVideo(bvid="BV17x411w7KC")
    video.get_info = AsyncMock(return_value={
        "title": "title", "bvid": "BV17x411w7KC", "owner": {"name": "author"},
        "stat": {"view": 100, "like": 7},
    })
    await adapter.im._handle_incoming_event(raw_event(video), "share_video")
    text = adapter.ctx.event_queue.get_nowait().message.chain[0].text
    assert "title" in text and "author" in text and "100" in text and "7" in text
    assert "https://www.bilibili.com/video/BV17x411w7KC" in text


@pytest.mark.asyncio
async def test_nickname_cache_is_account_local(monkeypatch):
    api = SimpleNamespace(get_user_info=AsyncMock(return_value={"name": "test-user"}))
    factory = Mock(return_value=api)
    monkeypatch.setattr(im_module, "BiliUser", factory)
    first, second = make_im_adapter(), make_im_adapter()
    assert await first.im._get_user_nickname(123) == "test-user"
    assert await first.im._get_user_nickname(123) == "test-user"
    assert api.get_user_info.await_count == 1
    await second.im._get_user_nickname(123)
    assert api.get_user_info.await_count == 2
    assert factory.call_args.kwargs["credential"] is second.credential


@pytest.mark.asyncio
async def test_image_download_keeps_cookie_auth_and_timeout_without_logging_secrets(monkeypatch):
    adapter = make_im_adapter(bili_jct="test-csrf", buvid3="test-device", dedeuserid="99")
    adapter.logger = Mock()
    response = SimpleNamespace(headers={"content-type": "image/png"}, content=b"image", raise_for_status=Mock())
    client = SimpleNamespace(get=AsyncMock(return_value=response))
    manager = AsyncMock()
    manager.__aenter__.return_value = client
    factory = Mock(return_value=manager)
    monkeypatch.setattr(im_module.httpx, "AsyncClient", factory)
    assert await adapter.im._download_image_as_base64_url("https://image.test/a") == "data:image/png;base64,aW1hZ2U="
    factory.assert_called_once_with(follow_redirects=True, timeout=30.0)
    assert client.get.await_args.kwargs["cookies"] == {
        "SESSDATA": "test-session", "bili_jct": "test-csrf", "buvid3": "test-device", "DedeUserID": "99",
    }
    client.get.side_effect = RuntimeError("private-cookie-and-message")
    assert await adapter.im._download_image_as_base64_url("https://image.test/private") == ""
    assert "private" not in str(adapter.logger.mock_calls)


@pytest.mark.asyncio
async def test_new_core_route_and_legacy_sending_share_one_implementation(monkeypatch):
    adapter = make_im_adapter()
    send = AsyncMock()
    monkeypatch.setattr(session_module, "send_msg", send)
    chain = MessageChain([Text("hello"), Emoji("510")])
    for send_call in (
        lambda: adapter.im.send_direct_message(user_id="123", message=chain),
        lambda: adapter.send_direct_message(user_id="123", send_message_obj=chain),
        lambda: processor_for(adapter).send_message_chain("bili-test:dm:123", chain),
    ):
        send.reset_mock()
        result = await send_call()
        assert result.ok
        assert [call.args for call in send.await_args_list] == [
            (adapter.credential, 123, EventType.TEXT, "hello[打call]"),
        ]


@pytest.mark.asyncio
async def test_outgoing_images_and_send_failures(monkeypatch):
    from bilibili_api.utils.picture import Picture
    adapter = make_im_adapter()
    adapter.logger = Mock()
    send = AsyncMock()
    monkeypatch.setattr(session_module, "send_msg", send)
    picture = object()
    load = AsyncMock(return_value=picture)
    from_content = Mock(return_value=picture)
    monkeypatch.setattr(Picture, "load_url", load)
    monkeypatch.setattr(Picture, "from_content", from_content)
    chain = MessageChain([Image("https://image.test/a.png"), Image("data:image/png;base64,aW1hZ2U=")])
    assert (await adapter.im.send_direct_message(123, chain)).ok
    load.assert_awaited_once_with("https://image.test/a.png")
    from_content.assert_called_once_with(b"image", "png")
    assert all(call.args[2:] == (EventType.PICTURE, picture) for call in send.await_args_list)
    send.side_effect = RuntimeError("private-message-and-cookie")
    result = await adapter.im.send_direct_message(123, MessageChain([Text("hello")]))
    assert not result.ok and "RuntimeError" in result.err and "private" not in result.err
    assert "private" not in str(adapter.logger.mock_calls)
    empty = make_im_adapter(sessdata="")
    assert not (await empty.send_direct_message(123, chain)).ok


@pytest.fixture
def dm_sessions(monkeypatch):
    sessions = []

    class FakeSession:
        def __init__(self, credential, debug):
            self.credential = credential
            self.handlers = {}
            self.entered = asyncio.Event()
            self.status = 0
            self.sched = SimpleNamespace(running=False, shutdown=Mock())
            self.close = Mock(side_effect=self._close)
            sessions.append(self)

        def on(self, event_type):
            def register(handler):
                self.handlers[event_type] = handler
            return register

        async def start(self, exclude_self):
            assert exclude_self is True
            self.status = 1
            self.sched.running = True
            self.entered.set()
            await asyncio.Event().wait()

        def get_status(self):
            return self.status

        def _close(self):
            self.status = 2

    monkeypatch.setattr(adapter_module, "Session", FakeSession)
    return sessions


@pytest.mark.asyncio
@pytest.mark.parametrize("with_feed", [False, True])
async def test_im_lifecycle_handlers_restart_and_shared_client(monkeypatch, sdk_client, dm_sessions, with_feed):
    adapter = make_im_adapter(permission_mode="deny_list", listening_bvid="BV17x411w7KC" if with_feed else "")
    adapter._log_login_status = AsyncMock()
    adapter.im._get_user_nickname = AsyncMock(return_value="user")
    adapter.feed.check_new_comments = AsyncMock()
    for _ in range(2):
        task = asyncio.create_task(adapter.start())
        for _ in range(30):
            if adapter._dm_session is not None:
                break
            await asyncio.sleep(0)
        session = adapter._dm_session
        await asyncio.wait_for(session.entered.wait(), timeout=1)
        assert set(session.handlers) == {EventType.TEXT, EventType.PICTURE, EventType.SHARE_VIDEO}
        await session.handlers[EventType.TEXT](raw_event())
        assert adapter.ctx.event_queue.get_nowait().session.sid == "bili-test:dm:123"
        await session.handlers[EventType.PICTURE](raw_event(SimpleNamespace()))
        assert adapter.ctx.event_queue.get_nowait().message.chain[0].text == "[Picture]"
        await session.handlers[EventType.SHARE_VIDEO](raw_event(SimpleNamespace()))
        assert adapter.ctx.event_queue.get_nowait().message.chain[0].text == "[Shared Video]"
        assert session.logger.isEnabledFor(20) is False
        await adapter.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        session.close.assert_called_once()
        session.sched.shutdown.assert_called_once_with(wait=False)
        assert adapter._dm_session is None and adapter._dm_task is None
        assert adapter.listening_task is None
        await session.handlers[EventType.TEXT](raw_event())
        assert adapter.ctx.event_queue.empty()
    assert len(dm_sessions) == 2
    assert adapter.feed.check_new_comments.await_count == (2 if with_feed else 0)
    sdk_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_cancels_inflight_message_handler(sdk_client, dm_sessions):
    adapter = make_im_adapter(permission_mode="deny_list")
    adapter._log_login_status = AsyncMock()
    entered = asyncio.Event()

    async def nickname(uid):
        entered.set()
        await asyncio.Event().wait()

    adapter.im._get_user_nickname = nickname
    task = asyncio.create_task(adapter.start())
    for _ in range(30):
        if adapter._dm_session is not None:
            break
        await asyncio.sleep(0)
    session = adapter._dm_session
    await asyncio.wait_for(session.entered.wait(), timeout=1)
    handler = asyncio.create_task(session.handlers[EventType.TEXT](raw_event()))
    await asyncio.wait_for(entered.wait(), timeout=1)
    await asyncio.wait_for(adapter.stop(), timeout=1)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert handler.cancelled()
    assert adapter.ctx.event_queue.empty()
    sdk_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_during_sdk_login_does_not_close_unstarted_scheduler(monkeypatch, sdk_client, dm_sessions):
    adapter = make_im_adapter()
    adapter._log_login_status = AsyncMock()
    entered = asyncio.Event()

    async def starting(session, exclude_self):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(adapter_module.Session, "start", starting)
    task = asyncio.create_task(adapter.start())
    await asyncio.wait_for(entered.wait(), timeout=1)
    session = adapter._dm_session
    await adapter.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    session.close.assert_not_called()
    session.sched.shutdown.assert_not_called()
    assert adapter._dm_session is None
    sdk_client.close.assert_not_awaited()

@pytest.mark.asyncio
async def test_emoji_dictionary_contains_official_native_tokens_only():
    adapter = make_im_adapter()
    assert (await adapter.im.get_message_metadata()).emojis["1"] == "[微笑]"
    assert (await adapter.im.get_message_metadata()).emojis["26"] == "[doge]"
    assert (await adapter.im.get_message_metadata()).emojis["510"] == "[打call]"
    assert all(key.isdigit() for key in (await adapter.im.get_message_metadata()).emojis)
    assert all(token.startswith("[") and token.endswith("]") for token in (await adapter.im.get_message_metadata()).emojis.values())

@pytest.mark.asyncio
async def test_text_and_emoji_merge_without_reordering_images(monkeypatch):
    from bilibili_api.utils.picture import Picture
    adapter = make_im_adapter()
    send = AsyncMock()
    picture = object()
    monkeypatch.setattr(session_module, "send_msg", send)
    monkeypatch.setattr(Picture, "load_url", AsyncMock(return_value=picture))
    chain = MessageChain([
        Text("before"), Emoji("510"), Text("!"),
        Image("https://image.test/a.png"),
        Emoji("26"), Text("after"), Emoji("1"),
    ])
    assert (await adapter.im.send_direct_message(123, chain)).ok
    assert [call.args for call in send.await_args_list] == [
        (adapter.credential, 123, EventType.TEXT, "before[打call]!"),
        (adapter.credential, 123, EventType.PICTURE, picture),
        (adapter.credential, 123, EventType.TEXT, "[doge]after[微笑]"),
    ]


@pytest.mark.asyncio
async def test_emoji_only_chain_and_separate_chains_keep_message_boundaries(monkeypatch):
    adapter = make_im_adapter()
    send = AsyncMock()
    monkeypatch.setattr(session_module, "send_msg", send)
    assert (await adapter.im.send_direct_message(123, MessageChain([Emoji("3")]))).ok
    assert (await adapter.im.send_direct_message(123, MessageChain([Text("next")]))).ok
    assert [call.args for call in send.await_args_list] == [
        (adapter.credential, 123, EventType.TEXT, "[喜欢]"),
        (adapter.credential, 123, EventType.TEXT, "next"),
    ]

@pytest.mark.asyncio
async def test_group_sending_is_unsupported_and_never_falls_back_to_dm(monkeypatch):
    adapter = make_im_adapter()
    send = AsyncMock()
    monkeypatch.setattr(session_module, "send_msg", send)
    assert not hasattr(adapter, "send_group_message")
    with pytest.raises(NotImplementedError, match="does not support group messages"):
        await processor_for(adapter).send_message_chain("bili-test:gm:123", MessageChain([Text("hello")]))
    send.assert_not_awaited()
