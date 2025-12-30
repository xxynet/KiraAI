import re
import requests
import configparser
from pathlib import Path
from datetime import datetime

from bilibili_api import video, search, homepage, Credential, exceptions as bili_e

from core.utils.tool_utils import BaseTool


_cfg = configparser.RawConfigParser()
_cfg_path = Path(__file__).parent / "bili.ini"
_cfg.read(_cfg_path, encoding="utf-8")

_credential = Credential(
    sessdata=_cfg.get("bili", "sessdata"),
    bili_jct=_cfg.get("bili", "bili_jct"),
    buvid3=_cfg.get("bili", "buvid3"),
    dedeuserid=_cfg.get("bili", "dedeuserid"),
    ac_time_value=_cfg.get("bili", "ac_time_value"),
)


def format_time(ts):
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")


def _resolve_b23(url: str) -> str:
    def _follow(u: str) -> str:
        response = requests.head(u, allow_redirects=True)
        if "location" in response.headers:
            return _follow(response.headers["location"])  # recursive follow
        return response.url

    return _follow(url) if url.startswith("https://b23.tv/") else url


async def _video_handle(original_url: str):
    link = _resolve_b23(original_url)
    bvid = re.findall(r"BV[a-zA-Z0-9]{10}", link)[0]
    v = video.Video(bvid=bvid, credential=_credential)
    info = await v.get_info()

    video_bvid = info["bvid"]
    title = info["title"]
    desc = info["desc"]
    tname = info["tname"]
    tname_v2 = info.get("tname_v2")

    pubdate = datetime.fromtimestamp(info["pubdate"]).strftime("%Y-%m-%d %H:%M:%S")
    up_info = info["owner"]
    stat = info["stat"]

    video_info_str = (
        f"以下是视频相关信息：bvid: {video_bvid}, title: {title}, description: {desc}, "
        f"分区：{tname} - {tname_v2}, 发布时间：{pubdate}, 作者信息：{up_info}, 互动数据：{stat}"
    )
    return video_info_str, v, info["aid"]


class BiliVideoInfoTool(BaseTool):
    name = "bilibili"
    description = "通过B站视频链接获取视频基本信息（www.bilibili.com/video/ 或 b23.tv/）"
    parameters = {
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    }

    async def execute(self, original_url: str) -> str:
        try:
            info_str, _, _ = await _video_handle(original_url)
            return info_str
        except Exception as bili_info_e:
            return str(bili_info_e)


class BiliLikeTool(BaseTool):
    name = "like_bilibili_video"
    description = "给B站视频点赞并返回视频信息"
    parameters = {
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    }

    async def execute(self, original_url: str) -> str:
        try:
            info_str, v, _ = await _video_handle(original_url)
            await v.like()
        except bili_e.ResponseCodeException as e:
            return f"点赞失败！{str(e)}"
        return f"点赞成功！{info_str}"


# class BiliCommentTool(BaseTool):
#     name = "comment_bilibili_video"
#     description = "生成评论内容并在B站视频下发表评论"
#     parameters = {
#         "type": "object",
#         "properties": {
#             "original_url": {"type": "string", "description": "B站视频url"}
#         },
#         "required": ["original_url"]
#     }
#
#     async def execute(self, original_url: str) -> str:
#         try:
#             info_str, _, aid = await _video_handle(original_url)
#         except Exception as bili_info_e:
#             return str(bili_info_e)
#
#         with open("data/persona.txt", "r", encoding="utf-8") as f:
#             persona_prompt = f.read()
#         with open("prompts/reply_bilibili.txt", "r", encoding="utf-8") as f:
#             reply_template = f.read()
#         prompt = reply_template.format(persona=persona_prompt, bili_video_info=info_str)
#
#         messages = [{"role": "user", "content": prompt}]
#         llm_resp = await llm_api.chat(messages)
#
#         resp = llm_resp.text_response
#
#         result = await comment.send_comment(
#             text=resp,
#             oid=aid,
#             type_=CommentResourceType.VIDEO,
#             credential=_credential
#         )
#         reply_status = result.get("success_toast")
#         reply_content = result.get("reply").get("content").get("message")
#         return f"status: {reply_status}, reply_content: {reply_content}"


class BiliSearchTool(BaseTool):
    name = "bilibili_search"
    description = "通过关键词搜索B站视频"
    parameters = {
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词"}
        },
        "required": ["keyword"]
    }

    async def _search_videos_with_count(self, keyword, count):
        result = await search.search_by_type(
            keyword=keyword,
            search_type=search.SearchObjectType.VIDEO,  # 指定搜索视频类型
            page_size=count  # 指定返回几个视频
        )
        result = result["result"]

        videos = []
        for item in result:
            videos.append({
                "bvid": item.get("bvid"),
                "title": re.sub(r'<.*?>', '', item.get("title") or ''),
                "author": item.get("author"),
                "description": item.get("description"),
                "views": item.get("play"),
                "likes": item.get("like"),
                "duration": item.get("duration"),
                "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)).strftime("%Y-%m-%d %H:%M:%S"),
                # "cover_url": "https:" + item.get("pic") if item.get("pic") else None,
                "tags": item.get("tag"),
                "url": f"https://www.bilibili.com/video/{item.get('bvid')}",
            })
        return str(videos)

    async def execute(self, keyword: str) -> str:
        try:
            res = await self._search_videos_with_count(keyword, 5)
            return res
        except Exception as bili_search_e:
            return str(bili_search_e)


class BiliFeedTool(BaseTool):
    name = "bilibili_feed"
    description = "获取B站首页视频"
    parameters = {
        "type": "object",
        "properties": {

        },
        "required": []
    }

    @staticmethod
    def clean_feed_items(feed_json, vid_count):
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
                "pubdate": format_time(v.get("pubdate", 0)),
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

    async def get_personalized_feed(self, count: int = 5):
        # 使用登录凭据获取个性化推荐
        result = await homepage.get_videos(credential=_credential)
        cleaned_feed = self.clean_feed_items(result, count)
        return cleaned_feed

    async def execute(self) -> str:
        try:
            feed = await self.get_personalized_feed(count=5)
            return str(feed)
        except Exception as bili_feed_e:
            return str(bili_feed_e)
