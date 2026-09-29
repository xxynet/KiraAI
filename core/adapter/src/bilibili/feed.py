from __future__ import annotations

import asyncio
from datetime import datetime
import re
import time
from typing import TYPE_CHECKING, Any

from bilibili_api import comment, homepage, search
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

from core.adapter.base import AdapterTargetId
from core.adapter.capabilities import FeedCapability
from core.chat import KiraCommentEvent
from core.chat.message_elements import Text

if TYPE_CHECKING:
    from .bilibili import BiliBiliAdapter


class BiliBiliFeedCapability(FeedCapability["BiliBiliAdapter"]):
    def __init__(self, adapter: BiliBiliAdapter):
        super().__init__(adapter)
        self.last_process_ts = int(time.time())

    @staticmethod
    def _format_time(ts: int) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    async def get_feed(self, count: int) -> list[Any]:
        if count <= 0:
            return []
        result = await homepage.get_videos(credential=self.adapter.credential)
        return [
            {
                "id": item.get("id"),
                "bvid": item.get("bvid"),
                "title": item.get("title"),
                "duration": item.get("duration"),
                "pubdate": self._format_time(item.get("pubdate", 0)),
                "uploader": {
                    "uid": item.get("owner", {}).get("mid"),
                    "name": item.get("owner", {}).get("name"),
                },
                "stat": {
                    "view": item.get("stat", {}).get("view"),
                    "like": item.get("stat", {}).get("like"),
                    "danmaku": item.get("stat", {}).get("danmaku"),
                },
                "recommend_reason": item.get("rcmd_reason", {}).get("content") or "",
            }
            for item in (result.get("item") or [])[:count]
        ]

    async def search_feed(self, keyword: str, count: int) -> list[Any]:
        if count <= 0:
            return []
        result = await search.search_by_type(
            keyword=keyword,
            search_type=search.SearchObjectType.VIDEO,
            page_size=count,
        )
        videos = []
        for item in (result.get("result") or [])[:count]:
            cover = item.get("pic")
            videos.append({
                "bvid": item.get("bvid"),
                "title": re.sub(r"<.*?>", "", item.get("title") or ""),
                "author": item.get("author"),
                "description": item.get("description"),
                "play": item.get("play"),
                "likes": item.get("like"),
                "duration": item.get("duration"),
                "pubdate": self._format_time(item.get("pubdate", 0)),
                "cover_url": "https:" + cover if cover and cover.startswith("//") else cover,
                "tags": item.get("tag"),
                "url": f"https://www.bilibili.com/video/{item.get('bvid')}",
            })
        return videos

    async def send_comment(
        self, text: str, root: AdapterTargetId, sub: AdapterTargetId | None = None,
    ) -> Any:
        bvid = self.adapter.config.get("listening_bvid")
        if not bvid:
            raise ValueError("Bilibili comment replies require listening_bvid")
        try:
            result = await comment.send_comment(
                text=text,
                oid=bvid2aid(bvid),
                type_=comment.CommentResourceType.VIDEO,
                root=root,
                parent=sub,
                credential=self.adapter.credential,
            )
            self.adapter.logger.debug(f"回复成功: {result}")
            return result
        except Exception:
            raise RuntimeError("Bilibili comment reply failed") from None

    async def check_new_comments(self) -> None:
        comments_data = await comment.get_comments_lazy(
            oid=bvid2aid(self.adapter.config["listening_bvid"]),
            type_=comment.CommentResourceType.VIDEO,
            credential=self.adapter.credential,
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
        await self._handle_new_comments(comments)

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

    async def _handle_new_comments(self, comments: list[dict[str, Any]]) -> None:
        interval = max(0.0, float(self.adapter.config.get("message_process_interval", 5.0) or 0))
        poll_start_ts = self.last_process_ts
        newest_process_ts = poll_start_ts
        for cmt in comments:
            if cmt["ctime"] > poll_start_ts and str(cmt["uid"]) != str(self.adapter.bot_uid):
                self.publish(KiraCommentEvent(
                    platform=self.adapter.info.platform,
                    adapter_name=self.adapter.info.name,
                    commenter_id=cmt["uid"],
                    commenter_nickname=cmt["user"],
                    cmt_id=cmt["comment_id"],
                    self_id=self.adapter.bot_uid,
                    cmt_content=[Text(cmt["message"])],
                    timestamp=int(time.time()),
                ))
                newest_process_ts = max(newest_process_ts, cmt["ctime"])
                await asyncio.sleep(interval)
            if str(cmt["uid"]) == str(self.adapter.bot_uid):
                for sub in cmt["sub_replies"]:
                    if sub["ctime"] > poll_start_ts and str(sub["uid"]) != str(self.adapter.bot_uid):
                        self.publish(KiraCommentEvent(
                            platform=self.adapter.info.platform,
                            adapter_name=self.adapter.info.name,
                            commenter_id=sub["uid"],
                            commenter_nickname=sub["user"],
                            cmt_id=cmt["comment_id"],
                            cmt_content=[Text(cmt["message"])],
                            sub_cmt_id=sub["comment_id"],
                            sub_cmt_content=[Text(sub["message"])],
                            self_id=self.adapter.bot_uid,
                            timestamp=int(time.time()),
                        ))
                        newest_process_ts = max(newest_process_ts, sub["ctime"])
                        await asyncio.sleep(interval)
        self.last_process_ts = newest_process_ts
