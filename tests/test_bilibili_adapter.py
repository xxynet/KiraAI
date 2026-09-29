import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import FeedCapability, IMCapability
from core.adapter.context import AdapterContext
from core.adapter.src.bilibili.bilibili import BiliBiliAdapter
from core.adapter.src.bilibili.feed import BiliBiliFeedCapability

adapter_module = importlib.import_module("core.adapter.src.bilibili.bilibili")
client_module = importlib.import_module("core.adapter.src.bilibili.client")
feed_module = importlib.import_module("core.adapter.src.bilibili.feed")


def make_adapter(**config):
    return BiliBiliAdapter(AdapterContext(
        info=AdapterInfo(True, "bili-test", "bili-test", "bilibili", config=config),
        event_queue=asyncio.Queue(),
    ))


def test_adapter_can_disable_im_and_keeps_credentials_account_local():
    first = make_adapter(enable_im=False, sessdata="first-session", dedeuserid="123")
    second = make_adapter(sessdata="second-session", bot_uid="456")
    assert isinstance(first, BaseAdapter)
    assert set(first.capabilities) == {FeedCapability}
    assert isinstance(first.get_capability(FeedCapability), BiliBiliFeedCapability)
    assert first.feed.adapter is first
    assert first.bot_uid == "123"
    assert second.bot_uid == "456"
    assert first.credential is not second.credential
    assert first.credential.sessdata == "first-session"
    assert not hasattr(first, "search")
    assert not hasattr(first, "send_comment")
    with pytest.raises(ValueError, match="found 0"):
        first.get_capability(IMCapability)


@pytest.mark.asyncio
async def test_feed_preserves_video_fields_and_respects_count(monkeypatch):
    adapter = make_adapter()
    item = {
        "id": 1, "bvid": "BV1xx", "title": "video", "duration": 60, "pubdate": 0,
        "owner": {"mid": 123, "name": "uploader"},
        "stat": {"view": 10, "like": 2, "danmaku": 1},
        "rcmd_reason": {"content": "recommended"},
    }
    fetch = AsyncMock(return_value={"item": [item, item]})
    monkeypatch.setattr(feed_module.homepage, "get_videos", fetch)
    result = await adapter.feed.get_feed(1)
    assert len(result) == 1
    assert result[0]["uploader"] == {"uid": 123, "name": "uploader"}
    assert result[0]["recommend_reason"] == "recommended"
    fetch.assert_awaited_once_with(credential=adapter.credential)
    assert await adapter.feed.get_feed(0) == []
    assert await adapter.feed.get_feed(-1) == []
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_search_maps_to_search_feed_and_respects_count(monkeypatch):
    adapter = make_adapter()
    search = AsyncMock(return_value={"result": [
        {"bvid": "BV1xx", "title": '<em class="keyword">video</em>', "pic": "//image.test/a"},
        {"bvid": "BV2xx", "title": "other", "pic": "https://image.test/b"},
        {"bvid": "BV3xx", "title": "extra"},
    ]})
    monkeypatch.setattr(feed_module.search, "search_by_type", search)
    result = await adapter.feed.search_feed("video", 2)
    assert [item["title"] for item in result] == ["video", "other"]
    assert [item["cover_url"] for item in result] == ["https://image.test/a", "https://image.test/b"]
    assert search.await_args.kwargs["page_size"] == 2
    assert search.await_args.kwargs["keyword"] == "video"
    assert await adapter.feed.search_feed("video", 0) == []
    assert search.await_count == 1


@pytest.mark.asyncio
async def test_comment_reply_maps_root_parent_and_credentials(monkeypatch):
    adapter = make_adapter(enable_im=False, listening_bvid="BV17x411w7KC")
    adapter.logger = Mock()
    send = AsyncMock(return_value={"rpid": 345})
    monkeypatch.setattr(feed_module.comment, "send_comment", send)
    result = await adapter.feed.send_comment("reply", 123, 234)
    assert result == {"rpid": 345}
    adapter.logger.debug.assert_called_once_with("回复成功: {'rpid': 345}")
    send.assert_awaited_once_with(
        text="reply", oid=170001, type_=feed_module.comment.CommentResourceType.VIDEO,
        root=123, parent=234, credential=adapter.credential,
    )
    send.side_effect = RuntimeError("test-private-comment-and-cookie")
    with pytest.raises(RuntimeError, match="^Bilibili comment reply failed$"):
        await adapter.feed.send_comment("reply", 123)
    with pytest.raises(ValueError, match="listening_bvid"):
        await make_adapter().feed.send_comment("reply", 123)


def reply(rpid, uid, timestamp, text, replies=None):
    return {
        "rpid": rpid, "member": {"mid": uid, "uname": f"user-{uid}"},
        "content": {"message": text}, "ctime": timestamp, "replies": replies,
    }


@pytest.mark.asyncio
async def test_comment_polling_publishes_root_and_sub_events_without_self_replies(monkeypatch):
    adapter = make_adapter(bot_uid="123", listening_bvid="BV17x411w7KC", message_process_interval=0)
    adapter.feed.last_process_ts = 10
    fetch = AsyncMock(return_value={"replies": [
        reply(1, "456", 11, "root"),
        reply(2, "123", 12, "bot root", [
            reply(3, "789", 13, "sub reply"),
            reply(4, "123", 14, "self reply"),
        ]),
    ]})
    fetch.return_value["replies"][0]["like"] = 7
    fetch.return_value["replies"][1]["replies"][0]["like"] = 3
    handle = AsyncMock(wraps=adapter.feed._handle_new_comments)
    monkeypatch.setattr(adapter.feed, "_handle_new_comments", handle)
    monkeypatch.setattr(feed_module.comment, "get_comments_lazy", fetch)
    await adapter.feed.check_new_comments()
    parsed = handle.await_args.args[0]
    assert parsed[0]["like"] == 7
    assert parsed[1]["like"] == 0
    assert parsed[1]["sub_replies"][0]["like"] == 3
    assert parsed[1]["sub_replies"][1]["like"] == 0
    first = adapter.ctx.event_queue.get_nowait()
    second = adapter.ctx.event_queue.get_nowait()
    assert first.adapter_name == "bili-test"
    assert first.platform == "bilibili"
    assert first.cmt_id == 1
    assert first.cmt_content[0].text == "root"
    assert first.self_id == "123"
    assert second.cmt_id == 2
    assert second.sub_cmt_id == 3
    assert second.sub_cmt_content[0].text == "sub reply"
    assert second.cmt_content[0].text == "bot root"
    assert second.commenter_id == "789"
    assert not hasattr(first, "capability_name")
    await adapter.feed.check_new_comments()
    assert adapter.ctx.event_queue.empty()
    fetch.return_value = {"replies": None}
    await adapter.feed.check_new_comments()


@pytest.fixture
def sdk_client(monkeypatch):
    client = SimpleNamespace(
        get_wrapped_session=Mock(return_value=SimpleNamespace(headers={})),
        close=AsyncMock(),
    )
    monkeypatch.setattr(client_module.network, "select_client", Mock())
    monkeypatch.setattr(client_module.network, "get_client", Mock(return_value=client))
    return client


@pytest.mark.asyncio
async def test_start_without_listener_verifies_account_and_keeps_sdk_client_shared(monkeypatch, sdk_client):
    adapter = make_adapter(enable_im=False, sessdata="test-session", bot_uid="old")
    account = AsyncMock(return_value={"mid": 123, "name": "test-name"})
    monkeypatch.setattr(adapter_module.user, "get_self_info", account)
    adapter.logger = Mock()
    await adapter.start()
    assert adapter.bot_uid == "123"
    assert adapter.get_client() is sdk_client
    assert sdk_client.get_wrapped_session().headers["Accept-Encoding"] == "gzip, deflate"
    assert adapter.listening_task is None
    account.assert_awaited_once_with(adapter.credential)
    adapter.logger.info.assert_called_once_with(
        "Bilibili login status: logged in, nickname=test-name, uid=123"
    )
    account.side_effect = RuntimeError("verification failed " + "x" * 120)
    await adapter._log_login_status()
    adapter.logger.warning.assert_called_once_with(
        "Bilibili login status verification failed: RuntimeError: "
        + str(account.side_effect)[:100]
    )
    await adapter.stop()
    assert adapter.get_client() is None
    sdk_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_cancels_listener_and_allows_restart(sdk_client):
    adapter = make_adapter(enable_im=False, listening_bvid="BV17x411w7KC")
    entered = asyncio.Event()

    async def poll():
        entered.set()
        await asyncio.Event().wait()

    adapter.feed.check_new_comments = poll
    for _ in range(2):
        entered.clear()
        task = asyncio.create_task(adapter.start())
        await asyncio.wait_for(entered.wait(), timeout=1)
        listener = adapter.listening_task
        await adapter.stop()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert listener.done()
        assert adapter.listening_task is None
    sdk_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_polling_logs_error_details_and_retries_after_failure(monkeypatch, sdk_client):
    adapter = make_adapter(enable_im=False, listening_bvid="BV17x411w7KC", listening_interval=1)
    adapter.logger = Mock()
    received = asyncio.Event()
    count = 0

    async def poll():
        nonlocal count
        count += 1
        if count == 1:
            raise RuntimeError("polling request failed")
        received.set()
        await asyncio.Event().wait()

    adapter.feed.check_new_comments = poll
    task = asyncio.create_task(adapter.start())
    await asyncio.wait_for(received.wait(), timeout=3)
    await adapter.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert count == 2
    adapter.logger.error.assert_called_once_with("Bilibili 监听出错: polling request failed")


@pytest.mark.asyncio
async def test_manager_constructs_bilibili_through_adapter_context(monkeypatch, sdk_client):
    from core.adapter.adapter_registry import AdapterManager

    manager = object.__new__(AdapterManager)
    manager._adapters = {}
    manager._adapter_tasks = {}
    manager.event_queue = asyncio.Queue()
    manager.kira_config = {}
    monkeypatch.setattr(manager, "get_adapter_class", lambda platform: BiliBiliAdapter)
    info = make_adapter().info
    await manager.register_adapter(info)
    instance = manager.get_adapter(info.name)
    assert isinstance(instance, BiliBiliAdapter)
    assert instance.ctx.event_queue is manager.event_queue
    assert instance.get_capability(FeedCapability) is instance.feed
    await manager.stop_adapter(info.name)
    assert manager.get_adapter(info.name) is None

@pytest.mark.asyncio
async def test_comment_poll_keeps_all_new_roots_and_replies_against_start_cursor(monkeypatch):
    adapter = make_adapter(bot_uid="123", listening_bvid="BV17x411w7KC", message_process_interval=0)
    adapter.feed.last_process_ts = 10
    fetch = AsyncMock(return_value={"replies": [
        reply(7, "123", 25, "second bot root", [reply(8, "456", 26, "later root reply")]),
        reply(5, "456", 20, "root with shared timestamp"),
        reply(6, "789", 20, "another root with shared timestamp"),
        reply(1, "123", 5, "old bot root", [
            reply(2, "456", 30, "newest reply"),
            reply(3, "789", 20, "earlier reply"),
            reply(4, "123", 99, "self reply"),
        ]),
        reply(9, "456", 9, "old user root", [reply(10, "789", 40, "ignored nested reply")]),
        reply(11, "456", 10, "already processed"),
    ]})
    monkeypatch.setattr(feed_module.comment, "get_comments_lazy", fetch)
    await adapter.feed.check_new_comments()
    events = []
    while not adapter.ctx.event_queue.empty():
        event = adapter.ctx.event_queue.get_nowait()
        events.append((event.cmt_id, event.sub_cmt_id))
    assert events == [(1, 3), (1, 2), (5, None), (6, None), (7, 8)]
    assert adapter.feed.last_process_ts == 30
    await adapter.feed.check_new_comments()
    assert adapter.ctx.event_queue.empty()
