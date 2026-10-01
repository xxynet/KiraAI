from __future__ import annotations

from datetime import datetime, timezone
from html import unescape
import re
from typing import Any

from bilibili_api import comment

from core.adapter.feed import FeedAttachment, FeedAuthor, FeedItem, FeedRef
from core.chat.message_elements import At, Emoji, Text
from core.chat.message_utils import MessageChain


COMMENT_RESOURCES = {
    resource.value: resource.name.lower().removeprefix("dynamic_")
    for resource in comment.CommentResourceType
}


def _url(value: str | None) -> str | None:
    return "https:" + value if value and value.startswith("//") else value


def _text(value: str | None) -> str:
    return unescape(re.sub(r"<[^>]*>", "", value or ""))


def _date(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc)
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def _duration(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parts = str(value).strip().split(":")
        result = 0.0
        for part in parts:
            result = result * 60 + float(part)
        return result
    except (TypeError, ValueError):
        return None


def _stats(**values: Any) -> dict[str, int | str]:
    return {key: value for key, value in values.items() if isinstance(value, (int, str))}


def comment_target(item: dict[str, Any]) -> FeedRef | None:
    """Prefer the actual comment ID; rid_str can identify a different resource."""
    basic = item.get("basic") or {}
    try:
        resource_type = COMMENT_RESOURCES[int(basic.get("comment_type", 0))]
    except (KeyError, TypeError, ValueError):
        return None
    resource_id = basic.get("comment_id_str")
    if not resource_id and item.get("type") != "DYNAMIC_TYPE_PGC":
        resource_id = basic.get("rid_str")
    if not resource_id and resource_type == "dynamic":
        resource_id = item.get("id_str")
    if not resource_id or str(resource_id) == "0":
        return None
    return FeedRef(resource_type, str(resource_id))


def video_item(data: dict[str, Any]) -> FeedItem:
    owner = data.get("owner") or {}
    stat = data.get("stat") or {}
    resource_id = data.get("bvid") or data.get("aid") or data.get("id")
    if not resource_id:
        raise ValueError("Bilibili video is missing its resource ID")
    ref = FeedRef("video", str(resource_id))
    author_id = owner.get("mid", data.get("mid"))
    cover = _url(data.get("pic") or data.get("cover"))
    return FeedItem(
        ref=ref, kind="video", comment_target=ref,
        title=_text(data.get("title")),
        content=MessageChain([Text(_text(data.get("description") or data.get("desc")))]),
        author=FeedAuthor(str(author_id) if author_id is not None else None, owner.get("name") or data.get("author")),
        published_at=_date(data.get("pubdate")),
        url=f"https://www.bilibili.com/video/{resource_id}" if data.get("bvid") else f"https://www.bilibili.com/video/av{resource_id}",
        cover_url=cover, duration=_duration(data.get("duration")),
        stats=_stats(
            view=stat.get("view", data.get("play")),
            like=stat.get("like", data.get("like")),
            danmaku=stat.get("danmaku", data.get("video_review")),
        ),
        extra={
            "aid": data.get("aid", data.get("id")), "bvid": data.get("bvid"),
            "tags": data.get("tag"), "duration_text": data.get("duration"),
            "recommend_reason": (data.get("rcmd_reason") or {}).get("content") or "",
        },
    )


def article_item(data: dict[str, Any]) -> FeedItem:
    resource_id = data.get("id") or data.get("cvid")
    if not resource_id:
        raise ValueError("Bilibili article is missing its resource ID")
    ref = FeedRef("article", str(resource_id))
    covers = data.get("image_urls") or []
    if isinstance(covers, str):
        covers = [covers]
    author_id = data.get("mid")
    return FeedItem(
        ref=ref, kind="article", comment_target=ref,
        title=_text(data.get("title")),
        content=MessageChain([Text(_text(data.get("desc") or data.get("description")))]),
        author=FeedAuthor(str(author_id) if author_id is not None else None, data.get("author")),
        published_at=_date(data.get("pubdate")),
        url=f"https://www.bilibili.com/read/cv{resource_id}",
        cover_url=_url(covers[0]) if covers else None,
        stats=_stats(view=data.get("view"), like=data.get("like"), comment=data.get("reply")),
        extra={"cover_urls": [_url(value) for value in covers]},
    )


def _rich_content(description: dict[str, Any]) -> MessageChain:
    elements = []
    for node in description.get("rich_text_nodes") or []:
        text = node.get("orig_text") or node.get("text") or ""
        if node.get("type") == "RICH_TEXT_NODE_TYPE_AT" and node.get("rid"):
            elements.append(At(node["rid"], text.lstrip("@")))
        elif node.get("type") == "RICH_TEXT_NODE_TYPE_EMOJI":
            elements.append(Emoji((node.get("emoji") or {}).get("emoji_id") or text, text))
        else:
            elements.append(Text(text))
    return MessageChain(elements or [Text(description.get("text") or "")])


def dynamic_item(data: dict[str, Any], *, depth: int = 0) -> FeedItem:
    resource_id = data.get("id_str")
    if not resource_id:
        raise ValueError("Bilibili dynamic is missing its resource ID")
    modules = data.get("modules") or {}
    author = modules.get("module_author") or {}
    body = modules.get("module_dynamic") or {}
    major = body.get("major") or {}
    native_type = data.get("type")
    opus = major.get("opus") or {}
    desc = body.get("desc") or opus.get("summary") or {}
    target = comment_target(data)
    item = FeedItem(
        ref=FeedRef("dynamic", str(resource_id)),
        kind="post" if native_type in {"DYNAMIC_TYPE_WORD", "DYNAMIC_TYPE_DRAW", "DYNAMIC_TYPE_FORWARD"} else "unknown",
        content=_rich_content(desc),
        author=FeedAuthor(str(author["mid"]) if author.get("mid") is not None else None, author.get("name")),
        published_at=_date(author.get("pub_ts")),
        url=f"https://t.bilibili.com/{resource_id}", comment_target=target,
        extra={"native_type": native_type, "major_type": major.get("type")},
    )
    stats = modules.get("module_stat") or {}
    item.stats = _stats(**{name: (stats.get(name) or {}).get("count") for name in ("like", "comment", "forward")})
    if native_type == "DYNAMIC_TYPE_FORWARD":
        original = data.get("orig")
        if original and original.get("id_str") and depth < 3:
            item.original = dynamic_item(original, depth=depth + 1)
        return item
    pictures = (major.get("draw") or {}).get("items") or opus.get("pics") or []
    item.attachments = [
        FeedAttachment("image", url=_url(pic.get("src") or pic.get("url")), width=pic.get("width"), height=pic.get("height"))
        for pic in pictures
    ]
    item.title = opus.get("title")
    archive = major.get("archive") or {}
    if archive:
        item.kind = "video"
        item.title = archive.get("title")
        item.extra["description"] = archive.get("desc")
        if not desc:
            item.content = MessageChain([Text(archive.get("desc") or "")])
        item.duration = _duration(archive.get("duration_text") or archive.get("duration"))
        item.cover_url = _url(archive.get("cover"))
        video_id = archive.get("bvid") or archive.get("aid")
        if video_id:
            item.linked_content = FeedRef("video", str(video_id))
        item.attachments.append(FeedAttachment(
            "video", url=_url(archive.get("jump_url")), ref=item.linked_content,
            title=item.title, cover_url=item.cover_url, duration=item.duration,
        ))
        item.stats.update(_stats(view=(archive.get("stat") or {}).get("play"), danmaku=(archive.get("stat") or {}).get("danmaku")))
    elif major.get("pgc"):
        pgc = major["pgc"]
        item.kind = "video"
        item.title = pgc.get("title")
        item.cover_url = _url(pgc.get("cover"))
        if pgc.get("epid"):
            item.linked_content = FeedRef("episode", str(pgc["epid"]))
        item.attachments.append(FeedAttachment(
            "video", url=_url(pgc.get("jump_url")), ref=item.linked_content,
            title=item.title, cover_url=item.cover_url,
        ))
        item.stats.update(_stats(view=(pgc.get("stat") or {}).get("play"), danmaku=(pgc.get("stat") or {}).get("danmaku")))
    elif native_type == "DYNAMIC_TYPE_ARTICLE" or major.get("article"):
        article = major.get("article") or {}
        item.kind = "article"
        item.title = article.get("title") or item.title
        article_id = article.get("id") or (target.id if target and target.resource_type == "article" else None)
        if article_id:
            item.linked_content = FeedRef("article", str(article_id))
        covers = article.get("covers") or []
        item.cover_url = _url(covers[0]) if covers else None
    elif major.get("music"):
        music = major["music"]
        item.kind = "audio"
        item.title = music.get("title")
        item.cover_url = _url(music.get("cover"))
        if music.get("id"):
            item.linked_content = FeedRef("audio", str(music["id"]))
        item.attachments.append(FeedAttachment("audio", url=_url(music.get("jump_url")), ref=item.linked_content, title=item.title, cover_url=item.cover_url))
    return item
