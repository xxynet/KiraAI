import os
import json
import time
from datetime import datetime
import asyncio
from typing import Any, Dict

from core.adapter.adapter_utils import IMAdapter
from core.logging_manager import get_logger
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult

from core.chat.message_elements import (
    Text,
    Image,
    At,
    Reply,
    Forward,
    Emoji,
    Sticker,
    Record,
    Notice,
    Poke,
    File,
    Video
)

from core.chat import Session, Group, User

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
        self.message_types = ["text", "img", "at", "reply", "record", "emoji", "sticker", "poke", "selfie", "file", "video", "forward"]
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
            message_chain = await self._process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, Poke):
                await self.bot.send_poke(user_id=ele.pid, group_id=group_id)
                return KiraIMSentResult(message_id=None, is_notice=True)
            elif isinstance(ele, File):
                msg_res = KiraIMSentResult(None)
                try:
                    if ele.file_type == "url":
                        file_string = ele.file
                    else:
                        file_b64 = await ele.to_base64()
                        file_string = f"base64://{file_b64}"
                    file_name = ele.name
                    if not file_name:
                        import uuid
                        file_name = uuid.uuid4().hex
                    resp = await self.bot.upload_group_file(str(group_id), file_string, file_name)
                    if not isinstance(resp, dict):
                        msg_res.ok = False
                        msg_res.err = f"Failed to send file: invalid response {resp!r}"
                        return msg_res
                    message_id = str((resp.get("data") or {}).get("message_id"))
                    if resp.get("status") != "ok":
                        msg_res.ok = False
                        msg_res.err = f"Failed to send file: {resp}"
                        return msg_res
                    msg_res.message_id = message_id
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while uploading file: {e}"
                return msg_res
            elif isinstance(ele, Video):
                msg_res = KiraIMSentResult(None)
                try:
                    if ele.file_type == "url":
                        video_file = ele.file
                    else:
                        video_file_b64 = await ele.to_base64()
                        video_file = f"base64://{video_file_b64}"
                    video_file_name = ele.name
                    if not video_file_name:
                        import uuid
                        video_file_name = uuid.uuid4().hex
                    resp = await self.bot.send_action("send_group_msg", {
                        "group_id": group_id,
                        "message": [
                            {
                                "type": "video",
                                "data": {
                                    "name": video_file_name,
                                    "file": video_file,
                                }
                            }
                        ]
                    })
                    if not isinstance(resp, dict):
                        msg_res.ok = False
                        msg_res.err = f"Failed to send video: invalid response {resp!r}"
                        return msg_res
                    message_id = str((resp.get("data") or {}).get("message_id"))
                    if resp.get("status") != "ok":
                        msg_res.ok = False
                        msg_res.err = f"Failed to send video: {resp}"
                        return msg_res
                    msg_res.message_id = message_id
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while uploading video: {e}"
                return msg_res
            elif isinstance(ele, Forward):
                msg_res = KiraIMSentResult(None)
                try:
                    forward_message_id = ele.message_id
                    merge = ele.merge

                    if merge:
                        resp = await self.bot.send_action(
                            action="send_group_msg",
                            params={
                                "group_id": group_id,
                                "message": [
                                    {
                                        "type": "node",
                                        "data": {
                                            "id": x
                                        }
                                    } for x in forward_message_id
                                ],

                            }
                        )
                        if not isinstance(resp, dict):
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: invalid response {resp!r}"
                            return msg_res
                        message_id = str((resp.get("data") or {}).get("message_id"))
                        if resp.get("status") != "ok":
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: {resp}"
                            return msg_res
                        msg_res.message_id = message_id

                    elif len(forward_message_id) == 1:
                        resp = await self.bot.send_action(
                            action="forward_group_single_msg",
                            params={
                                "message_id": forward_message_id[0],
                                "group_id": group_id
                            }
                        )
                        if not isinstance(resp, dict):
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: invalid response {resp!r}"
                            return msg_res
                        message_id = str((resp.get("data") or {}).get("message_id"))
                        if resp.get("status") != "ok":
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: {resp}"
                            return msg_res
                        msg_res.message_id = message_id
                    else:
                        self.logger.warning("尝试发送多条逐条转发消息")
                        ...
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while forwarding message: {e}"
                return msg_res

            message_chain = QQMessageChain(message_chain)
            result = await self.bot.send_group_message(group_id=group_id, msg=message_chain)
            status = result.get("status")
            retcode = result.get("retcode")
            msg_res = KiraIMSentResult(None)
            if status == "failed":
                msg_res.ok = False
                if retcode == 1200:
                    msg_res.err = "禁言中或达到发言频率限制，消息发送失败"
                else:
                    msg_res.err = f"未知错误，消息发送失败，错误码：{retcode}"
                return msg_res
            message_id = str(result.get("data", {}).get("message_id"))
            msg_res.message_id = message_id
            return msg_res
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=str(e))

    async def send_direct_message(self, user_id, send_message_obj):
        msg_res = KiraIMSentResult(None)
        try:
            message_chain = await self._process_outgoing_message(send_message_obj)
            ele = message_chain[0]
            if isinstance(ele, Poke):
                await self.bot.send_poke(user_id=ele.pid)
                msg_res.is_notice = True
                return msg_res
            elif isinstance(ele, File):
                try:
                    if ele.file_type == "url":
                        file_string = ele.file
                    else:
                        file_b64 = await ele.to_base64()
                        file_string = f"base64://{file_b64}"
                    file_name = ele.name
                    if not file_name:
                        import uuid
                        file_name = uuid.uuid4().hex
                    resp = await self.bot.upload_private_file(str(user_id), file_string, file_name)
                    if not isinstance(resp, dict):
                        msg_res.ok = False
                        msg_res.err = f"Failed to send file: invalid response {resp!r}"
                        return msg_res
                    message_id = str((resp.get("data") or {}).get("message_id"))
                    if resp.get("status") != "ok":
                        msg_res.ok = False
                        msg_res.err = f"Failed to send file: {resp}"
                        return msg_res
                    msg_res.message_id = message_id
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while uploading file: {e}"
                return msg_res
            elif isinstance(ele, Video):
                try:
                    if ele.file_type == "url":
                        video_file = ele.file
                    else:
                        video_file_b64 = await ele.to_base64()
                        video_file = f"base64://{video_file_b64}"
                    video_file_name = ele.name
                    if not video_file_name:
                        import uuid
                        video_file_name = uuid.uuid4().hex
                    resp = await self.bot.send_action("send_private_msg", {
                        "user_id": user_id,
                        "message": [
                            {
                                "type": "video",
                                "data": {
                                    "name": video_file_name,
                                    "file": video_file,
                                }
                            }
                        ]
                    })
                    if not isinstance(resp, dict):
                        msg_res.ok = False
                        msg_res.err = f"Failed to send video: invalid response {resp!r}"
                        return msg_res
                    message_id = str((resp.get("data") or {}).get("message_id"))
                    if resp.get("status") != "ok":
                        msg_res.ok = False
                        msg_res.err = f"Failed to send video: {resp}"
                        return msg_res
                    msg_res.message_id = message_id
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while uploading video: {e}"
                return msg_res
            elif isinstance(ele, Forward):
                msg_res = KiraIMSentResult(None)
                try:
                    forward_message_id = ele.message_id
                    merge = ele.merge

                    if merge:
                        resp = await self.bot.send_action(
                            action="send_private_msg",
                            params={
                                "user_id": user_id,
                                "message": [
                                    {
                                        "type": "node",
                                        "data": {
                                            "id": x
                                        }
                                    } for x in forward_message_id
                                ],

                            }
                        )
                        if not isinstance(resp, dict):
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: invalid response {resp!r}"
                            return msg_res
                        message_id = str((resp.get("data") or {}).get("message_id"))
                        if resp.get("status") != "ok":
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: {resp}"
                            return msg_res
                        msg_res.message_id = message_id
                    elif len(forward_message_id) == 1:

                        resp = await self.bot.send_action(
                            action="forward_friend_single_msg",
                            params={
                                "message_id": forward_message_id[0],
                                "user_id": user_id
                            }
                        )
                        if not isinstance(resp, dict):
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: invalid response {resp!r}"
                            return msg_res
                        message_id = str((resp.get("data") or {}).get("message_id"))
                        if resp.get("status") != "ok":
                            msg_res.ok = False
                            msg_res.err = f"Failed to forward message: {resp}"
                            return msg_res
                        msg_res.message_id = message_id
                    else:
                        self.logger.warning("尝试发送多条逐条转发消息")
                        ...
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = f"Error occurred while forwarding message: {e}"
                return msg_res

            message_chain = QQMessageChain(message_chain)
            result = await self.bot.send_direct_message(user_id=user_id, msg=message_chain)
            status = result.get("status")
            retcode = result.get("retcode")
            if status == "failed":
                msg_res.ok = False
                msg_res.err = f"未知错误，消息发送失败，错误码：{retcode}"
                return msg_res
            message_id = str(result.get("data", {}).get("message_id"))
            msg_res.message_id = message_id
        except Exception as e:
            msg_res.ok = False
            msg_res.err = str(e)
        return msg_res

    async def process_incoming_message(self, msg):
        """把QQ平台消息转换为项目通用消息格式"""
        message_type = msg.get("message_type")
        group_id = msg.get("group_id")

        message_content = []
        for ele in msg.get("message"):
            if ele.get("type") == "text":
                message_content.append(Text(ele.get("data").get("text")))
            elif ele.get("type") == "at":
                at_obj = At(str(ele.get("data").get("qq")))
                if str(ele.get("data").get("qq")) != "all":
                    at_user_info = await self.bot.get_user_info(user_id=str(ele.get("data").get("qq")))
                    at_nickname = at_user_info["data"]["nickname"]
                    at_obj.nickname = at_nickname
                message_content.append(at_obj)
            elif ele.get("type") == "reply":
                reply_content = await self.bot.get_msg(ele.get("data").get("id"))
                reply_chain = await self._process_reply_message(reply_content)
                message_content.append(Reply(ele.get("data").get("id"), chain=reply_chain))
            elif ele.get("type") == "face":
                emoji_id = str(ele.get("data").get("id"))
                emoji_desc = self.emoji_dict.get(emoji_id)
                message_content.append(Emoji(emoji_id, emoji_desc))
            elif ele.get("type") == "image":
                img_url = ele.get("data", "").get("url", "")

                summary = ele.get("data", "").get("summary", "")
                sub_type = ele.get("data", "").get("sub_type", 0)

                if sub_type == 1 or summary == "[动画表情]":
                    from core.utils.common_utils import image_to_base64
                    sticker_bs64 = await image_to_base64(img_url)
                    message_content.append(Sticker(sticker=sticker_bs64))
                else:
                    message_content.append(Image(image=img_url))
            elif ele.get("type") == "video":
                video_file_name = ele.get("data", {}).get("file", "")  # e.g. xxx.mp4
                video_file_url = ele.get("data", {}).get("url", "")
                video_file_size = ele.get("data", {}).get("file_size", "")  # Bytes, str
                video_obj = Video(file=video_file_url, name=video_file_name, size=video_file_size)
                message_content.append(video_obj)
            elif ele.get("type") == "json":
                json_card_info = ele.get("data", "").get("data", "")
                cleaned_card_info = extract_card_info(json_card_info)
                message_content.append(Text(f"[Json {cleaned_card_info}]"))
            elif ele.get("type") == "file":
                file_name = ele.get("data").get("file")
                file_id = ele.get("data").get("file_id")
                file_size = ele.get("data").get("file_size")  # Bytes, str

                if message_type == "group":
                    file_info = await self.bot.send_action("get_group_file_url", {"group_id": group_id, "file_id": file_id})
                    if not file_info:
                        continue
                    file_url = file_info.get("data", {}).get("url")
                elif message_type == "private":
                    file_info = await self.bot.send_action("get_private_file_url", {"file_id": file_id})
                    if not file_info:
                        continue
                    file_url = file_info.get("data", {}).get("url")
                else:
                    continue

                if not file_url:
                    message_content.append(Text(f"[File {file_name}]"))
                    continue

                file_obj = File(file=file_url, name=file_name, size=file_size)
                message_content.append(file_obj)

                # file_info = await self.bot.send_action("get_file", {"file_id": file_id})
                # file_b64 = file_info.get("data", {}).get("base64")

            elif ele.get("type") == "forward":
                forward_message_id = msg.get("message_id")
                forward_message = await self.bot.get_forward_msg(forward_message_id)
                forward_chains = await self._process_forward_message(forward_message)
                message_content.append(Forward(chains=forward_chains))
            elif ele.get("type") == "record":
                file_id = ele.get("data").get("file")

                record_info = await self.bot.get_record(file_id, output_format="mp3")
                audio_base64 = record_info.get("data").get("base64")
                message_content.append(Record(record=audio_base64))
        return MessageChain(message_content)

    async def _on_notice_message(self, msg: Dict):
        notice_type = msg.get("notice_type")
        sub_type = msg.get("sub_type")
        self_id = msg.get("self_id")
        user_id = msg.get("user_id")
        target_id = msg.get("target_id")
        group_id = msg.get("group_id")

        group_obj = None

        if notice_type == "notify" and sub_type == "poke" and self_id == target_id:
            notice_str = f"[Poke 用户{user_id}{msg['raw_info'][2]['txt']}你{msg['raw_info'][4]['txt']}]"
            message_list = [Notice(notice_str)]

            if group_id:
                if str(group_id) not in self.group_list:
                    return

                group_info = await self.bot.get_group_info(group_id)
                group_name = group_info.get("data").get("group_name")

                group_obj = Group(
                    group_id=str(group_id),
                    group_name=group_name
                )
            else:
                if str(user_id) not in self.user_list:
                    return

        elif notice_type == "group_ban" and self_id == user_id:
            ban_duration = msg["duration"]
            ban_operator_id = msg["operator_id"]
            ban_group_id = msg["group_id"]
            if sub_type == "ban":
                notice_str = f"[System 用户{ban_operator_id}禁言了你{ban_duration}秒]"
                message_list = [Notice(notice_str)]
                group_info = await self.bot.get_group_info(group_id)
                group_name = group_info.get("data").get("group_name")

                group_obj = Group(
                    group_id=str(group_id),
                    group_name=group_name
                )

                if str(group_id) not in self.group_list:
                    return

            elif sub_type == "lift_ban":  # 人为解除禁言
                # ban_duration 永远是0，invalid
                notice_str = f"[System 你之前被禁言了，用户{ban_operator_id}解除了你的禁言]"
                message_list = [Notice(notice_str)]
                group_info = await self.bot.get_group_info(group_id)
                group_name = group_info.get("data").get("group_name")

                group_obj = Group(
                    group_id=str(group_id),
                    group_name=group_name
                )

                if str(group_id) not in self.group_list:
                    return

            else:
                return
            # print(ban_duration)
            # print(ban_operator_id)
            # print(ban_group_id)
        elif notice_type == "group_increase":
            # and msg["sub_type"] == "approve"
            if not group_id:
                return

            notice_str = f"[System 用户{user_id}加入了群聊]"
            message_list = [Notice(notice_str)]
            group_info = await self.bot.get_group_info(group_id)
            group_name = group_info.get("data").get("group_name")

            group_obj = Group(
                group_id=str(group_id),
                group_name=group_name
            )

            if str(group_id) not in self.group_list:
                return
        else:
            return

        message_obj = KiraMessageEvent(
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=int(msg.get("time") or time.time()),
                message_id="None",
                group=group_obj,
                sender=User(
                    user_id=str(user_id),
                    nickname="None"
                ),
                is_notice=True,
                is_mentioned=True,
                self_id=str(self_id),
                chain=message_list,
            ),
            timestamp=int(msg.get("time") or time.time())
        )
        self.publish(message_obj)

    async def _on_group_message(self, msg):
        should_process = False

        if self.permission_mode == "allow_list" and str(msg.get("group_id")) in self.group_list:
            should_process = True
        elif self.permission_mode == "deny_list" and str(msg.get("group_id")) not in self.group_list:
            should_process = True

        if not should_process:
            return

        is_mentioned = False

        for m in msg.get("message", {}):
            at_id = m.get("data", {}).get("qq", "")
            if m.get("type") == "at" and (at_id == str(msg.get("self_id")) or at_id == "all"):
                is_mentioned = True
                break
            elif m.get("type") == "reply":
                reply_msg_info = await self.bot.get_msg(m.get("data", {}).get("id", ""))
                if reply_msg_info.get("data", {}).get("user_id") == msg.get("self_id"):  # int int
                    is_mentioned = True
                    break

        message_chain = await self.process_incoming_message(msg)

        group_info = await self.bot.get_group_info(msg.get("group_id"))
        group_name = group_info.get("data").get("group_name")

        message_obj = KiraMessageEvent(
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=int(msg.get("time") or time.time()),
                group=Group(
                    group_id=str(msg.get("group_id")),
                    group_name=group_name
                ),
                sender=User(
                    user_id=str(msg.get("user_id")),
                    nickname=msg.get("sender").get("nickname")
                ),
                is_mentioned=is_mentioned,
                message_id=str(msg.get("message_id")),
                self_id=str(msg.get("self_id")),
                chain=message_chain,
                extra=msg
            ),
            timestamp=int(msg.get("time") or time.time())
        )
        self.publish(message_obj)

    async def _on_private_message(self, msg: dict):
        should_process = False

        if self.permission_mode == "allow_list" and str(msg.get("user_id")) in self.user_list:
            should_process = True
        elif self.permission_mode == "deny_list" and str(msg.get("user_id")) not in self.user_list:
            should_process = True

        if not should_process:
            return

        message_chain = await self.process_incoming_message(msg)

        message_obj = KiraMessageEvent(
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=int(msg.get("time") or time.time()),
                sender=User(
                    user_id=str(msg.get("user_id")),
                    nickname=msg.get("sender").get("nickname")
                ),
                message_id=str(msg.get("message_id")),
                is_mentioned=True,
                self_id=str(msg.get("self_id")),
                chain=message_chain,
                extra=msg
            ),
            timestamp=int(msg.get("time") or time.time())
        )
        self.publish(message_obj)

    async def _process_reply_message(self, message_data):
        if not message_data:
            return MessageChain([])

        data = message_data.get("data") or {}
        if not data:
            return MessageChain([])

        msg = data
        sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
        ts = msg.get("time", 0)
        dt = datetime.fromtimestamp(ts)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        inner_elements_chain = await self.process_incoming_message(msg)
        elements = [Text(f"[{time_str}] {sender}: ")]
        elements.extend(inner_elements_chain.message_list)
        return MessageChain(elements)

    async def _process_forward_message(self, message_data):
        if not message_data:
            self.logger.warning("处理转发消息时获取到了空消息")
            return
        messages = message_data.get("data", {}).get("messages", [])

        chains = []
        for msg in messages:
            sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
            ts = msg.get("time", 0)
            dt = datetime.fromtimestamp(ts)  # 转换成可读时间
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

            elements = [Text(f"[{time_str}] {sender}: ")]
            inner_elements_chain = await self.process_incoming_message(msg)
            elements.extend(inner_elements_chain.message_list)
            chains.append(MessageChain(elements))

        return chains
        # 组合消息内容
        # result = []
        # for msg in messages:
        #     parts = []
        #     for seg in msg.get("message", []):
        #         t = seg.get("type")
        #         d = seg.get("data", {})
        #         if t == "text":
        #             parts.append(d.get("text", ""))
        #         elif t == "at":
        #             parts.append(f"[At {d.get('qq')}]")
        #         elif t == "image":
        #             img_desc = await self.llm_api.desc_img(d.get('url', ''))
        #             parts.append(f"[Image {img_desc}]")
        #         elif t == "face":
        #             parts.append(f"[Emoji {d.get('id')}]")
        #         elif t == "reply":
        #             parts.append(f"[Reply {d.get('id')}]")
        #         else:
        #             parts.append(f"[{t}]")
        #
        #     content = " ".join(parts).strip()
        #     result.append(f"{sender}  [{time_str}]\n{content}\n")
        #
        # return "\n".join(result)

    async def _process_outgoing_message(self, message: MessageChain):
        """将通用消息格式转换为QQ消息格式"""
        message_chain_elements = []
        for ele in message:
            if isinstance(ele, Text):
                message_chain_elements.append(QQMessageType.Text(ele.text))
            elif isinstance(ele, Emoji):
                if ele.emoji_id in self.emoji_dict:
                    message_chain_elements.append(QQMessageType.Emoji(int(ele.emoji_id)))
                else:
                    self.logger.warning(f"未定义的 Emoji ID: {ele.emoji_id}")
            elif isinstance(ele, Sticker):
                sticker_base64 = await ele.to_base64()
                message_chain_elements.append(QQMessageType.Image(f"base64://{sticker_base64}"))
            elif isinstance(ele, At):
                val = ele.pid
                message_chain_elements.append(QQMessageType.At(val))
                message_chain_elements.append(QQMessageType.Text(" "))
            elif isinstance(ele, Image):
                if ele.image_type == "url":
                    message_chain_elements.append(QQMessageType.Image(ele.image))
                else:
                    image_base64 = await ele.to_base64()
                    message_chain_elements.append(QQMessageType.Image(f"base64://{image_base64}"))
            elif isinstance(ele, Reply):
                message_chain_elements.append(QQMessageType.Reply(ele.message_id))
            elif isinstance(ele, Record):
                record_base64 = await ele.to_base64()
                message_chain_elements.append(QQMessageType.Record(f"base64://{record_base64}"))
            elif isinstance(ele, Notice):
                # 可以实现定时主动消息等
                pass
            elif isinstance(ele, Poke):
                message_chain_elements.append(ele)
            elif isinstance(ele, File):
                message_chain_elements.append(ele)
            elif isinstance(ele, Video):
                message_chain_elements.append(ele)
            elif isinstance(ele, Forward):
                message_chain_elements.append(ele)
            else:
                pass
        return message_chain_elements


if __name__ == "__main__":
    pass
