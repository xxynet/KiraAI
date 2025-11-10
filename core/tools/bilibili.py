import re
import requests
import configparser
from pathlib import Path
from datetime import datetime

from bilibili_api import video, Credential, sync, comment, exceptions as bili_e
from bilibili_api.comment import CommentResourceType

from utils.tool_utils import BaseTool
from core.llm_client import LLMClient  # Only to use same chat interface for generating replies


_cfg = configparser.RawConfigParser()
_cfg_path = Path("core/tools/bili.ini")
_cfg.read(_cfg_path, encoding="utf-8")

_credential = Credential(
    sessdata=_cfg.get("bili", "sessdata"),
    bili_jct=_cfg.get("bili", "bili_jct"),
    buvid3=_cfg.get("bili", "buvid3"),
    dedeuserid=_cfg.get("bili", "dedeuserid"),
    ac_time_value=_cfg.get("bili", "ac_time_value"),
)


def _resolve_b23(url: str) -> str:
    def _follow(u: str) -> str:
        response = requests.head(u, allow_redirects=True)
        if "location" in response.headers:
            return _follow(response.headers["location"])  # recursive follow
        return response.url

    return _follow(url) if url.startswith("https://b23.tv/") else url


def _video_handle(original_url: str):
    link = _resolve_b23(original_url)
    bvid = re.findall(r"BV[a-zA-Z0-9]{10}", link)[0]
    v = video.Video(bvid=bvid, credential=_credential)
    info = sync(v.get_info())

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

    def execute(self, original_url: str) -> str:
        try:
            info_str, _, _ = _video_handle(original_url)
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

    def execute(self, original_url: str) -> str:
        try:
            info_str, v, _ = _video_handle(original_url)
            sync(v.like())
        except bili_e.ResponseCodeException as e:
            return f"点赞失败！{str(e)}"
        return f"点赞成功！{info_str}"


class BiliCommentTool(BaseTool):
    name = "comment_bilibili_video"
    description = "生成评论内容并在B站视频下发表评论"
    parameters = {
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    }

    def __init__(self):
        super().__init__()
        self._llm = LLMClient()

    def execute(self, original_url: str) -> str:
        try:
            info_str, _, aid = _video_handle(original_url)
        except Exception as bili_info_e:
            return str(bili_info_e)

        with open("prompts/persona.txt", "r", encoding="utf-8") as f:
            persona_prompt = f.read()
        with open("prompts/reply_bilibili.txt", "r", encoding="utf-8") as f:
            reply_template = f.read()
        prompt = reply_template.format(persona=persona_prompt, bili_video_info=info_str)

        messages = [{"role": "user", "content": prompt}]
        resp, _ = self._llm.chat(messages)

        result = sync(comment.send_comment(
            text=resp,
            oid=aid,
            type_=CommentResourceType.VIDEO,
            credential=_credential
        ))
        reply_status = result.get("success_toast")
        reply_content = result.get("reply").get("content").get("message")
        return f"status: {reply_status}, reply_content: {reply_content}"
