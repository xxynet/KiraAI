import asyncio
import contextlib
from collections import OrderedDict
from datetime import datetime
import re
import time
from typing import Union, Optional, Dict, Any

from bilibili_api import comment, Credential, homepage, search, user
from bilibili_api.utils.aid_bvid_transformer import bvid2aid
from bilibili_api.utils import network

from core.adapter.adapter_utils import SocialMediaAdapter
from core.logging_manager import get_logger
from core.chat import KiraCommentEvent
from core.logging_manager import get_logger

from core.chat.message_elements import (
    Text,
    Image,
    At,
    Reply,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke
)


DEFAULT_LISTENING_INTERVAL = 20.0
DEFAULT_MESSAGE_PROCESS_INTERVAL = 5.0
PROCESSED_COMMENT_ID_LIMIT = 500


class BiliBiliAdapter(SocialMediaAdapter):
    def __init__(self, info, event_bus: asyncio.Queue):
        super().__init__(info, event_bus)
        self.emoji_dict: Optional[dict] = None
        self.last_process_ts: int = int(time.time())
        self.listening_task = None
        self.logger = get_logger(info.name, "purple")
        self._processed_cmt_ids: "OrderedDict[int, None]" = OrderedDict()
        self.bot_uid = self.config.get("bot_uid")
        self.logger = get_logger(info.name, "blue")
        self._credential = Credential(
            sessdata=self.config.get("sessdata", ""),
            bili_jct=self.config.get("bili_jct", ""),
            buvid3=self.config.get("buvid3", ""),
            dedeuserid=self.config.get("dedeuserid", ""),
            ac_time_value=self.config.get("ac_time_value", ""),
        )

    def _float_config(self, key: str, default: float) -> float:
        """Read a float config value, falling back when it is missing or malformed"""
        try:
            return float(self.config.get(key))
        except (TypeError, ValueError):
            return default

    async def start(self):
        network.select_client("aiohttp")
        session = network.get_session()
        session.headers["Accept-Encoding"] = "gzip, deflate"
        await self._log_login_status()
        if self.config.get("listening_bvid"):
            interval = self._float_config("listening_interval", DEFAULT_LISTENING_INTERVAL)
            self.listening_task = asyncio.create_task(self._start_listening(interval))
            try:
                await self.listening_task
            except asyncio.CancelledError:
                pass
        else:
            return

    async def _log_login_status(self):
        if not self.config.get("sessdata"):
            self.logger.info("Bilibili login status: not logged in")
            return

        try:
            account = await user.get_self_info(self._credential)
        except Exception as exc:
            self.logger.warning(
                f"Bilibili login status verification failed: {type(exc).__name__}: {str(exc)[:100]}"
            )
            return

        self.logger.info(
            f"Bilibili login status: logged in, nickname={account.get('name', 'unknown')}, "
            f"uid={account.get('mid', 'unknown')}"
        )

    async def stop(self):
        """Stop the comment-listening task if it is running."""
        if self.listening_task and not self.listening_task.done():
            self.listening_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.listening_task
        self.listening_task = None

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
            self.logger.debug(f"回复成功: {result}")
            return result
        except Exception as e:
            self.logger.error(f"回复失败: {e}")
            raise

    async def _start_listening(self, interval: float = DEFAULT_LISTENING_INTERVAL):
        """开始监听，默认20秒检查一次"""
        while True:
            try:
                await self._check_new_comments()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger.error(f"Bilibili 监听出错: {e}")
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

    def _is_already_processed(self, cmt_id: int) -> bool:
        """Return True when the comment was already published, otherwise remember it."""
        if cmt_id in self._processed_cmt_ids:
            return True
        self._processed_cmt_ids[cmt_id] = None
        while len(self._processed_cmt_ids) > PROCESSED_COMMENT_ID_LIMIT:
            self._processed_cmt_ids.popitem(last=False)
        return False

    def _collect_pending_comments(self, comments: list) -> list:
        """Collect comments newer than the cursor as (ctime, comment, sub_comment) tuples.

        Top-level comments and sub replies are gathered together and sorted by their own
        timestamp, because a sub reply under an older thread may be newer than a later
        top-level comment.
        """
        pending = []
        for cmt in comments:
            cmt_ts = int(cmt.get("ctime"))
            is_own_comment = str(cmt.get("uid")) == str(self.bot_uid)
            if not is_own_comment and cmt_ts >= self.last_process_ts:
                pending.append((cmt_ts, cmt, None))
            if is_own_comment:
                for sub_cmt in cmt.get("sub_replies") or []:
                    sub_cmt_ts = int(sub_cmt.get("ctime"))
                    if str(sub_cmt.get("uid")) != str(self.bot_uid) and sub_cmt_ts >= self.last_process_ts:
                        pending.append((sub_cmt_ts, cmt, sub_cmt))
        pending.sort(key=lambda item: item[0])
        return pending

    async def _handle_new_comment(self, comments: list):
        """处理评论"""
        pending = self._collect_pending_comments(comments)
        if not pending:
            return

        interval = self._float_config("message_process_interval", DEFAULT_MESSAGE_PROCESS_INTERVAL)

        for cmt_ts, cmt, sub_cmt in pending:
            self.last_process_ts = max(self.last_process_ts, cmt_ts)
            cmt_id = int(cmt.get("comment_id"))
            cmt_content = cmt.get("message")

            if sub_cmt is None:
                if self._is_already_processed(cmt_id):
                    continue
                cmt_obj = KiraCommentEvent(
                    platform=self.info.platform,
                    adapter_name=self.info.name,
                    commenter_id=cmt.get("uid"),
                    commenter_nickname=cmt.get("user"),
                    cmt_id=cmt_id,
                    self_id=self.bot_uid,
                    cmt_content=[Text(cmt_content)],
                    timestamp=int(time.time())
                )
            else:
                sub_cmt_id = int(sub_cmt.get("comment_id"))
                if self._is_already_processed(sub_cmt_id):
                    continue
                cmt_obj = KiraCommentEvent(
                    platform=self.info.platform,
                    adapter_name=self.info.name,
                    commenter_id=sub_cmt.get("uid"),
                    commenter_nickname=sub_cmt.get("user"),
                    cmt_id=cmt_id,
                    cmt_content=[Text(cmt_content)],
                    sub_cmt_id=sub_cmt_id,
                    sub_cmt_content=[Text(sub_cmt.get("message"))],
                    self_id=self.bot_uid,
                    timestamp=int(time.time())
                )

            await self.event_bus.put(cmt_obj)
            await asyncio.sleep(interval)
