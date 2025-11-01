from pathlib import Path
from datetime import datetime
import requests
import os
import json
import re
import sys
import configparser

from tavily import TavilyClient
from bilibili_api import video, Credential, sync, comment, exceptions as bili_e
from bilibili_api.comment import CommentResourceType

from core.llm_client import LLMClient


llm_api = LLMClient()

# llm_api.register_tool(
#     name="add_numbers",
#     description="将两个数字相加",
#     parameters={
#         "type": "object",
#         "properties": {
#             "a": {"type": "number"},
#             "b": {"type": "number"}
#         },
#         "required": ["a", "b"]
#     },
#     func=lambda a, b: {"result": a + b}
# )
#
#
# def exec_code(code: str):
#     try:
#         old_stdout = sys.stdout
#         redirected_output = sys.stdout = StringIO()
#
#         exec(code)
#
#         sys.stdout = old_stdout
#
#         output = redirected_output.getvalue()
#         return f"执行成功，输出：{output}"
#     except Exception as e:
#         return f"执行失败 {str(e)}"
#
#
# llm_api.register_tool(
#     name="python",
#     description="执行Python代码，可以通过此工具操作电脑",
#     parameters={
#         "type": "object",
#         "properties": {
#             "code": {"type": "string", "description": "要执行的代码"}
#         },
#         "required": ["code"]
#     },
#     func=exec_code
# )


# ====== memory tools ======
def memory_add(text: str):
    core_memory_path = "data/memory/core.txt"
    os.makedirs(os.path.dirname(core_memory_path), exist_ok=True)
    with open(core_memory_path, "r", encoding='utf-8') as mem:
        mem_str = mem.read()
    with open(core_memory_path, "a", encoding='utf-8') as mem:
        if not mem_str.endswith('\n'):
            mem.write('\n')
        mem.write(text + '\n')
    return "Core memory added"


llm_api.register_tool(
    name="memory_add",
    description="添加一条记忆",
    parameters={
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "要记录的记忆文本"}
        },
        "required": ["text"]
    },
    func=memory_add
)


def memory_update(index: int, text: str):
    core_memory_path = "data/memory/core.txt"
    os.makedirs(os.path.dirname(core_memory_path), exist_ok=True)
    with open(core_memory_path, "r", encoding='utf-8') as mem:
        lines = mem.readlines()
    lines[index] = text + '\n' if not text.endswith('\n') else text
    with open(core_memory_path, "w", encoding='utf-8') as mem:
        mem.writelines(lines)
    print(f"更新后: {lines}")
    return "Core memory updated"


llm_api.register_tool(
    name="memory_update",
    description="修改特定记忆",
    parameters={
        "type": "object",
        "properties": {
            "index": {"type": "number", "description": "要修改的记忆编号"},
            "text": {"type": "string", "description": "要更新成的记忆文本"}
        },
        "required": ["index", "text"]
    },
    func=memory_update
)


def memory_remove(index: int):
    core_memory_path = "data/memory/core.txt"
    os.makedirs(os.path.dirname(core_memory_path), exist_ok=True)
    with open(core_memory_path, "r", encoding='utf-8') as mem:
        lines = mem.readlines()
    removed_memory = lines.pop(index)
    with open(core_memory_path, "w", encoding='utf-8') as mem:
        mem.writelines(lines)
    print(f"更新后: {lines}")
    return f"Core memory removed: {removed_memory}"


llm_api.register_tool(
    name="memory_remove",
    description="删除一条记忆",
    parameters={
        "type": "object",
        "properties": {
            "index": {"type": "number", "description": "要删除的记忆编号"}
        },
        "required": ["index"]
    },
    func=memory_remove
)

# ====== bili tools ======

bili_config = configparser.RawConfigParser()
config_path = Path("core/tools/bili.ini")
bili_config.read(config_path, encoding='utf-8')

sessdata = bili_config.get("bili", "sessdata")
bili_jct = bili_config.get("bili", "bili_jct")
buvid3 = bili_config.get("bili", "buvid3")
dedeuserid = bili_config.get("bili", "dedeuserid")
ac_time_value = bili_config.get("bili", "ac_time_value")

bili_credential = Credential(
        sessdata=sessdata,
        bili_jct=bili_jct, buvid3=buvid3,
        dedeuserid=dedeuserid, ac_time_value=ac_time_value)


def b2_vid_info(url):
    bili_video_link = url

    def get_permanent_link(url):
        response = requests.head(url, allow_redirects=True)

        if 'location' in response.headers:
            # 手机端链接
            # 如果响应头中包含'location'，则表示发生了重定向
            # 递归调用自身以处理连续重定向的情况
            return get_permanent_link(response.headers['location'])
        else:
            # 如果没有重定向，则返回当前请求的URL作为永久链接
            return response.url

    if url.startswith("https://b23.tv/"):
        bili_video_link = get_permanent_link(url)

    bvid = re.findall(r'BV[a-zA-Z0-9]{10}', bili_video_link)[0]

    credential = bili_credential
    # 实例化 Video 类
    v = video.Video(bvid=bvid, credential=credential)
    # 获取视频信息
    video_info = sync(v.get_info())

    # 基本信息
    video_bvid = video_info['bvid']
    video_aid = video_info['aid']
    title = video_info['title']
    desc = video_info['desc']
    tname = video_info['tname']
    tname_v2 = video_info['tname_v2']

    # 时间
    from datetime import datetime
    pubdate = datetime.fromtimestamp(video_info['pubdate'])
    pubdate_str = pubdate.strftime("%Y-%m-%d %H:%M:%S")

    # 作者
    up_info = video_info['owner']

    # 热度数据
    stat = video_info['stat']

    video_info_str = f"以下是视频相关信息：bvid: {video_bvid}, title: {title}, description: {desc}, 分区：{tname} - {tname_v2}, 发布时间：{pubdate_str}, 作者信息：{up_info}, 互动数据：{stat}"
    return video_info_str, v, video_aid


def get_b2_video_info(original_url: str):
    video_info_str, _, _ = b2_vid_info(original_url)
    return video_info_str


llm_api.register_tool(
    name="bilibili",
    description="通过B站（哔哩哔哩）视频链接获取视频基本信息，B站视频链接为www.bilibili.com/video/xxxx 或者 b23.tv/xxx",
    parameters={
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    },
    func=get_b2_video_info
)


def like_b2_video(original_url):
    video_info_str, v, _ = b2_vid_info(original_url)
    try:
        sync(v.like())
    except bili_e.ResponseCodeException as e:
        return f"点赞失败！{str(e)}"

    return f"点赞成功！{video_info_str}"


llm_api.register_tool(
    name="like_bilibili_video",
    description="通过B站（哔哩哔哩）视频链接点赞视频并获取视频基本信息，B站视频链接为www.bilibili.com/video/xxxx 或者 b23.tv/xxx",
    parameters={
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    },
    func=like_b2_video
)


def comment_b2_video(original_url):
    video_info_str, _, aid = b2_vid_info(original_url)

    with open("prompts/persona.txt", 'r', encoding="utf-8") as f:
        persona_prompt = f.read()

    with open("prompts/reply_bilibili.txt", 'r', encoding="utf-8") as f:
        reply_bili_prompt = f.read()
        reply_bili_prompt = reply_bili_prompt.format(persona=persona_prompt, bili_video_info=video_info_str)

    messages = [{"role": "user", "content": reply_bili_prompt}]
    resp, _ = llm_api.chat(messages)

    # 发表评论
    result = sync(comment.send_comment(
        text=resp,
        oid=aid,
        type_=CommentResourceType.VIDEO,
        credential=bili_credential
    ))
    reply_status = result.get("success_toast")
    reply_content = result.get("reply").get("content").get("message")
    return_str = f"status: {reply_status}, reply_content: {reply_content}"
    return return_str


llm_api.register_tool(
    name="comment_bilibili_video",
    description="通过B站（哔哩哔哩）视频链接获取视频基本信息并评论视频，B站视频链接为www.bilibili.com/video/xxxx 或者 b23.tv/xxx",
    parameters={
        "type": "object",
        "properties": {
            "original_url": {"type": "string", "description": "B站视频url"}
        },
        "required": ["original_url"]
    },
    func=comment_b2_video
)


tavily_config = configparser.RawConfigParser()
tavily_config_path = Path("core/tools/tavily.ini")
tavily_config.read(tavily_config_path, encoding='utf-8')

tavily_key = tavily_config.get("tavily", "key")


def search(keyword: str):
    search_client = TavilyClient(tavily_key)
    res = search_client.search(
        query=keyword
    )

    query_res = res.get("results")
    if len(query_res) > 2:
        query_res = query_res[:2]

    res_str = ""
    for ele in query_res:
        res_str += json.dumps(ele, ensure_ascii=False)
    return res_str


llm_api.register_tool(
    name="search",
    description="通过关键词在互联网上查找信息",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "关键词"}
        },
        "required": ["keyword"]
    },
    func=search
)


ntfy_config = configparser.RawConfigParser()
ntfy_config_path = Path("core/tools/ntfy.ini")
ntfy_config.read(ntfy_config_path, encoding='utf-8')

ntfy_url = ntfy_config.get("ntfy", "url")


def ntfy_tool(msg, title=None):
    resp = requests.post(ntfy_url, data=msg.encode(encoding='utf-8'),
                      headers={
                          "Title": title,
                          # "Tags": "milk_glass"
                      }
                  )
    return resp.text


llm_api.register_tool(
    name="ntfy",
    description="推送通知的工具，标题中不得出现中文",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "通知标题"},
            "msg": {"type": "string", "description": "通知内容"},
        },
        "required": ["msg"]
    },
    func=ntfy_tool
)

if __name__ == '__main__':
    pass
