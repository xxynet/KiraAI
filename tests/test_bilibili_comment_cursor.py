import asyncio
import sys
import types

import pytest

from core.adapter.adapter_info import AdapterInfo


def _install_bilibili_api_stub() -> None:
    """Provide the minimal bilibili_api surface the adapter imports at module level"""
    package = types.ModuleType("bilibili_api")

    class Credential:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class CommentResourceType:
        VIDEO = "video"

    comment = types.ModuleType("bilibili_api.comment")
    comment.CommentResourceType = CommentResourceType

    utils = types.ModuleType("bilibili_api.utils")
    transformer = types.ModuleType("bilibili_api.utils.aid_bvid_transformer")
    transformer.bvid2aid = lambda bvid: 0
    utils.aid_bvid_transformer = transformer

    package.Credential = Credential
    package.comment = comment
    package.homepage = types.ModuleType("bilibili_api.homepage")
    package.search = types.ModuleType("bilibili_api.search")
    package.utils = utils

    sys.modules["bilibili_api"] = package
    sys.modules["bilibili_api.comment"] = comment
    sys.modules["bilibili_api.utils"] = utils
    sys.modules["bilibili_api.utils.aid_bvid_transformer"] = transformer


try:  # pragma: no cover - depends on the local environment
    import bilibili_api  # noqa: F401
except ModuleNotFoundError:
    _install_bilibili_api_stub()

from core.adapter.src.bilibili.bilibili import BiliBiliAdapter, PROCESSED_COMMENT_ID_LIMIT


BOT_UID = "1"


def build_adapter(last_process_ts: int):
    info = AdapterInfo(
        enabled=True,
        adapter_id="bili-id",
        name="bili-test",
        platform="Bilibili",
        config={"bot_uid": BOT_UID, "message_process_interval": 0},
    )
    queue = asyncio.Queue()
    adapter = BiliBiliAdapter(info, queue)
    adapter.last_process_ts = last_process_ts
    return adapter, queue


def make_comment(cmt_id: int, uid: str, ctime: int, sub_replies=None) -> dict:
    return {
        "comment_id": cmt_id,
        "user": f"user-{uid}",
        "uid": uid,
        "message": f"message-{cmt_id}",
        "ctime": ctime,
        "like": 0,
        "sub_replies": sub_replies or [],
    }


def drain(queue: asyncio.Queue) -> list:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


@pytest.mark.anyio
async def test_sub_reply_does_not_hide_older_top_level_comment():
    adapter, queue = build_adapter(last_process_ts=90)

    bot_thread = make_comment(
        1, BOT_UID, 100,
        sub_replies=[make_comment(3, "3", 115)],
    )
    comments = [bot_thread, make_comment(2, "2", 110)]

    await adapter._handle_new_comment(comments)

    events = drain(queue)
    assert [(e.cmt_id, e.sub_cmt_id) for e in events] == [(2, None), (1, 3)]


@pytest.mark.anyio
async def test_comments_are_published_only_once():
    adapter, queue = build_adapter(last_process_ts=90)

    comments = [
        make_comment(1, BOT_UID, 100, sub_replies=[make_comment(3, "3", 115)]),
        make_comment(2, "2", 110),
    ]

    await adapter._handle_new_comment(comments)
    assert len(drain(queue)) == 2

    await adapter._handle_new_comment(comments)
    assert drain(queue) == []


@pytest.mark.anyio
async def test_second_comment_in_the_same_second_is_not_lost():
    adapter, queue = build_adapter(last_process_ts=90)

    await adapter._handle_new_comment([make_comment(1, "2", 100)])
    assert [e.cmt_id for e in drain(queue)] == [1]
    assert adapter.last_process_ts == 100

    await adapter._handle_new_comment([
        make_comment(1, "2", 100),
        make_comment(2, "3", 100),
    ])
    assert [e.cmt_id for e in drain(queue)] == [2]


@pytest.mark.anyio
async def test_comments_older_than_cursor_are_ignored():
    adapter, queue = build_adapter(last_process_ts=200)

    comments = [
        make_comment(1, BOT_UID, 100, sub_replies=[make_comment(3, "3", 120)]),
        make_comment(2, "2", 110),
    ]

    await adapter._handle_new_comment(comments)
    assert drain(queue) == []
    assert adapter.last_process_ts == 200


@pytest.mark.anyio
async def test_bot_own_comments_are_never_published():
    adapter, queue = build_adapter(last_process_ts=90)

    comments = [make_comment(1, BOT_UID, 100, sub_replies=[make_comment(2, BOT_UID, 110)])]

    await adapter._handle_new_comment(comments)
    assert drain(queue) == []


@pytest.mark.anyio
async def test_processed_id_cache_is_bounded():
    adapter, queue = build_adapter(last_process_ts=0)

    comments = [make_comment(i, "2", i + 1) for i in range(PROCESSED_COMMENT_ID_LIMIT + 50)]
    await adapter._handle_new_comment(comments)

    assert len(drain(queue)) == len(comments)
    assert len(adapter._processed_cmt_ids) == PROCESSED_COMMENT_ID_LIMIT
