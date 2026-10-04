import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from tests.adapter_lifecycle import start_adapter
from bilibili_api import comment

from core.adapter import FeedItem, FeedRef
from core.chat import MessageChain
from core.chat.message_elements import Text
from tests.test_bilibili_adapter import client_module, make_adapter, reply, sdk_client


def notification(nid=1, rpid=11, timestamp=101, kind="reply", uid=456, root=10, business=1):
    return {
        "id": nid, f"{kind}_time": timestamp,
        "user": {"mid": uid, "nickname": f"user-{uid}"},
        "item": {
            "type": "reply", "business_id": business, "subject_id": 170001,
            "source_id": rpid, "root_id": root, "target_id": root,
            "source_content": f"comment-{rpid}", "root_reply_content": "bot root",
        },
    }


def page(*items, end=True, cursor_id=1, cursor_time=101):
    return {"items": list(items), "cursor": {"is_end": end, "id": cursor_id, "time": cursor_time}}


def setup_listener(monkeypatch, **config):
    monkeypatch.setattr("core.adapter.src.bilibili.comment_notifications.time.time", lambda: 100)
    adapter = make_adapter(bot_uid="123", message_process_interval=0, **config)
    adapter.logger = Mock()
    adapter.get_client().get_reply_notifications = AsyncMock(return_value=page())
    adapter.get_client().get_at_notifications = AsyncMock(return_value=page())
    return adapter


@pytest.mark.asyncio
async def test_replies_and_mentions_publish_replyable_events_once(monkeypatch):
    adapter = setup_listener(monkeypatch)
    client = adapter.get_client()
    client.get_reply_notifications.return_value = page(notification(), notification(uid=123, rpid=12))
    client.get_at_notifications.return_value = page(
        notification(kind="at"), notification(nid=2, rpid=13, kind="at", root=0),
    )
    await adapter.comment_notifications.check()
    first = adapter.ctx.event_queue.get_nowait()
    second = adapter.ctx.event_queue.get_nowait()
    assert (first.comment_id, first.root_comment_id) == (11, 10)
    assert first.commenter_id == "456" and first.commenter_nickname == "user-456"
    assert first.self_id == "123" and first.timestamp == 101
    assert first.comment_content[0].text == "comment-11"
    assert first.root_comment_content[0].text == "bot root"
    assert first.target == FeedRef("video", "170001")
    assert second.comment_id == second.root_comment_id == 13
    assert second.root_comment_content is None
    assert adapter.ctx.event_queue.empty()
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.empty()
    send = AsyncMock(return_value={"rpid": 99})
    monkeypatch.setattr(client, "send_comment", send)
    await adapter.feed.send_comment(
        MessageChain([Text("reply")]), first.target,
        root=first.root_comment_id, parent=first.comment_id,
    )
    assert send.await_args.kwargs["oid"] == 170001
    assert send.await_args.kwargs["root"] == 10 and send.await_args.kwargs["parent"] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("business,resource_type", [(1, "video"), (11, "draw"), (17, "dynamic"), (12, "article"), (14, "audio")])
async def test_notifications_preserve_native_comment_resources(monkeypatch, business, resource_type):
    adapter = setup_listener(monkeypatch)
    item = notification(business=business, root=0)
    item["item"]["type"] = "dynamic" if business == 17 else "reply"
    adapter.get_client().get_reply_notifications.return_value = page(item)
    await adapter.comment_notifications.check()
    event = adapter.ctx.event_queue.get_nowait()
    target = event.target.comment_target if isinstance(event.target, FeedItem) else event.target
    assert target == FeedRef(resource_type, "170001")
    send = AsyncMock(return_value={"rpid": 99})
    detail = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    await adapter.feed.send_comment(
        MessageChain([Text("reply")]), event.target,
        root=event.root_comment_id, parent=event.comment_id,
    )
    assert send.await_args.kwargs["type_"] == comment.CommentResourceType(business)
    assert send.await_args.kwargs["oid"] == 170001
    detail.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_boundary_keeps_distinct_arrivals_in_same_second(monkeypatch):
    adapter = setup_listener(monkeypatch)
    fetch = adapter.get_client().get_reply_notifications
    fetch.return_value = page(notification(timestamp=100), notification(timestamp=101))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    fetch.return_value = page(
        notification(nid=2, rpid=12, timestamp=101), notification(timestamp=101),
        notification(nid=3, rpid=13, timestamp=100),
    )
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 12
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_pagination_failure_retries_without_skipping_comments(monkeypatch):
    adapter = setup_listener(monkeypatch)
    fetch = adapter.get_client().get_reply_notifications
    fetch.side_effect = [
        page(notification(timestamp=105), end=False, cursor_id=91, cursor_time=105),
        RuntimeError("private-comment-and-cookie"),
    ]
    adapter.get_client().get_at_notifications.return_value = page(notification(rpid=15, kind="at"))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 15
    assert adapter.comment_notifications._streams["reply"].last_time == 100
    assert "private" not in str(adapter.logger.mock_calls)
    fetch.side_effect = [
        page(notification(timestamp=105), end=False, cursor_id=91, cursor_time=105),
        page(notification(rpid=12, timestamp=104)),
    ]
    await adapter.comment_notifications.check()
    assert fetch.await_args.kwargs == {"cursor_id": 91, "cursor_time": 105}
    assert adapter.ctx.event_queue.get_nowait().comment_id == 12
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    assert adapter.comment_notifications._streams["reply"].last_time == 105
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_large_backlog_is_deduplicated_as_one_check(monkeypatch):
    adapter = setup_listener(monkeypatch)
    fetch = adapter.get_client().get_reply_notifications
    fetch.side_effect = [
        page(notification(nid=i, rpid=i, timestamp=110-i), end=False, cursor_id=i, cursor_time=110-i)
        for i in range(1, 7)
    ] + [page(notification(rpid=7, timestamp=103))]
    await adapter.comment_notifications.check()
    assert fetch.await_count == 7
    assert fetch.await_args_list[5].kwargs == {"cursor_id": 5, "cursor_time": 105}
    assert adapter.ctx.event_queue.qsize() == 7
    assert adapter.comment_notifications._streams["reply"].last_time == 109
    assert adapter.comment_notifications._streams["reply"].last_id == 1

@pytest.mark.asyncio
async def test_non_comments_and_malformed_items_do_not_block_valid_notifications(monkeypatch):
    adapter = setup_listener(monkeypatch)
    invalid = []
    for key, value in [
        ("type", "danmu"), ("business_id", 999), ("subject_id", 0),
        ("source_id", 0), ("root_id", -1), ("source_content", {}),
        ("root_id", "bad"), ("source_content", " "),
    ]:
        item = notification(kind="at")
        item["item"][key] = value
        invalid.append(item)
    missing_root = notification(kind="at")
    del missing_root["item"]["root_id"]
    adapter.get_client().get_at_notifications.return_value = page(
        None, {}, missing_root, *invalid, notification(kind="at", rpid=15),
    )
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 15
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_reply_to_bot_subcomment_does_not_attribute_third_party_root_to_bot(monkeypatch):
    adapter = setup_listener(monkeypatch)
    item = notification()
    item["item"]["target_id"] = 9
    adapter.get_client().get_reply_notifications.return_value = page(item)
    await adapter.comment_notifications.check()
    event = adapter.ctx.event_queue.get_nowait()
    assert event.root_comment_id == 10 and event.root_comment_content is None


@pytest.mark.asyncio
async def test_video_listener_and_notifications_share_check_deduplication(monkeypatch):
    adapter = setup_listener(monkeypatch, listening_bvid="BV17x411w7KC")
    adapter.feed.last_process_ts = 100
    adapter.get_client().get_comments_lazy = AsyncMock(return_value={"replies": [
        reply(11, "456", 101, "comment-11"),
    ]})
    adapter.get_client().get_reply_notifications.return_value = page(notification(root=0))
    await adapter.comment_notifications.check()
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.qsize() == 1
    await adapter.stop()
    assert not hasattr(adapter.feed, "_seen_comments")


@pytest.mark.asyncio
async def test_notification_sdk_calls_use_account_credentials_and_pagination(monkeypatch, sdk_client):
    adapter = make_adapter(sessdata="session")
    replies = AsyncMock(return_value=page())
    mentions = AsyncMock(return_value=page())
    monkeypatch.setattr(client_module.session, "get_replies", replies)
    monkeypatch.setattr(client_module.session, "get_at", mentions)
    client = adapter.get_client()
    await client.get_reply_notifications(cursor_id=12, cursor_time=34)
    await client.get_at_notifications(cursor_id=56, cursor_time=78)
    replies.assert_awaited_once_with(adapter.credential, last_reply_id=12, reply_time=34)
    mentions.assert_awaited_once_with(adapter.credential, last_uid=56, at_time=78)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["reply", "at"])
async def test_notification_requests_redact_failures_and_timeout(monkeypatch, sdk_client, kind):
    adapter = make_adapter()
    sdk_method = "get_replies" if kind == "reply" else "get_at"
    fetch = adapter.get_client().get_reply_notifications if kind == "reply" else adapter.get_client().get_at_notifications
    monkeypatch.setattr(client_module.session, sdk_method, AsyncMock(side_effect=RuntimeError("private-cookie")))
    with pytest.raises(RuntimeError) as caught:
        await fetch()
    assert "private" not in str(caught.value)
    adapter.get_client().timeout = 0.01

    async def pending(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(client_module.session, sdk_method, pending)
    with pytest.raises(TimeoutError):
        await fetch()


@pytest.mark.asyncio
async def test_notification_lifecycle_without_video_or_im_restarts_and_cancels(monkeypatch, sdk_client):
    adapter = make_adapter(enable_im=False, enable_comment_notifications=True, sessdata="session", bot_uid="123")
    adapter._log_login_status = AsyncMock()
    entered = asyncio.Event()

    async def poll():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(adapter.comment_notifications, "check", poll)
    for _ in range(2):
        entered.clear()
        task = asyncio.create_task(adapter.start())
        await asyncio.wait_for(entered.wait(), timeout=1)
        listener = adapter._comment_task
        assert adapter.listening_task is None and adapter._dm_task is None
        await asyncio.wait_for(adapter.stop(), timeout=1)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert listener.cancelled() and adapter._comment_task is None
    sdk_client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_notifications_default_on_but_require_login(monkeypatch, sdk_client):
    adapter = make_adapter(enable_im=False, sessdata="session", bot_uid="123")
    del adapter.config["enable_comment_notifications"]
    adapter._log_login_status = AsyncMock()
    entered = asyncio.Event()

    async def poll():
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(adapter.comment_notifications, "check", poll)
    task = asyncio.create_task(adapter.start())
    await asyncio.wait_for(entered.wait(), timeout=1)
    await adapter.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    logged_out = make_adapter(enable_im=False, enable_comment_notifications=True)
    logged_out_task = await start_adapter(logged_out)
    await asyncio.sleep(0)
    assert not logged_out_task.done()
    await logged_out.stop()
    await asyncio.gather(logged_out_task, return_exceptions=True)
    assert logged_out._comment_task is None

@pytest.mark.asyncio
async def test_notifications_require_known_account_uid_to_exclude_self(monkeypatch, sdk_client):
    adapter = make_adapter(enable_im=False, enable_comment_notifications=True, sessdata="session")
    adapter._log_login_status = AsyncMock()
    adapter.logger = Mock()
    task = await start_adapter(adapter)
    await asyncio.sleep(0)
    assert not task.done()
    await adapter.stop()
    await asyncio.gather(task, return_exceptions=True)
    assert adapter._comment_task is None
    adapter.logger.warning.assert_called_once_with(
        "Bilibili comment notifications require a verified or configured account UID"
    )


@pytest.mark.asyncio
async def test_repeated_cursor_does_not_advance_boundary_or_duplicate_events(monkeypatch):
    adapter = setup_listener(monkeypatch)
    fetch = adapter.get_client().get_reply_notifications
    fetch.return_value = page(notification(), end=False, cursor_id=1, cursor_time=101)
    await adapter.comment_notifications.check()
    assert fetch.await_count == 2 and adapter.ctx.event_queue.empty()
    assert adapter.comment_notifications._streams["reply"].last_time == 100
    fetch.return_value = page(notification(), notification(rpid=12, timestamp=102))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    assert adapter.ctx.event_queue.get_nowait().comment_id == 12
    assert adapter.ctx.event_queue.empty()

@pytest.mark.asyncio
@pytest.mark.parametrize("first_kind", ["reply", "at"])
async def test_delayed_other_notification_is_compared_with_current_response(monkeypatch, first_kind):
    adapter = setup_listener(monkeypatch)
    client = adapter.get_client()
    first_fetch = client.get_reply_notifications if first_kind == "reply" else client.get_at_notifications
    second_fetch = client.get_at_notifications if first_kind == "reply" else client.get_reply_notifications
    second_kind = "at" if first_kind == "reply" else "reply"
    first_fetch.return_value = page(notification(kind=first_kind))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    second_fetch.return_value = page(notification(kind=second_kind))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.empty()
    assert not hasattr(adapter.feed, "_seen_comments")


@pytest.mark.asyncio
async def test_page_overlap_is_deduplicated_within_check(monkeypatch):
    adapter = setup_listener(monkeypatch)
    fetch = adapter.get_client().get_reply_notifications
    fetch.side_effect = [
        page(notification(timestamp=103), end=False, cursor_id=1, cursor_time=103),
        page(notification(timestamp=103), notification(nid=2, rpid=12, timestamp=102)),
    ]
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 12
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_failed_video_check_does_not_block_account_notifications(monkeypatch):
    adapter = setup_listener(monkeypatch, listening_bvid="BV17x411w7KC")
    adapter.feed.get_comment_events = AsyncMock(side_effect=RuntimeError("private-body"))
    adapter.get_client().get_reply_notifications.return_value = page(notification())
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    assert "private" not in str(adapter.logger.mock_calls)

@pytest.mark.asyncio
async def test_video_and_notification_cursors_keep_same_second_new_comments(monkeypatch):
    adapter = setup_listener(monkeypatch, listening_bvid="BV17x411w7KC")
    client = adapter.get_client()
    client.get_comments_lazy = AsyncMock(return_value={"replies": [reply(11, "456", 101, "first")]})
    client.get_reply_notifications.return_value = page(notification(root=0))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    client.get_comments_lazy.return_value["replies"].append(reply(12, "789", 101, "second"))
    client.get_reply_notifications.return_value = page(
        notification(nid=2, rpid=12, root=0), notification(root=0),
    )
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 12
    assert adapter.ctx.event_queue.empty()
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_delayed_notification_for_video_comment_is_not_republished(monkeypatch):
    adapter = setup_listener(monkeypatch, listening_bvid="BV17x411w7KC")
    client = adapter.get_client()
    client.get_comments_lazy = AsyncMock(return_value={"replies": [reply(11, "456", 101, "first")]})
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.get_nowait().comment_id == 11
    client.get_reply_notifications.return_value = page(notification(root=0))
    await adapter.comment_notifications.check()
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_account_listener_polls_video_once_without_separate_video_task(monkeypatch, sdk_client):
    adapter = setup_listener(
        monkeypatch, enable_im=False, enable_comment_notifications=True,
        sessdata="session", listening_bvid="BV17x411w7KC",
    )
    adapter._log_login_status = AsyncMock()
    adapter.feed.check_new_comments = AsyncMock()
    adapter.feed.get_comment_events = AsyncMock(return_value=[])
    entered = asyncio.Event()

    async def at(**kwargs):
        entered.set()
        return page()

    adapter.get_client().get_at_notifications = at
    task = asyncio.create_task(adapter.start())
    await asyncio.wait_for(entered.wait(), timeout=1)
    assert adapter._comment_task is not None and adapter.listening_task is None
    await adapter.stop()
    with pytest.raises(asyncio.CancelledError):
        await task
    adapter.feed.get_comment_events.assert_awaited_once_with()
    adapter.feed.check_new_comments.assert_not_awaited()
