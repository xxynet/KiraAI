from datetime import timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from bilibili_api import comment, dynamic, homepage, search

from core.adapter import FeedItem, FeedQuery, FeedRef, FeedSearchQuery
from core.adapter.src.bilibili import client as client_module
from core.adapter.src.bilibili import feed as feed_module
from core.adapter.src.bilibili.feed_content import dynamic_item
from core.chat import MessageChain
from core.chat.message_elements import At, Emoji, Text
from tests.test_bilibili_adapter import make_adapter, reply, sdk_client


def dynamic_data(id="100", type="DYNAMIC_TYPE_WORD", major=None, basic=None):
    return {
        "id_str": id, "type": type,
        "basic": basic or {"comment_type": 17, "comment_id_str": id},
        "modules": {
            "module_author": {"mid": 42, "name": "author", "pub_ts": 123},
            "module_dynamic": {"desc": {"text": "post text"}, "major": major},
            "module_stat": {"like": {"count": 2}, "comment": {"count": 3}},
        },
    }


@pytest.mark.asyncio
async def test_mixed_dynamics_have_common_models_and_do_not_drop_page_tails(monkeypatch):
    adapter = make_adapter()
    draw = dynamic_data("101", "DYNAMIC_TYPE_DRAW", {
        "type": "MAJOR_TYPE_OPUS",
        "opus": {"title": "picture post", "summary": {"text": "summary"}, "pics": [{"url": "//image.test/a", "width": 10, "height": 20}]},
    }, {"comment_type": 11, "comment_id_str": "201", "rid_str": "999"})
    draw["modules"]["module_dynamic"]["desc"] = None
    video = dynamic_data("102", "DYNAMIC_TYPE_AV", {
        "type": "MAJOR_TYPE_ARCHIVE", "archive": {
            "bvid": "BV17x411w7KC", "aid": "170001", "title": "video", "duration_text": "01:20",
            "cover": "//image.test/cover", "jump_url": "//www.bilibili.com/video/BV17x411w7KC",
            "stat": {"play": "1.2万", "danmaku": "2"},
        },
    }, {"comment_type": 1, "comment_id_str": "170001"})
    fetch = AsyncMock(side_effect=[
        {"items": [draw, video], "offset": "next-offset", "has_more": True},
        {"items": [dynamic_data("103")], "has_more": False},
    ])
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_page", fetch)
    page1 = await adapter.feed.get_feed(FeedQuery(source="following", count=1))
    item = page1.items[0]
    assert item.kind == "post" and item.content[0].text == "summary"
    assert item.title == "picture post"
    assert item.comment_target == FeedRef("draw", "201")
    assert item.attachments[0].url == "https://image.test/a"
    assert item.published_at.tzinfo is timezone.utc
    page2 = await adapter.feed.get_feed(FeedQuery(source="following", count=1, cursor=page1.next_cursor))
    item = page2.items[0]
    assert item.kind == "video" and item.ref == FeedRef("dynamic", "102")
    assert item.linked_content == FeedRef("video", "BV17x411w7KC")
    assert item.comment_target == FeedRef("video", "170001")
    assert item.duration == 80 and item.stats["view"] == "1.2万"
    assert fetch.await_count == 1
    page3 = await adapter.feed.get_feed(FeedQuery(source="following", count=3, cursor=page2.next_cursor))
    assert [item.ref.id for item in page3.items] == ["103"]
    assert not page3.has_more
    assert fetch.await_args.kwargs == {"offset": "next-offset", "page": 2}


@pytest.mark.asyncio
async def test_filtered_empty_page_preserves_continuation(monkeypatch):
    adapter = make_adapter()
    fetch = AsyncMock(side_effect=[
        {"items": [dynamic_data()], "has_more": True, "offset": "200"},
        {"items": [dynamic_data("200", "DYNAMIC_TYPE_AV", {"archive": {"bvid": "BV1xx", "title": "video"}})], "has_more": False},
    ])
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_page", fetch)
    page = await adapter.feed.get_feed(FeedQuery(source="following", kinds=("video",)))
    assert not page.items and page.has_more
    page = await adapter.feed.get_feed(FeedQuery(source="following", kinds=("video",), cursor=page.next_cursor))
    assert len(page.items) == 1 and page.items[0].kind == "video"


@pytest.mark.asyncio
async def test_user_feed_and_article_search(monkeypatch):
    adapter = make_adapter()
    user_fetch = AsyncMock(return_value={"items": [dynamic_data()], "has_more": False})
    search_fetch = AsyncMock(return_value={"result": [{
        "id": 123, "title": "<em>article</em>&amp;", "desc": "summary", "mid": 42,
        "author": "author", "image_urls": ["//image.test/cover"], "pubdate": 123,
    }], "numPages": 2})
    monkeypatch.setattr(adapter.get_client(), "get_user_dynamics", user_fetch)
    monkeypatch.setattr(adapter.get_client(), "search_by_type", search_fetch)
    await adapter.feed.get_feed(FeedQuery(source="user", author_id="42"))
    user_fetch.assert_awaited_once_with(42, offset="")
    page = await adapter.feed.search_feed(FeedSearchQuery("article", kind="article"))
    item = page.items[0]
    assert item.kind == "article" and item.title == "article&"
    assert item.ref == item.comment_target == FeedRef("article", "123")
    assert item.author.id == "42" and item.cover_url == "https://image.test/cover"
    await adapter.feed.search_feed(FeedSearchQuery("article", kind="article", cursor=page.next_cursor))
    assert search_fetch.await_args.kwargs["page"] == 2


def test_rich_text_forwarded_articles_audio_and_unknown_cards():
    data = dynamic_data()
    data["modules"]["module_dynamic"]["desc"] = {"rich_text_nodes": [
        {"type": "RICH_TEXT_NODE_TYPE_AT", "rid": "42", "text": "@author"},
        {"type": "RICH_TEXT_NODE_TYPE_EMOJI", "text": "[微笑]"},
    ]}
    item = dynamic_item(data)
    assert isinstance(item.content[0], At) and isinstance(item.content[1], Emoji)
    article = dynamic_data("101", "DYNAMIC_TYPE_ARTICLE", {"article": {"id": 123, "title": "article", "covers": ["//image.test/a"]}})
    forward = dynamic_data("102", "DYNAMIC_TYPE_FORWARD")
    forward["orig"] = article
    item = dynamic_item(forward)
    assert item.kind == "post" and item.original.kind == "article"
    assert item.original.linked_content == FeedRef("article", "123")
    assert item.comment_target == FeedRef("dynamic", "102")
    audio = dynamic_item(dynamic_data("103", "DYNAMIC_TYPE_MUSIC", {"music": {"id": 3, "title": "audio", "jump_url": "//www.bilibili.com/audio/au3"}}))
    assert audio.kind == "audio" and audio.linked_content == FeedRef("audio", "3")
    unknown = dynamic_item(dynamic_data("104", "DYNAMIC_TYPE_FUTURE", {"type": "MAJOR_TYPE_FUTURE"}))
    assert unknown.kind == "unknown" and unknown.ref.id == "104"


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    FeedQuery(count=0), FeedQuery(count=101), FeedQuery(count=True),
    FeedQuery(source="invalid"), FeedQuery(source="recommended", kinds=("post",)),
    FeedQuery(source="user"), FeedQuery(source="user", author_id="bad"),
    FeedQuery(source="following", author_id="bad"), FeedQuery(kinds=("bad",)),
    FeedQuery(extra={"unsupported_filter": True}), FeedQuery(extra=None),
])
async def test_invalid_queries_fail_before_fetching(monkeypatch, query):
    adapter = make_adapter()
    fetch = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "get_recommended_videos", fetch)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_page", fetch)
    monkeypatch.setattr(adapter.get_client(), "get_user_dynamics", fetch)
    with pytest.raises((TypeError, ValueError)):
        await adapter.feed.get_feed(query)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    FeedSearchQuery(" "), FeedSearchQuery("x", kind="post"), FeedSearchQuery("x", kind="audio"),
    FeedSearchQuery(author_id=42), FeedSearchQuery("x", author_id="bad"),
    FeedSearchQuery("x", extra={"unsupported_filter": True}), FeedSearchQuery("x", extra=None),
])
async def test_unsupported_search_does_not_fall_back_to_video(monkeypatch, query):
    adapter = make_adapter()
    fetch = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "search_by_type", fetch)
    with pytest.raises((TypeError, ValueError)):
        await adapter.feed.search_feed(query)
    fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_cursor_is_account_query_scoped_replayable_and_expires(monkeypatch):
    adapter = make_adapter()
    other = make_adapter()
    fetch = AsyncMock(return_value={"item": [{"id": 1, "bvid": "BV1xx"}, {"id": 2, "bvid": "BV2xx"}]})
    monkeypatch.setattr(adapter.get_client(), "get_recommended_videos", fetch)
    first = await adapter.feed.get_feed(FeedQuery(count=1))
    cursor = first.next_cursor
    for query in (FeedQuery(source="following", cursor=cursor), FeedQuery(kinds=("video",), cursor=cursor)):
        with pytest.raises(ValueError, match="cursor"):
            await adapter.feed.get_feed(query)
    with pytest.raises(ValueError, match="cursor"):
        await other.feed.get_feed(FeedQuery(cursor=cursor))
    tail = await adapter.feed.get_feed(FeedQuery(cursor=cursor))
    tail.items[0].title = "modified"
    replay = await adapter.feed.get_feed(FeedQuery(cursor=cursor))
    assert replay.items[0].title != "modified"
    state = adapter.feed._cursors[cursor]
    monkeypatch.setattr(feed_module.time, "monotonic", lambda: state.created_at + 601)
    with pytest.raises(ValueError, match="expired"):
        await adapter.feed.get_feed(FeedQuery(cursor=cursor))
    assert fetch.await_count == 1


@pytest.mark.asyncio
async def test_cursor_storage_is_bounded_and_cleared_on_stop(monkeypatch):
    adapter = make_adapter()
    fetch = AsyncMock(return_value={"item": [{"id": 1}, {"id": 2}]})
    monkeypatch.setattr(adapter.get_client(), "get_recommended_videos", fetch)
    for _ in range(129):
        await adapter.feed.get_feed(FeedQuery(count=1))
    assert len(adapter.feed._cursors) == 128
    await adapter.stop()
    assert not adapter.feed._cursors


@pytest.mark.asyncio
async def test_dynamic_pagination_rejects_nonadvancing_cursor(monkeypatch):
    adapter = make_adapter()
    fetch = AsyncMock(side_effect=[
        {"items": [], "has_more": True, "offset": "100"},
        {"items": [], "has_more": True, "offset": "100"},
    ])
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_page", fetch)
    page = await adapter.feed.get_feed(FeedQuery(source="following"))
    with pytest.raises(RuntimeError, match="did not advance"):
        await adapter.feed.get_feed(FeedQuery(source="following", cursor=page.next_cursor))


@pytest.mark.asyncio
@pytest.mark.parametrize("resource,type_", [
    ("video", comment.CommentResourceType.VIDEO),
    ("article", comment.CommentResourceType.ARTICLE),
    ("draw", comment.CommentResourceType.DYNAMIC_DRAW),
    ("audio", comment.CommentResourceType.AUDIO),
])
async def test_top_level_comments_use_explicit_resources(monkeypatch, resource, type_):
    adapter = make_adapter()
    send = AsyncMock(return_value={"rpid": 123})
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    assert await adapter.feed.send_comment(MessageChain([Text("comment")]), FeedRef(resource, "42")) == {"rpid": 123}
    send.assert_awaited_once_with(text="comment", oid=42, type_=type_, root=None, parent=None, pic=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("native_type,basic,oid,type_", [
    ("DYNAMIC_TYPE_DRAW", {"comment_type": 11, "comment_id_str": "42", "rid_str": "99"}, 42, comment.CommentResourceType.DYNAMIC_DRAW),
    ("DYNAMIC_TYPE_ARTICLE", {"comment_type": 12, "rid_str": "43"}, 43, comment.CommentResourceType.ARTICLE),
    ("DYNAMIC_TYPE_WORD", {"comment_type": 17}, 100, comment.CommentResourceType.DYNAMIC),
    ("DYNAMIC_TYPE_PGC", {"comment_type": 1, "comment_id_str": "44", "rid_str": "99"}, 44, comment.CommentResourceType.VIDEO),
])
async def test_dynamic_comments_resolve_actual_comment_resource(monkeypatch, native_type, basic, oid, type_):
    adapter = make_adapter()
    detail = AsyncMock(return_value={"item": dynamic_data(type=native_type, basic=basic)})
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    await adapter.feed.send_comment(MessageChain([Text("reply")]), FeedRef("dynamic", "100"), root=12, parent=13)
    detail.assert_awaited_once_with(100)
    send.assert_awaited_once_with(text="reply", oid=oid, type_=type_, root=12, parent=13, pic=None)


@pytest.mark.asyncio
async def test_pgc_without_comment_id_cannot_use_episode_id(monkeypatch):
    adapter = make_adapter()
    detail = AsyncMock(return_value={"item": dynamic_data(type="DYNAMIC_TYPE_PGC", basic={"comment_type": 1, "rid_str": "99"})})
    send = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    with pytest.raises(ValueError, match="no supported comment resource"):
        await adapter.feed.send_comment(MessageChain([Text("comment")]), FeedRef("dynamic", "100"))
    send.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("target,kwargs", [
    (FeedRef("video", "42"), {"parent": 1}),
    (FeedRef("video", "42"), {"root": 0}),
    (FeedRef("video", "-1"), {}),
    (FeedRef("other", "42"), {}),
    (FeedRef("dynamic", "bad"), {}),
])
async def test_invalid_comment_target_or_thread_fails_before_sending(monkeypatch, target, kwargs):
    adapter = make_adapter()
    send = AsyncMock()
    detail = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    with pytest.raises(ValueError):
        await adapter.feed.send_comment(MessageChain([Text("comment")]), target, **kwargs)
    send.assert_not_awaited()
    detail.assert_not_awaited()


@pytest.mark.asyncio
async def test_poll_event_keeps_target_when_listening_config_changes(monkeypatch, sdk_client):
    adapter = make_adapter(listening_bvid="BV17x411w7KC", bot_uid="1", message_process_interval=0)
    adapter.feed.last_process_ts = 0

    async def fetch(**kwargs):
        adapter.config["listening_bvid"] = "changed-after-request"
        return {"replies": [reply(1, "2", 10, "comment")]}

    monkeypatch.setattr(comment, "get_comments_lazy", fetch)
    await adapter.feed.check_new_comments()
    event = adapter.ctx.event_queue.get_nowait()
    assert event.target == FeedRef("video", "BV17x411w7KC")


@pytest.mark.asyncio
async def test_native_read_and_comment_operations_use_bound_account(monkeypatch, sdk_client):
    adapter = make_adapter(sessdata="account", bili_jct="csrf")
    client = adapter.get_client()
    recommended = AsyncMock(return_value={})
    following = AsyncMock(return_value={})
    comments = AsyncMock(return_value={})
    send = AsyncMock(return_value={})
    monkeypatch.setattr(homepage, "get_videos", recommended)
    monkeypatch.setattr(dynamic, "get_dynamic_page_info", following)
    monkeypatch.setattr(comment, "get_comments_lazy", comments)
    monkeypatch.setattr(comment, "send_comment", send)
    user_instance = SimpleNamespace(get_dynamics_new=AsyncMock(return_value={}))
    user_factory = Mock(return_value=user_instance)
    monkeypatch.setattr(client_module.user, "User", user_factory)
    await client.get_recommended_videos()
    await client.get_dynamic_page(offset="100", page=2)
    await client.get_comments_lazy(42, comment.CommentResourceType.VIDEO)
    await client.send_comment("text", 42, comment.CommentResourceType.VIDEO)
    await client.get_user_dynamics(42, offset="200")
    for method in (recommended, following, comments, send):
        assert method.await_args.kwargs["credential"] is adapter.credential
    user_factory.assert_called_once_with(42, credential=adapter.credential)
    user_instance.get_dynamics_new.assert_awaited_once_with(offset="200")
    assert following.await_args.kwargs["_type"] is dynamic.DynamicType.ALL


@pytest.mark.asyncio
async def test_native_search_binds_credentials_at_sdk_api_boundary(monkeypatch, sdk_client):
    adapter = make_adapter(sessdata="account", bili_jct="csrf")
    request = Mock()
    request.update_params.return_value = request
    factory = Mock(return_value=request)
    monkeypatch.setattr(client_module.network, "Api", factory)

    async def result():
        return {"result": []}

    request.result = result()
    try:
        assert await adapter.get_client().search_by_type("keyword", search.SearchObjectType.ARTICLE, page=2) == {"result": []}
    finally:
        request.result.close()
    assert factory.call_args.kwargs["credential"] is adapter.credential
    assert factory.call_args.kwargs["wbi"] is True
    request.update_params.assert_called_once_with(keyword="keyword", search_type="article", page=2, page_size=20)


def test_pgc_video_keeps_episode_reference_separate_from_comment_aid():
    item = dynamic_item(dynamic_data(
        type="DYNAMIC_TYPE_PGC",
        major={"pgc": {"epid": 99, "title": "episode", "cover": "//image.test/a", "jump_url": "//www.bilibili.com/bangumi/play/ep99"}},
        basic={"comment_type": 1, "comment_id_str": "42", "rid_str": "99"},
    ))
    assert item.kind == "video"
    assert item.linked_content == FeedRef("episode", "99")
    assert item.comment_target == FeedRef("video", "42")
    assert item.attachments[0].cover_url == "https://image.test/a"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["recommended", "following"])
async def test_author_filter_retains_matching_page_tails_and_scopes_cursor(monkeypatch, source):
    adapter = make_adapter()
    if source == "recommended":
        result = {"item": [
            {"id": 1, "owner": {"mid": 42}},
            {"id": 2, "owner": {"mid": 43}},
            {"id": 3, "owner": {"mid": 42}},
        ]}
        method = "get_recommended_videos"
    else:
        other = dynamic_data("2")
        other["modules"]["module_author"]["mid"] = 43
        result = {"items": [dynamic_data("1"), other, dynamic_data("3")], "has_more": False}
        method = "get_dynamic_page"
    fetch = AsyncMock(return_value=result)
    monkeypatch.setattr(adapter.get_client(), method, fetch)
    first = await adapter.feed.get_feed(FeedQuery(source=source, author_id=42, count=1))
    assert [item.ref.id for item in first.items] == ["1"]
    assert first.has_more
    with pytest.raises(ValueError, match="cursor"):
        await adapter.feed.get_feed(FeedQuery(source=source, author_id=43, cursor=first.next_cursor))
    tail = await adapter.feed.get_feed(FeedQuery(source=source, author_id="42", cursor=first.next_cursor))
    assert [item.ref.id for item in tail.items] == ["3"]
    assert not tail.has_more
    fetch.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["video", "article"])
async def test_search_author_filter_preserves_empty_pages_and_cursor_scope(monkeypatch, kind):
    adapter = make_adapter()
    fetch = AsyncMock(side_effect=[
        {"result": [{"id": 1, "mid": 43}], "numPages": 2},
        {"result": [{"id": 2, "mid": 42}, {"id": 3, "mid": 43}, {"id": 4, "mid": 42}], "numPages": 2},
    ])
    monkeypatch.setattr(adapter.get_client(), "search_by_type", fetch)
    first = await adapter.feed.search_feed(FeedSearchQuery("x", kind=kind, author_id=42, count=1))
    assert not first.items and first.has_more
    with pytest.raises(ValueError, match="cursor"):
        await adapter.feed.search_feed(FeedSearchQuery("x", kind=kind, author_id=43, cursor=first.next_cursor))
    second = await adapter.feed.search_feed(FeedSearchQuery(
        "x", kind=kind, author_id="42", count=1, cursor=first.next_cursor,
    ))
    assert [item.ref.id for item in second.items] == ["2"]
    assert second.has_more
    assert fetch.await_args.kwargs["page"] == 2
    tail = await adapter.feed.search_feed(FeedSearchQuery(
        "x", kind=kind, author_id=42, cursor=second.next_cursor,
    ))
    assert [item.ref.id for item in tail.items] == ["4"]
    assert not tail.has_more
    assert fetch.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("native_type,basic,major,oid,type_", [
    ("DYNAMIC_TYPE_WORD", {"comment_type": 17, "comment_id_str": "100"}, None, 100, comment.CommentResourceType.DYNAMIC),
    ("DYNAMIC_TYPE_DRAW", {"comment_type": 11, "comment_id_str": "201"}, None, 201, comment.CommentResourceType.DYNAMIC_DRAW),
    ("DYNAMIC_TYPE_AV", {"comment_type": 1, "comment_id_str": "170001"}, {"archive": {"bvid": "BV17x411w7KC"}}, 170001, comment.CommentResourceType.VIDEO),
    ("DYNAMIC_TYPE_PGC", {"comment_type": 1, "comment_id_str": "170001", "rid_str": "200"}, {"pgc": {"epid": 200}}, 170001, comment.CommentResourceType.VIDEO),
    ("DYNAMIC_TYPE_FORWARD", {"comment_type": 17, "comment_id_str": "100"}, None, 100, comment.CommentResourceType.DYNAMIC),
])
async def test_returned_mixed_feed_items_can_be_commented_without_platform_refs(monkeypatch, native_type, basic, major, oid, type_):
    adapter = make_adapter()
    data = dynamic_data(type=native_type, basic=basic, major=major)
    if native_type == "DYNAMIC_TYPE_FORWARD":
        data["orig"] = dynamic_data("555", "DYNAMIC_TYPE_ARTICLE", {"article": {"id": 555}})
    fetch = AsyncMock(return_value={"items": [data], "has_more": False})
    detail = AsyncMock()
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_page", fetch)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    page = await adapter.feed.get_feed(FeedQuery(source="following"))
    item = page.items[0]
    original_ref = item.ref
    assert await adapter.feed.send_comment(MessageChain([Text("reply")]), item, root=10, parent=11) == {"rpid": 1}
    send.assert_awaited_once_with(text="reply", oid=oid, type_=type_, root=10, parent=11, pic=None)
    detail.assert_not_awaited()
    assert item.ref is original_ref


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,resource_id,oid,type_", [
    ("video", "BV17x411w7KC", 170001, comment.CommentResourceType.VIDEO),
    ("article", "123", 123, comment.CommentResourceType.ARTICLE),
])
async def test_returned_search_items_can_be_commented_directly(monkeypatch, kind, resource_id, oid, type_):
    adapter = make_adapter()
    data = {"id": oid, "mid": 42}
    if kind == "video":
        data["bvid"] = resource_id
    fetch = AsyncMock(return_value={"result": [data], "numPages": 1})
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "search_by_type", fetch)
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    page = await adapter.feed.search_feed(FeedSearchQuery("x", kind=kind))
    await adapter.feed.send_comment(MessageChain([Text("reply")]), page.items[0])
    send.assert_awaited_once_with(text="reply", oid=oid, type_=type_, root=None, parent=None, pic=None)


@pytest.mark.asyncio
async def test_item_without_comment_target_resolves_its_primary_dynamic_ref(monkeypatch):
    adapter = make_adapter()
    item = FeedItem(FeedRef("dynamic", "100"), "post", MessageChain([Text("post")]))
    detail = AsyncMock(return_value={"item": dynamic_data(
        basic={"comment_type": 11, "comment_id_str": "201"},
    )})
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    await adapter.feed.send_comment(MessageChain([Text("reply")]), item)
    detail.assert_awaited_once_with(100)
    assert send.await_args.kwargs["oid"] == 201
    assert send.await_args.kwargs["type_"] == comment.CommentResourceType.DYNAMIC_DRAW
