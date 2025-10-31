import os
os.environ["LOG_FILE_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

from ncatbot.core import BotClient, GroupMessage, PrivateMessage
from ncatbot.core import (
    MessageChain,  # 消息链，用于组合多个消息元素
    Text,          # 文本消息
    Reply,         # 回复消息
    At,            # @某人
    AtAll,         # @全体成员
    Face,          # QQ表情
    Image,         # 图片
    Record,        # 语音
)
from ncatbot.utils import get_log  # 已禁用适配器日志

import json
import time
import threading
import logging
from datetime import datetime
import asyncio
from typing import Any, Dict

from core.llm_manager import llm_api
from utils.adapter_utils import IMAdapter
from utils.message_utils import BotPrivateMessage, BotGroupMessage, MessageSending, MessageType

logging.getLogger("PluginLoader").setLevel(logging.CRITICAL)
logging.getLogger("adapter.nc.launcher").setLevel(logging.CRITICAL)
logging.getLogger("AccessController").setLevel(logging.CRITICAL)


def process_incoming_message(bot, msg):
    """把QQ平台消息转换为项目通用消息格式"""
    message_content = []
    for ele in msg.message:
        if ele.get("type") == "text":
            message_content.append(MessageType.Text(ele.get("data").get("text")))
        elif ele.get("type") == "at":
            at_obj = MessageType.At(str(ele.get("data").get("qq")))
            if str(ele.get("data").get("qq")) != "all":
                at_user_info = bot.api.get_stranger_info_sync(user_id=str(ele.get("data").get("qq")))
                at_nickname = at_user_info["data"]["nickname"]
                at_obj.nickname = at_nickname
            message_content.append(at_obj)
        elif ele.get("type") == "reply":
            reply_content = bot.api.get_msg_sync(ele.get("data").get("id"))
            processed_reply = process_reply_message(reply_content)
            message_content.append(MessageType.Reply(ele.get("data").get("id"), processed_reply))
        elif ele.get("type") == "face":
            message_content.append(MessageType.Emoji(str(ele.get("data").get("id"))))
        elif ele.get("type") == "image":
            img_url = ele.get("data", "").get("url", "")
            message_content.append(MessageType.Image(img_url))
        elif ele.get("type") == "video":
            message_content.append(MessageType.Text("[Video]"))
        elif ele.get("type") == "file":
            message_content.append(MessageType.Text("[File]"))
        elif ele.get("type") == "forward":
            forward_message = bot.api.get_forward_msg_sync(msg.message_id)
            processed_forward = process_forward_message(forward_message)
            message_content.append(MessageType.Text(processed_forward))
        elif ele.get("type") == "record":
            file_id = ele.get("data").get("file")

            record_info = bot.api.get_record_sync(file_id, output_type="mp3")
            audio_base64 = record_info.get("data").get("base64")
            message_content.append(MessageType.Record(audio_base64))
    return message_content


def process_reply_message(message_data):
    msg = message_data.get("data", {})
    sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
    ts = msg.get("time", 0)
    dt = datetime.fromtimestamp(ts)
    time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

    # 组合消息内容
    parts = []
    for seg in msg.get("message", []):
        t = seg.get("type")
        d = seg.get("data", {})
        if t == "text":
            parts.append(d.get("text", ""))
        elif t == "at":
            parts.append(f"[At {d.get('qq')}]")
        elif t == "image":
            img_desc = llm_api.desc_img(d.get('url', ''))
            parts.append(f"[Image {img_desc}]")
        elif t == "face":
            parts.append(f"[Emoji {d.get('id')}]")
        elif t == "reply":
            parts.append(f"[Reply {d.get('id')}]")
        else:
            parts.append(f"[{t}]")

    content = " ".join(parts).strip()
    return f"{sender}  [{time_str}]\n{content}"


def process_forward_message(message_data):
    result = []
    messages = message_data.get("data", {}).get("messages", [])

    for msg in messages:
        sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
        ts = msg.get("time", 0)
        dt = datetime.fromtimestamp(ts)  # 转换成可读时间
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        # 组合消息内容
        parts = []
        for seg in msg.get("message", []):
            t = seg.get("type")
            d = seg.get("data", {})
            if t == "text":
                parts.append(d.get("text", ""))
            elif t == "at":
                parts.append(f"[At {d.get('qq')}]")
            elif t == "image":
                img_desc = llm_api.desc_img(d.get('url', ''))
                parts.append(f"[Image {img_desc}]")
            elif t == "face":
                parts.append(f"[Emoji {d.get('id')}]")
            elif t == "reply":
                parts.append(f"[Reply {d.get('id')}]")
            else:
                parts.append(f"[{t}]")

        content = " ".join(parts).strip()
        result.append(f"{sender}  [{time_str}]\n{content}\n")

    return "\n".join(result)


def process_outgoing_message(message: MessageSending):
    """将通用消息格式转换为QQ消息格式"""
    message_chain_elements = []
    for ele in message.message_list:
        if isinstance(ele, MessageType.Text):
            message_chain_elements.append(Text(ele.text))
        elif isinstance(ele, MessageType.Emoji):
            message_chain_elements.append(Face(int(ele.emoji_id)))
        elif isinstance(ele, MessageType.Sticker):
            message_chain_elements.append(Image(f"base64://{ele.sticker_bs64}"))
        elif isinstance(ele, MessageType.At):
            val = ele.pid
            if val == "all":
                message_chain_elements.append(AtAll())
            else:
                try:
                    val_num = int(val)
                    message_chain_elements.append(At(val_num))
                except Exception as e:
                    pass
            message_chain_elements.append(Text(" "))
        elif isinstance(ele, MessageType.Image):
            message_chain_elements.append(Image(ele.url))
        elif isinstance(ele, MessageType.Reply):
            message_chain_elements.append(Reply(ele.message_id))
        elif isinstance(ele, MessageType.Record):
            message_chain_elements.append(Record(f"base64://{ele.bs64}"))
        elif isinstance(ele, MessageType.Notice):
            # 可以实现定时主动消息等
            pass
        elif isinstance(ele, MessageType.Poke):
            message_chain_elements.append(ele)
        else:
            pass
    return message_chain_elements


class QQAdapter(IMAdapter):
    def __init__(self, config: Dict[str, Any], loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        super().__init__(config, loop, event_bus)
        self.name: str = "QQ"
        self.group_list: list = []
        self.user_list: list = []
        self.emoji_dict = self._load_dict("adapters/qq/emoji.json")
        self.message_types = [MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Emoji, MessageType.Sticker, MessageType.Record, MessageType.Poke, MessageType.Notice]
        self._init_config()
        self.bot: BotClient = BotClient()
        # self._log = get_log()  # 已禁用适配器日志

    def _init_config(self):
        group_list_str = self.config["group_list"]
        user_list_str = self.config["user_list"]
        try:
            self.group_list = [int(item.strip()) for item in group_list_str.split(",")]
            self.user_list = [int(item.strip()) for item in user_list_str.split(",")]
        except Exception as e:
            print(f"error occurred while loading allow list config: {str(e)}")

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """加载字典"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception as e:
            return {}

    def start_blocking(self):
        @self.bot.group_event()
        async def on_group_message(msg: GroupMessage):
            await self._on_group_message(msg)

        @self.bot.private_event()
        async def on_private_message(msg: PrivateMessage):
            await self._on_private_message(msg)

        @self.bot.notice_event()
        async def on_notice_message(msg: Dict):
            await self._on_notice_message(msg)

        self.bot.run(bt_uin=self.config["bot_pid"], root=self.config["owner_pid"], ws_uri=self.config["ws_uri"], ws_listen_ip=self.config["ws_listen_ip"], ws_token=self.config["ws_token"], enable_webui_interaction=False)

    async def start(self):
        threading.Thread(target=self.start_blocking, daemon=True).start()

    async def send_group_message(self, group_id, send_message_obj):
        try:
            message_chain = process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, MessageType.Poke):
                await self.bot.api.send_poke(user_id=ele.pid, group_id=group_id)
                return None
            message_chain = MessageChain(message_chain)
            result = await self.bot.api.post_group_msg(group_id=group_id, rtf=message_chain)
            message_id = str(result.get("data", {}).get("message_id"))
        except:
            message_id = None
        return message_id

    async def send_direct_message(self, user_id, send_message_obj):
        try:
            message_chain = process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, MessageType.Poke):
                await self.bot.api.send_poke(user_id=ele.pid)
                return None
            message_chain = MessageChain(message_chain)
            result = await self.bot.api.post_private_msg(user_id=user_id, rtf=message_chain)
            message_id = str(result.get("data", {}).get("message_id"))
        except:
            message_id = None
        return message_id

    async def _on_notice_message(self, msg: Dict):
        # print(msg)
        if msg.get("notice_type") == "notify" and msg.get("sub_type") == "poke" and msg.get("self_id") == msg.get("target_id"):
            notice_str = f"[Poke 用户{msg.get('user_id')}{msg['raw_info'][2]['txt']}你{msg['raw_info'][4]['txt']}]"
            message_list = [MessageType.Notice(notice_str)]
            if "group_id" in msg:
                if msg["group_id"] in self.group_list:
                    group_info = self.bot.api.get_group_info_sync(msg.get("group_id"))
                    group_name = group_info.get("data").get("group_name")
                    message_obj = BotGroupMessage(
                        self.name,
                        self.config['adapter_name'],
                        self.message_types,
                        str(msg.get("group_id")),
                        group_name,
                        str(msg.get("user_id")),
                        "user_name 未获取",
                        "message_id",
                        str(msg.get("self_id")),
                        message_list,
                        int(msg.get("time"))
                    )
                    self.publish(message_obj)
            else:
                if msg["user_id"] in self.user_list:
                    message_obj = BotPrivateMessage(self.name, self.config['adapter_name'], self.message_types, str(msg['user_id']), "user_name 未获取",
                                                    "message_id", str(msg["self_id"]), message_list, int(time.time()))
                    self.publish(message_obj)

        elif msg["notice_type"] == "group_ban" and msg["self_id"] == msg["user_id"]:
            ban_duration = msg["duration"]
            ban_operator_id = msg["operator_id"]
            ban_group_id = msg["group_id"]
            if msg["sub_type"] == "ban":
                notice_str = f"[System 用户{ban_operator_id}禁言了你{ban_duration}秒]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = self.bot.api.get_group_info_sync(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if msg["group_id"] in self.group_list:
                    message_obj = BotGroupMessage(
                        self.name,
                        self.config['adapter_name'],
                        self.message_types,
                        str(msg["group_id"]),
                        group_name,
                        str(msg['user_id']),
                        "user_name 未获取",
                        "message_id",
                        str(msg["self_id"]),
                        message_list,
                        int(msg["time"])
                    )
                    self.publish(message_obj)
            elif msg["sub_type"] == "lift_ban":  # 人为解除禁言
                # ban_duration 永远是0，invalid
                notice_str = f"[System 你之前被禁言了，用户{ban_operator_id}解除了你的禁言]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = self.bot.api.get_group_info_sync(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if msg["group_id"] in self.group_list:
                    message_obj = BotGroupMessage(
                        self.name,
                        self.config['adapter_name'],
                        self.message_types,
                        str(msg["group_id"]),
                        group_name,
                        str(msg['user_id']),
                        "user_name 未获取",
                        "message_id",
                        str(msg["self_id"]),
                        message_list,
                        int(msg["time"])
                    )
                    self.publish(message_obj)
            else:
                pass
            # print(ban_duration)
            # print(ban_operator_id)
            # print(ban_group_id)
        elif msg["notice_type"] == "group_increase":
            # and msg["sub_type"] == "approve"
            if "group_id" in msg:
                notice_str = f"[System 用户{msg.get('user_id')}加入了群聊]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = self.bot.api.get_group_info_sync(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if msg["group_id"] in self.group_list:
                    message_obj = BotGroupMessage(
                        self.name,
                        self.config['adapter_name'],
                        self.message_types,
                        str(msg.get("group_id")),
                        group_name,
                        str(msg.get("user_id")),
                        "user_name 未获取",
                        "message_id",
                        str(msg.get("self_id")),
                        message_list,
                        int(msg.get("time"))
                    )
                    self.publish(message_obj)

    async def _on_group_message(self, msg: GroupMessage):
        if msg.group_id in self.group_list:
            # self._log.info(msg)

            should_respond = False

            for m in msg.message:
                if m.get("type") == "at" and (
                        m.get("data", {}).get("qq", "") == str(msg.self_id) or m.get("data", {}).get("qq",
                                                                                                     "") == "all"):
                    should_respond = True
                    break
                elif m.get("type") == "reply":
                    reply_msg_info = await self.bot.api.get_msg(m.get("data", {}).get("id", ""))
                    if reply_msg_info.get("data", {}).get("user_id") == msg.self_id:  # int int
                        should_respond = True
                        break

            if should_respond:
                # 仅进行 Adapter 层职责：打包消息并发布到事件总线，等待主循环回复
                message_list = process_incoming_message(self.bot, msg)
                group_info = self.bot.api.get_group_info_sync(msg.group_id)
                group_name = group_info.get("data").get("group_name")
                message_obj = BotGroupMessage(
                    self.name,
                    self.config['adapter_name'],
                    self.message_types,
                    str(msg.group_id),
                    group_name,
                    str(msg.user_id),
                    msg.sender.nickname,
                    str(msg.message_id),
                    str(msg.self_id),
                    message_list,
                    int(msg.time)
                )
                self.publish(message_obj)

    async def _on_private_message(self, msg: PrivateMessage):
        if msg.user_id in self.user_list:

            # self._log.info(msg)

            message_list = process_incoming_message(self.bot, msg)

            message_obj = BotPrivateMessage(self.name, self.config['adapter_name'], self.message_types, str(msg.user_id), msg.sender.nickname, str(msg.message_id), str(msg.self_id), message_list, int(msg.time))
            self.publish(message_obj)


if __name__ == "__main__":
    pass
