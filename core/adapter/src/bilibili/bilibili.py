import asyncio
from datetime import datetime
import re
import time
from typing import Union, Optional, Dict, Any

from bilibili_api import comment, Credential, homepage, search
from bilibili_api.utils.aid_bvid_transformer import bvid2aid

from core.adapter.adapter_utils import SocialMediaAdapter
from core.chat import KiraCommentEvent, MessageType


class BiliBiliAdapter(SocialMediaAdapter):
    def __init__(self, info, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        super().__init__(info, loop, event_bus)
        self.emoji_dict: Optional[dict] = None
        self.last_process_ts: int = int(time.time())
        self.listening_task = None
        self.bot_uid = self.config.get("bot_uid")
        self._credential = Credential(
            sessdata=self.config.get("sessdata", ""),
            bili_jct=self.config.get("bili_jct", ""),
            buvid3=self.config.get("buvid3", ""),
            dedeuserid=self.config.get("dedeuserid", ""),
            ac_time_value=self.config.get("ac_time_value", ""),
        )

    async def start(self):
        if self.config.get("listening_bvid"):
            self.listening_task = asyncio.create_task(self._start_listening(self.config.get("listening_interval")))
            await self.listening_task
        else:
            return

    @staticmethod
    def _format_time(ts):
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")

    def _clean_feed_items(self, feed_json, vid_count):
        items = feed_json.get("item", [])
        results = []

        count = 0

        for v in items:
            results.append({
                "id": v.get("id"),
                "bvid": v.get("bvid"),
                "title": v.get("title"),
                # "cover": v.get("pic"),
                # "url": v.get("uri"),
                "duration": v.get("duration"),
                "pubdate": self._format_time(v.get("pubdate", 0)),
                "uploader": {
                    "uid": v.get("owner", {}).get("mid"),
                    "name": v.get("owner", {}).get("name"),
                    # "face": v.get("owner", {}).get("face"),
                },
                "stat": {
                    "view": v.get("stat", {}).get("view"),
                    "like": v.get("stat", {}).get("like"),
                    "danmaku": v.get("stat", {}).get("danmaku"),
                },
                "recommend_reason": v.get("rcmd_reason", {}).get("content") or "",
            })

            count += 1
            if count == vid_count:
                break

        return results

    async def get_feed(self, count: int):
        result = await homepage.get_videos(credential=self._credential)
        cleaned_feed = self._clean_feed_items(result, count)
        return cleaned_feed

    async def search(self, keyword: str, count: int = 1):
        result = await search.search_by_type(
            keyword=keyword,
            search_type=search.SearchObjectType.VIDEO,  # 指定搜索视频类型
            page_size=2  # 指定返回20个视频
        )
        result = result["result"]

        videos = []
        for item in result:
            videos.append({
                "bvid": item.get("bvid"),
                "title": re.sub(r'<.*?>', '', item.get("title") or ''),
                "author": item.get("author"),
                "description": item.get("description"),
                "play": item.get("play"),
                "likes": item.get("like"),
                "duration": item.get("duration"),
                "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)).strftime("%Y-%m-%d %H:%M:%S"),
                "cover_url": "https:" + item.get("pic") if item.get("pic") else None,
                "tags": item.get("tag"),
                "url": f"https://www.bilibili.com/video/{item.get('bvid')}",
            })
        return videos

    async def send_comment(self, text: str, root: Union[int, str], sub: Union[int, str] = None):
        try:
            result = await comment.send_comment(
                text=text,
                oid=bvid2aid(self.config.get("listening_bvid")),
                type_=comment.CommentResourceType.VIDEO,
                root=root,  # 回复这条评论
                parent=sub,
                credential=self._credential
            )
            print(f"回复成功: {result}")
        except Exception as e:
            print(f"回复失败: {e}")

    async def _start_listening(self, interval: float = 20.0):
        """开始监听，默认20秒检查一次"""
        while True:
            try:
                # print(f"last_process_ts: {self.last_process_ts}")
                await self._check_new_comments()
                await asyncio.sleep(interval)
            except Exception as e:
                print(f"监听出错: {e}")
                await asyncio.sleep(interval)

    async def _check_new_comments(self):
        """检查新评论并回复"""
        comments_data = await comment.get_comments_lazy(
            oid=bvid2aid(self.config.get("listening_bvid")),
            type_=comment.CommentResourceType.VIDEO,
            credential=self._credential
        )

        replies = comments_data.get('replies', [])

        # print(replies)

        comments = []

        for reply in replies:
            comment_info = {
                "comment_id": reply.get('rpid'),
                "user": reply["member"].get("uname"),
                "uid": reply.get("member").get("mid"),
                "message": reply.get("content").get("message"),
                "ctime": reply.get("ctime"),
                "like": reply.get("like", 0),
            }

            # 处理子评论（如果有）
            sub_comments = []
            if reply.get("replies"):
                for sub in reply["replies"]:
                    sub_comments.append({
                        "comment_id": sub.get("rpid"),
                        "user": sub["member"].get("uname"),
                        "uid": sub.get("member").get("mid"),
                        "message": sub["content"].get("message"),
                        "ctime": sub.get("ctime"),
                        "like": sub.get("like", 0),
                    })
                sub_comments.sort(key=lambda x: int(x.get("ctime")))
            comment_info["sub_replies"] = sub_comments

            comments.append(comment_info)
        comments.sort(key=lambda x: int(x.get("ctime")))

        # print(comments)

        # process comments
        await self._handle_new_comment(comments)

    async def _handle_new_comment(self, comments: list):
        """处理评论"""
        for cmt in comments:
            cmt_id = int(cmt.get("comment_id"))
            cmt_content = cmt.get("message")
            commenter = cmt.get("user")
            commenter_id = cmt.get("uid")
            cmt_ts = int(cmt.get("ctime"))
            if cmt_ts > self.last_process_ts and cmt.get("uid") != self.bot_uid:
                cmt_obj = KiraCommentEvent(
                    platform=self.info.platform,
                    adapter_name=self.info.name,
                    commenter_id=commenter_id,
                    commenter_nickname=commenter,
                    cmt_id=cmt_id,
                    self_id=self.bot_uid,
                    cmt_content=[MessageType.Text(cmt_content)],
                    timestamp=int(time.time())
                )
                await self.event_bus.put(cmt_obj)
                self.last_process_ts = int(cmt.get("ctime"))
                await asyncio.sleep(self.config.get("message_process_interval"))
            if cmt.get("uid") == self.bot_uid:
                for sub_cmt in cmt.get("sub_replies"):
                    sub_cmt_id = int(sub_cmt.get("comment_id"))
                    sub_cmt_content = sub_cmt.get("message")
                    sub_cmt_ts = int(sub_cmt.get("ctime"))
                    sub_commenter = sub_cmt.get("user")
                    sub_commenter_uid = sub_cmt.get("uid")
                    if sub_cmt_ts > self.last_process_ts and sub_commenter_uid != self.bot_uid:
                        cmt_obj = KiraCommentEvent(
                            platform=self.info.platform,
                            adapter_name=self.info.name,
                            commenter_id=sub_commenter_uid,
                            commenter_nickname=sub_commenter,
                            cmt_id=cmt_id,
                            cmt_content=[MessageType.Text(cmt_content)],
                            sub_cmt_id=sub_cmt_id,
                            sub_cmt_content=[MessageType.Text(sub_cmt_content)],
                            self_id=self.bot_uid,
                            timestamp=int(time.time())
                        )
                        await self.event_bus.put(cmt_obj)
                        self.last_process_ts = sub_cmt_ts
                        await asyncio.sleep(self.config.get("message_process_interval"))
