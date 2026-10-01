from __future__ import annotations

import asyncio
import base64
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from datetime import datetime
import uuid
import time
from typing import TYPE_CHECKING, Any

from PIL import Image as PILImage
from bilibili_api import comment, dynamic, search
from bilibili_api.utils.picture import Picture
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

from core.adapter.base import AdapterTargetId
from core.adapter.capabilities import FeedCapability
from core.adapter.feed import FeedItem, FeedPage, FeedPost, FeedQuery, FeedRef, FeedSearchQuery
from core.chat import KiraCommentEvent
from core.chat.message_elements import At, Emoji, Image, Text
from core.chat.message_utils import MessageChain
from core.utils.network import get_file_content

from .feed_content import COMMENT_RESOURCES, article_item, comment_target, dynamic_item, video_item

if TYPE_CHECKING:
    from .bilibili import BiliBiliAdapter


@dataclass
class _FeedCursor:
    key: tuple[Any, ...]
    items: list[FeedItem] = field(default_factory=list)
    offset: str = ""
    page: int = 1
    has_more: bool = False
    created_at: float = field(default_factory=time.monotonic)


class BiliBiliFeedCapability(FeedCapability["BiliBiliAdapter"]):
    def __init__(self, adapter: BiliBiliAdapter):
        super().__init__(adapter)
        self.last_process_ts = int(time.time())
        self._cursors: OrderedDict[str, _FeedCursor] = OrderedDict()

    def clear_cursors(self) -> None:
        self._cursors.clear()

    @staticmethod
    def _validate_count(count: int) -> None:
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError("Feed count must be an integer between 1 and 100")

    def _resume(self, token: str | None, key: tuple[Any, ...]) -> _FeedCursor:
        if token is None:
            return _FeedCursor(key)
        state = self._cursors.get(token) if isinstance(token, str) else None
        if state is None or state.key != key or time.monotonic() - state.created_at > 600:
            raise ValueError("Feed cursor is invalid, expired, or belongs to another query or account")
        return deepcopy(state)

    def _page(self, state: _FeedCursor, count: int) -> FeedPage:
        items = state.items[:count]
        state.items = state.items[count:]
        more = bool(state.items) or state.has_more
        token = None
        if more:
            token = uuid.uuid4().hex
            state.created_at = time.monotonic()
            self._cursors[token] = state
            while len(self._cursors) > 128:
                self._cursors.popitem(last=False)
        return FeedPage(items, next_cursor=token, has_more=more)

    async def get_feed(self, query: FeedQuery) -> FeedPage:
        """Read recommendations or mixed dynamics; count is a per-page maximum.

        Cursors retain unconsumed entries from fixed-size SDK pages. They expire
        after ten minutes or adapter stop and must be used with the same query.
        Author and kind filters apply to each fetched page; an empty page may have_more.
        """
        if not isinstance(query, FeedQuery):
            raise TypeError("get_feed requires FeedQuery")
        self._validate_count(query.count)
        self._validate_query_extra(query.extra)
        if query.source not in {"recommended", "following", "user"}:
            raise ValueError("Unsupported Bilibili feed source")
        if not isinstance(query.kinds, tuple) or any(kind not in {"post", "video", "article", "audio", "unknown"} for kind in query.kinds):
            raise ValueError("Unsupported feed content kind")
        if query.source == "recommended" and any(kind != "video" for kind in query.kinds):
            raise ValueError("Bilibili recommendations only support videos")
        author_id = str(self._resource_id(query.author_id)) if query.author_id is not None else None
        if query.source == "user" and author_id is None:
            raise ValueError("Bilibili user feed requires author_id")
        key = ("feed", query.source, author_id, query.kinds, deepcopy(query.extra))
        state = self._resume(query.cursor, key)
        if state.items:
            return self._page(state, query.count)
        client = self.adapter.get_client()
        if query.source == "recommended":
            data = await client.get_recommended_videos()
            items = [video_item(item) for item in data.get("item") or []]
        else:
            if query.source == "following":
                data = await client.get_dynamic_page(offset=state.offset, page=state.page)
            else:
                data = await client.get_user_dynamics(self._resource_id(query.author_id), offset=state.offset)
            items = [dynamic_item(item) for item in data.get("items") or []]
            state.has_more = bool(data.get("has_more"))
            next_offset = str(data.get("next_offset") or data.get("offset") or "")
            if state.has_more and (not next_offset or next_offset == state.offset):
                raise RuntimeError("Bilibili dynamic pagination did not advance")
            state.offset = next_offset
            state.page += 1
        state.items = [
            item for item in items
            if (not query.kinds or item.kind in query.kinds)
            and (author_id is None or item.author.id == author_id)
        ]
        return self._page(state, query.count)

    async def search_feed(self, query: FeedSearchQuery) -> FeedPage:
        """Search videos or articles by keyword, with per-page author filtering.

        General dynamic search and searches without keywords are unsupported.
        A filtered page may be empty while has_more is true.
        """
        if not isinstance(query, FeedSearchQuery):
            raise TypeError("search_feed requires FeedSearchQuery")
        self._validate_count(query.count)
        self._validate_query_extra(query.extra)
        if not isinstance(query.keyword, str) or not query.keyword.strip():
            raise ValueError("Bilibili feed search requires a non-empty keyword")
        types = {"video": search.SearchObjectType.VIDEO, "article": search.SearchObjectType.ARTICLE}
        if not isinstance(query.kind, str) or query.kind not in types:
            raise ValueError("Bilibili feed search only supports videos and articles")
        author_id = str(self._resource_id(query.author_id)) if query.author_id is not None else None
        state = self._resume(query.cursor, (
            "search", query.keyword, query.kind, author_id, deepcopy(query.extra),
        ))
        if state.items:
            return self._page(state, query.count)
        result = await self.adapter.get_client().search_by_type(
            query.keyword, types[query.kind], page=state.page, page_size=20,
        )
        normalize = video_item if query.kind == "video" else article_item
        items = [normalize(item) for item in result.get("result") or []]
        state.items = [item for item in items if author_id is None or item.author.id == author_id]
        state.has_more = state.page < int(result.get("numPages") or 0)
        state.page += 1
        return self._page(state, query.count)

    @staticmethod
    def _validate_query_extra(extra: dict[str, Any]) -> None:
        if not isinstance(extra, dict):
            raise TypeError("Feed query extra must be a dictionary")
        if extra:
            raise ValueError("Bilibili feed extra filters are not supported")

    @staticmethod
    def _resource_id(value: AdapterTargetId | None) -> int:
        if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).isascii() or not str(value).isdecimal() or int(value) <= 0:
            raise ValueError("Bilibili resource IDs must be positive integers")
        return int(value)

    async def send_post(self, post: FeedPost) -> dict[str, Any]:
        """Publish text and images, with Bilibili-specific options in ``extra``.

        Supported options: topic_id, vote_id, live_reserve_id, send_time
        (a timezone-aware datetime), up_choose_comment, and close_comment.
        Text, At, and Emoji retain their order; images form the dynamic gallery.
        """
        if not isinstance(post, FeedPost) or not isinstance(post.content, MessageChain):
            raise TypeError("Bilibili posts require FeedPost with MessageChain content")
        self._validate_post(post)
        self.adapter.credential.raise_for_no_sessdata()
        self.adapter.credential.raise_for_no_bili_jct()
        try:
            draft = await asyncio.wait_for(self._build_post(post), timeout=60.0)
        except asyncio.TimeoutError:
            raise TimeoutError("Bilibili post preparation timed out") from None
        return await self.adapter.get_client().send_dynamic(draft)

    @staticmethod
    def _validate_post(post: FeedPost) -> None:
        if not isinstance(post.extra, dict):
            raise TypeError("FeedPost.extra must be a dictionary")
        supported = {
            "topic_id", "vote_id", "live_reserve_id", "send_time",
            "up_choose_comment", "close_comment",
        }
        if post.extra.keys() - supported:
            raise ValueError("Unsupported Bilibili post option")
        for key in ("topic_id", "vote_id", "live_reserve_id"):
            if key in post.extra and (type(post.extra[key]) is not int or post.extra[key] <= 0):
                raise ValueError(f"Bilibili post option {key} must be a positive integer")
        for key in ("up_choose_comment", "close_comment"):
            if key in post.extra and type(post.extra[key]) is not bool:
                raise ValueError(f"Bilibili post option {key} must be a boolean")
        if "send_time" in post.extra:
            value = post.extra["send_time"]
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError("Bilibili post send_time must be a timezone-aware datetime")
        if not BiliBiliFeedCapability._validate_content(post.content, mentions=True) and "vote_id" not in post.extra:
            raise ValueError("Bilibili post content must not be empty")

    @staticmethod
    def _validate_content(content: MessageChain, *, mentions: bool = False) -> bool:
        if not isinstance(content, MessageChain):
            raise TypeError("Bilibili content requires MessageChain")
        supported = (Text, Image, Emoji, At) if mentions else (Text, Image, Emoji)
        has_content = False
        for element in content:
            if not isinstance(element, supported):
                raise ValueError("Unsupported Bilibili content element")
            if isinstance(element, Text):
                if not isinstance(element.text, str):
                    raise TypeError("Bilibili text must be a string")
                has_content = has_content or bool(element.text.strip())
            elif isinstance(element, At):
                BiliBiliFeedCapability._resource_id(element.pid)
                has_content = True
            else:
                has_content = True
        return has_content

    async def _emoji_token(self, element: Emoji) -> str:
        token = element.emoji_desc
        if not token:
            await self.adapter._load_emoji_dict()
            token = self.adapter.emoji_dict.get(element.emoji_id)
        if not isinstance(token, str) or not token:
            raise ValueError("Bilibili emoji requires a native token or known ID")
        return token

    async def _build_post(self, post: FeedPost) -> dynamic.BuildDynamic:
        draft = dynamic.BuildDynamic.empty()
        for element in post.content:
            if isinstance(element, Text):
                draft.add_plain_text(element.text)
            elif isinstance(element, At):
                draft.add_at(uid=int(element.pid), uname=element.nickname or "")
            elif isinstance(element, Emoji):
                draft.add_emoji(await self._emoji_token(element))
            elif isinstance(element, Image):
                draft.add_image(await self._load_picture(element))
                if element.caption:
                    draft.add_plain_text(element.caption)
        extra = post.extra
        if "topic_id" in extra:
            draft.set_topic(extra["topic_id"])
        if "vote_id" in extra:
            draft.add_vote(extra["vote_id"])
        if "live_reserve_id" in extra:
            draft.set_attach_card(extra["live_reserve_id"])
        if "send_time" in extra:
            draft.set_send_time(extra["send_time"])
        draft.set_options(
            up_choose_comment=extra.get("up_choose_comment", False),
            close_comment=extra.get("close_comment", False),
        )
        return draft

    @staticmethod
    def _picture_from_bytes(data: bytes) -> Picture:
        with PILImage.open(BytesIO(data)) as image:
            image.verify()
            return Picture(
                content=data, width=image.width, height=image.height,
                imageType=image.format.lower(), size=round(len(data) / 1024),
            )

    async def _load_picture(self, element: Image) -> Picture:
        try:
            if element.file_type == "path":
                data = await asyncio.to_thread(Path(element.file).read_bytes)
            elif element.file_type == "url":
                data = await get_file_content(element.file)
            else:
                encoded = await element.to_base64()
                data = await asyncio.to_thread(base64.b64decode, encoded, validate=True)
            return await asyncio.to_thread(self._picture_from_bytes, data)
        except Exception:
            raise ValueError("Bilibili image could not be loaded") from None

    async def _build_comment(self, message: MessageChain) -> tuple[str, list[Picture]]:
        parts = []
        pictures = []
        for element in message:
            if isinstance(element, Text):
                parts.append(element.text)
            elif isinstance(element, Emoji):
                parts.append(await self._emoji_token(element))
            elif isinstance(element, Image):
                pictures.append(await self._load_picture(element))
                if element.caption:
                    parts.append(element.caption)
        return "".join(parts), pictures

    async def send_comment(
        self, message: MessageChain, target: FeedItem | FeedRef, *,
        root: AdapterTargetId | None = None, parent: AdapterTargetId | None = None,
    ) -> dict[str, Any]:
        """Send a Text/Emoji/Image chain to a feed item, resource, or comment thread.

        Text and emoji order is preserved; images become comment attachments.
        Feed items use their comment target, falling back to their primary reference.
        """

        has_comment_target = isinstance(target, FeedItem) and target.comment_target is not None
        if isinstance(target, FeedItem):
            target = target.comment_target if has_comment_target else target.ref
        if not isinstance(target, FeedRef):
            raise TypeError("Bilibili comments require FeedItem or FeedRef")
        if not self._validate_content(message):
            raise ValueError("Comment content must not be empty")
        if parent is not None and root is None:
            raise ValueError("A parent comment requires a root comment")
        root_id = self._resource_id(root) if root is not None else None
        parent_id = self._resource_id(parent) if parent is not None else None
        client = self.adapter.get_client()
        resource = target
        if target.resource_type == "dynamic" and not has_comment_target:
            detail = await client.get_dynamic_info(self._resource_id(target.id))
            resource = comment_target(detail.get("item") or {})
            if resource is None:
                raise ValueError("Bilibili dynamic has no supported comment resource")
        types = {name: comment.CommentResourceType(value) for value, name in COMMENT_RESOURCES.items()}
        if resource.resource_type not in types:
            raise ValueError("Unsupported Bilibili comment resource type")
        if resource.resource_type == "video" and isinstance(resource.id, str) and resource.id.startswith("BV"):
            try:
                oid = bvid2aid(resource.id)
            except Exception:
                raise ValueError("Invalid Bilibili video target") from None
        else:
            oid = self._resource_id(resource.id)
        try:
            text, pictures = await asyncio.wait_for(self._build_comment(message), timeout=60.0)
        except asyncio.TimeoutError:
            raise TimeoutError("Bilibili comment preparation timed out") from None
        result = await client.send_comment(
            text=text, oid=oid, type_=types[resource.resource_type],
            root=root_id, parent=parent_id, pic=pictures or None,
        )
        self.adapter.logger.debug(f"回复成功: {result.get('rpid')}")
        return result

    async def check_new_comments(self) -> None:
        target = FeedRef("video", self.adapter.config["listening_bvid"])
        comments_data = await self.adapter.get_client().get_comments_lazy(
            oid=bvid2aid(target.id),
            type_=comment.CommentResourceType.VIDEO,
        )
        comments = []
        for reply in comments_data.get("replies") or []:
            comment_info = self._comment_info(reply)
            comment_info["sub_replies"] = sorted(
                (self._comment_info(sub) for sub in reply.get("replies") or []),
                key=lambda item: item["ctime"],
            )
            comments.append(comment_info)
        comments.sort(key=lambda item: item["ctime"])
        await self._handle_new_comments(comments, target)

    @staticmethod
    def _comment_info(reply: dict[str, Any]) -> dict[str, Any]:
        return {
            "comment_id": int(reply["rpid"]),
            "user": reply["member"].get("uname"),
            "uid": reply["member"].get("mid"),
            "message": reply["content"].get("message"),
            "ctime": int(reply["ctime"]),
            "like": reply.get("like", 0),
        }

    async def _handle_new_comments(self, comments: list[dict[str, Any]], target: FeedRef) -> None:
        interval = max(0.0, float(self.adapter.config.get("message_process_interval", 5.0) or 0))
        poll_start_ts = self.last_process_ts
        newest_process_ts = poll_start_ts
        for cmt in comments:
            if cmt["ctime"] > poll_start_ts and str(cmt["uid"]) != str(self.adapter.bot_uid):
                self.publish(KiraCommentEvent(
                    target=target,
                    platform=self.adapter.info.platform,
                    adapter_name=self.adapter.info.name,
                    commenter_id=cmt["uid"],
                    commenter_nickname=cmt["user"],
                    comment_id=cmt["comment_id"],
                    self_id=self.adapter.bot_uid,
                    comment_content=MessageChain([Text(cmt["message"])]),
                    timestamp=int(time.time()),
                ))
                newest_process_ts = max(newest_process_ts, cmt["ctime"])
                await asyncio.sleep(interval)
            if str(cmt["uid"]) == str(self.adapter.bot_uid):
                for sub in cmt["sub_replies"]:
                    if sub["ctime"] > poll_start_ts and str(sub["uid"]) != str(self.adapter.bot_uid):
                        self.publish(KiraCommentEvent(
                            target=target,
                            platform=self.adapter.info.platform,
                            adapter_name=self.adapter.info.name,
                            commenter_id=sub["uid"],
                            commenter_nickname=sub["user"],
                            comment_id=sub["comment_id"],
                            comment_content=MessageChain([Text(sub["message"])]),
                            root_comment_id=cmt["comment_id"],
                            root_comment_content=MessageChain([Text(cmt["message"])]),
                            self_id=self.adapter.bot_uid,
                            timestamp=int(time.time()),
                        ))
                        newest_process_ts = max(newest_process_ts, sub["ctime"])
                        await asyncio.sleep(interval)
        self.last_process_ts = newest_process_ts
