import os
import json
import time
from datetime import datetime
import asyncio
from typing import Any, Dict

from core.adapter.adapter_utils import IMAdapter
from core.logging_manager import get_logger
from core.chat import KiraMessageEvent, MessageChain, MessageType

from .napcat_client import NapCatWebSocketClient, QQMessageChain, QQMessageType


def extract_card_info(card_json: str) -> str:
    card_json = json.loads(card_json)
    detail = card_json.get("meta", {}).get("detail_1", {})
    card_json_dic = {
        "title": detail.get("title", ""),
        "desc": detail.get("desc", ""),
        # "icon": detail.get("icon", ""),
        # "preview": detail.get("preview", ""),
        # "url": detail.get("url", ""),
        # "qqdocurl": detail.get("qqdocurl", ""),
        "appid": detail.get("appid", ""),
        "nick": detail.get("host", {}).get("nick", ""),
        "prompt": card_json.get("prompt", ""),
        "app": card_json.get("app", "")
    }
    return json.dumps(card_json_dic, ensure_ascii=False)


class QQAdapter(IMAdapter):
    def __init__(self, info, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue, llm_api):
        super().__init__(info, loop, event_bus, llm_api)
        self.emoji_dict = self._load_dict(os.path.join(os.path.dirname(os.path.abspath(__file__)), "emoji.json"))
        self.message_types = ["text", "img", "at", "reply", "record", "emoji", "sticker", "poke", "selfie"]
        self.bot: NapCatWebSocketClient = NapCatWebSocketClient()
        self.logger = get_logger(info.name, "blue")

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """加载字典"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception as e:
            return {}

    async def start_blocking(self):
        @self.bot.group_event()
        async def on_group_message(msg: Dict):
            await self._on_group_message(msg)

        @self.bot.private_event()
        async def on_private_message(msg: Dict):
            await self._on_private_message(msg)

        @self.bot.notice_event()
        async def on_notice_message(msg: Dict):
            await self._on_notice_message(msg)

        @self.bot.meta_event()
        async def on_meta_message(msg: Dict):
            # print(msg)
            pass

        @self.bot.napcat_event()
        async def on_napcat_message(msg: Dict):
            # self.logger.info(f"napcat event: {msg}")
            pass

        await self.bot.run(bt_uin=self.config["bot_pid"], ws_uri=self.config["ws_uri"], ws_token=self.config["ws_token"])

    async def start(self):
        task = asyncio.create_task(self.start_blocking())

    async def stop(self):
        await self.bot.close()

    def get_client(self) -> NapCatWebSocketClient:
        return self.bot

    async def send_group_message(self, group_id, send_message_obj):
        try:
            message_chain = self._process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, MessageType.Poke):
                await self.bot.send_poke(user_id=ele.pid, group_id=group_id)
                return None
            message_chain = QQMessageChain(message_chain)
            result = await self.bot.send_group_message(group_id=group_id, msg=message_chain)
            status = result.get("status")
            retcode = result.get("retcode")
            if status == "failed":
                if retcode == 1200:
                    self.logger.error("禁言中或达到发言频率限制，消息发送失败")
                else:
                    self.logger.error(f"未知错误，消息发送失败，错误码：{retcode}")
            message_id = str(result.get("data", {}).get("message_id"))
        except:
            message_id = None
        return message_id

    async def send_direct_message(self, user_id, send_message_obj):
        try:
            message_chain = self._process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, MessageType.Poke):
                await self.bot.send_poke(user_id=ele.pid)
                return None
            message_chain = QQMessageChain(message_chain)
            result = await self.bot.send_direct_message(user_id=user_id, msg=message_chain)
            status = result.get("status")
            retcode = result.get("retcode")
            if status == "failed":
                self.logger.error(f"未知错误，消息发送失败，错误码：{retcode}")

            message_id = str(result.get("data", {}).get("message_id"))
        except:
            message_id = None
        return message_id

    async def process_incoming_message(self, msg):
        """把QQ平台消息转换为项目通用消息格式"""
        message_content = []
        for ele in msg.get("message"):
            if ele.get("type") == "text":
                message_content.append(MessageType.Text(ele.get("data").get("text")))
            elif ele.get("type") == "at":
                at_obj = MessageType.At(str(ele.get("data").get("qq")))
                if str(ele.get("data").get("qq")) != "all":
                    at_user_info = await self.bot.get_user_info(user_id=str(ele.get("data").get("qq")))
                    at_nickname = at_user_info["data"]["nickname"]
                    at_obj.nickname = at_nickname
                message_content.append(at_obj)
            elif ele.get("type") == "reply":
                reply_content = await self.bot.get_msg(ele.get("data").get("id"))
                processed_reply = await self._process_reply_message(reply_content)
                message_content.append(MessageType.Reply(ele.get("data").get("id"), processed_reply))
            elif ele.get("type") == "face":
                message_content.append(MessageType.Emoji(str(ele.get("data").get("id"))))
            elif ele.get("type") == "image":
                img_url = ele.get("data", "").get("url", "")

                summary = ele.get("data", "").get("summary", "")
                sub_type = ele.get("data", "").get("sub_type", 0)

                if sub_type == 1 or summary == "[动画表情]":
                    from core.utils.common_utils import image_to_base64
                    message_content.append(MessageType.Sticker(sticker_bs64=image_to_base64(img_url)))
                else:
                    message_content.append(MessageType.Image(img_url))
            elif ele.get("type") == "video":
                video_file_name = ele.get("data", {}).get("file", "")  # e.g. xxx.mp4
                video_file_url = ele.get("data", {}).get("url", "")
                video_file_size = ele.get("data", {}).get("file_size", "")  # Bytes, str
                message_content.append(MessageType.Text("[Video]"))
            elif ele.get("type") == "json":
                json_card_info = ele.get("data", "").get("data", "")
                cleaned_card_info = extract_card_info(json_card_info)
                message_content.append(MessageType.Text(f"[Json {cleaned_card_info}]"))
            elif ele.get("type") == "file":
                file_name = ele.get("data").get("file")
                file_id = ele.get("data").get("file_id")
                file_size = ele.get("data").get("file_size")  # Bytes, str
                message_content.append(MessageType.Text(f"[File {file_name}]"))
            elif ele.get("type") == "forward":
                forward_message = await self.bot.get_forward_msg(msg.get("message_id"))
                processed_forward = await self._process_forward_message(forward_message)
                message_content.append(MessageType.Text(f"[Forward {processed_forward}]"))
            elif ele.get("type") == "record":
                file_id = ele.get("data").get("file")

                record_info = await self.bot.get_record(file_id, output_format="mp3")
                audio_base64 = record_info.get("data").get("base64")
                message_content.append(MessageType.Record(audio_base64))
        return message_content

    async def _on_notice_message(self, msg: Dict):
        if msg.get("notice_type") == "notify" and msg.get("sub_type") == "poke" and msg.get("self_id") == msg.get("target_id"):
            notice_str = f"[Poke 用户{msg.get('user_id')}{msg['raw_info'][2]['txt']}你{msg['raw_info'][4]['txt']}]"
            message_list = [MessageType.Notice(notice_str)]
            if "group_id" in msg:
                if str(msg["group_id"]) in self.group_list:
                    group_info = await self.bot.get_group_info(msg.get("group_id"))
                    group_name = group_info.get("data").get("group_name")
                    message_obj = KiraMessageEvent(
                        platform=self.info.platform,
                        adapter_name=self.info.name,
                        message_types=self.message_types,
                        group_id=str(msg.get("group_id")),
                        group_name=group_name,
                        user_id=str(msg.get("user_id")),
                        user_nickname="None",
                        message_id="None",
                        self_id=str(msg.get("self_id")),
                        content=message_list,
                        timestamp=int(msg.get("time"))
                    )
                    self.publish(message_obj)
            else:
                if str(msg["user_id"]) in self.user_list:
                    message_obj = KiraMessageEvent(self.info.platform, self.info.name, self.message_types, str(msg['user_id']), "user_name 未获取",
                                                    "None", str(msg["self_id"]), message_list, int(time.time()))
                    self.publish(message_obj)

        elif msg.get("notice_type") == "group_ban" and msg.get("self_id") == msg.get("user_id"):
            ban_duration = msg["duration"]
            ban_operator_id = msg["operator_id"]
            ban_group_id = msg["group_id"]
            if msg["sub_type"] == "ban":
                notice_str = f"[System 用户{ban_operator_id}禁言了你{ban_duration}秒]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = await self.bot.get_group_info(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if str(msg["group_id"]) in self.group_list:
                    message_obj = KiraMessageEvent(
                        platform=self.info.platform,
                        adapter_name=self.info.name,
                        message_types=self.message_types,
                        group_id=str(msg.get("group_id")),
                        group_name=group_name,
                        user_id=str(msg.get("user_id")),
                        user_nickname="None",
                        message_id="None",
                        self_id=str(msg.get("self_id")),
                        content=message_list,
                        timestamp=int(msg.get("time"))
                    )
                    self.publish(message_obj)
            elif msg["sub_type"] == "lift_ban":  # 人为解除禁言
                # ban_duration 永远是0，invalid
                notice_str = f"[System 你之前被禁言了，用户{ban_operator_id}解除了你的禁言]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = await self.bot.get_group_info(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if str(msg["group_id"]) in self.group_list:
                    message_obj = KiraMessageEvent(
                        platform=self.info.platform,
                        adapter_name=self.info.name,
                        message_types=self.message_types,
                        group_id=str(msg.get("group_id")),
                        group_name=group_name,
                        user_id=str(msg.get("user_id")),
                        user_nickname="None",
                        message_id="None",
                        self_id=str(msg.get("self_id")),
                        content=message_list,
                        timestamp=int(msg.get("time"))
                    )
                    self.publish(message_obj)
            else:
                pass
            # print(ban_duration)
            # print(ban_operator_id)
            # print(ban_group_id)
        elif msg.get("notice_type") == "group_increase":
            # and msg["sub_type"] == "approve"
            if "group_id" in msg:
                notice_str = f"[System 用户{msg.get('user_id')}加入了群聊]"
                message_list = [MessageType.Notice(notice_str)]
                group_info = await self.bot.get_group_info(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                if str(msg["group_id"]) in self.group_list:
                    message_obj = KiraMessageEvent(
                        platform=self.info.platform,
                        adapter_name=self.info.name,
                        message_types=self.message_types,
                        group_id=str(msg.get("group_id")),
                        group_name=group_name,
                        user_id=str(msg.get("user_id")),
                        user_nickname="None",
                        message_id="None",
                        self_id=str(msg.get("self_id")),
                        content=message_list,
                        timestamp=int(msg.get("time"))
                    )
                    self.publish(message_obj)

    async def _on_group_message(self, msg):
        should_process = False

        if self.permission_mode == "allow_list" and str(msg.get("group_id")) in self.group_list:
            should_process = True
        elif self.permission_mode == "deny_list" and str(msg.get("group_id")) not in self.group_list:
            should_process = True

        if should_process:
            # self._log.info(msg)

            should_respond = False

            for m in msg.get("message", {}):
                if m.get("type") == "at" and (
                        m.get("data", {}).get("qq", "") == str(msg.get("self_id")) or m.get("data", {}).get("qq", "") == "all"):
                    should_respond = True
                    break
                elif m.get("type") == "reply":
                    reply_msg_info = await self.bot.get_msg(m.get("data", {}).get("id", ""))
                    if reply_msg_info.get("data", {}).get("user_id") == msg.get("self_id"):  # int int
                        should_respond = True
                        break
                elif m.get("type") == "text":
                    message_text = m.get("data").get("text")
                    waking_keywords_config = self.config.get("waking_keywords", [])
                    if waking_keywords_config:
                        if isinstance(waking_keywords_config, str):
                            waking_keywords = [kw.strip() for kw in self.config.get("waking_keywords", "").split(",")]
                        else:
                            waking_keywords = waking_keywords_config
                        if any(kw in message_text for kw in waking_keywords):
                            should_respond = True
                            break

            # should_respond = True

            if should_respond:
                message_list = await self.process_incoming_message(msg)

                group_info = await self.bot.get_group_info(msg.get("group_id"))
                group_name = group_info.get("data").get("group_name")
                message_obj = KiraMessageEvent(
                    platform=self.info.platform,
                    adapter_name=self.info.name,
                    message_types=self.message_types,
                    group_id=str(msg.get("group_id")),
                    group_name=group_name,
                    user_id=str(msg.get("user_id")),
                    user_nickname=msg.get("sender").get("nickname"),
                    message_id=str(msg.get("message_id")),
                    self_id=str(msg.get("self_id")),
                    content=message_list,
                    timestamp=int(msg.get("time"))
                )
                self.publish(message_obj)

    async def _on_private_message(self, msg: dict):
        should_process = False

        if self.permission_mode == "allow_list" and str(msg.get("user_id")) in self.user_list:
            should_process = True
        elif self.permission_mode == "deny_list" and str(msg.get("user_id")) not in self.user_list:
            should_process = True

        if should_process:

            # self._log.info(msg)

            message_list = await self.process_incoming_message(msg)

            message_obj = KiraMessageEvent(
                platform=self.info.platform,
                adapter_name=self.info.name,
                message_types=self.message_types,
                user_id=str(msg.get("user_id")),
                user_nickname=msg.get("sender").get("nickname"),
                message_id=str(msg.get("message_id")),
                self_id=str(msg.get("self_id")),
                content=message_list,
                timestamp=int(msg.get("time")))
            self.publish(message_obj)

    async def _process_reply_message(self, message_data):
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
                img_desc = await self.llm_api.desc_img(d.get('url', ''))
                parts.append(f"[Image {img_desc}]")
            elif t == "face":
                parts.append(f"[Emoji {d.get('id')}]")
            elif t == "json":
                json_card_info = d.get("data", "")
                cleaned_card_info = extract_card_info(json_card_info)
                parts.append(f"[Json {cleaned_card_info}]")
            elif t == "reply":
                parts.append(f"[Reply {d.get('id')}]")
            else:
                parts.append(f"[{t}]")

        content = " ".join(parts).strip()
        return f"{sender}  [{time_str}]\n{content}"

    async def _process_forward_message(self, message_data):
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
                    img_desc = await self.llm_api.desc_img(d.get('url', ''))
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

    def _process_outgoing_message(self, message: MessageChain):
        """将通用消息格式转换为QQ消息格式"""
        message_chain_elements = []
        for ele in message.message_list:
            if isinstance(ele, MessageType.Text):
                message_chain_elements.append(QQMessageType.Text(ele.text))
            elif isinstance(ele, MessageType.Emoji):
                if ele.emoji_id in self.emoji_dict:
                    message_chain_elements.append(QQMessageType.Emoji(int(ele.emoji_id)))
                else:
                    self.logger.warning(f"未定义的 Emoji ID: {ele.emoji_id}")
            elif isinstance(ele, MessageType.Sticker):
                message_chain_elements.append(QQMessageType.Image(f"base64://{ele.sticker_bs64}"))
            elif isinstance(ele, MessageType.At):
                val = ele.pid
                message_chain_elements.append(QQMessageType.At(val))
                message_chain_elements.append(QQMessageType.Text(" "))
            elif isinstance(ele, MessageType.Image):
                if ele.url:
                    message_chain_elements.append(QQMessageType.Image(ele.url))
                elif ele.base64:
                    message_chain_elements.append(QQMessageType.Image(f"base64://{ele.base64}"))
            elif isinstance(ele, MessageType.Reply):
                message_chain_elements.append(QQMessageType.Reply(ele.message_id))
            elif isinstance(ele, MessageType.Record):
                message_chain_elements.append(QQMessageType.Record(f"base64://{ele.bs64}"))
            elif isinstance(ele, MessageType.Notice):
                # 可以实现定时主动消息等
                pass
            elif isinstance(ele, MessageType.Poke):
                message_chain_elements.append(ele)
            else:
                pass
        return message_chain_elements


if __name__ == "__main__":
    pass
