from __future__ import annotations

import json
import time
from pathlib import Path
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Dict

from core.adapter.base import AdapterTargetId
from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata, load_emoji_mapping
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult
from core.chat.message_elements import (
    Text, Image, At, Reply, Forward, Emoji, Sticker, Record, Poke, Json, File, Video,
)
from core.chat import Group, User

from .napcat_client import QQMessageChain, QQMessageType

if TYPE_CHECKING:
    from .qq import QQAdapter


def extract_card_info(card_json: str) -> dict:
    try:
        card_json = json.loads(card_json)
    except (json.JSONDecodeError, TypeError):
        return {"raw": card_json} if isinstance(card_json, str) else {}

    meta = card_json.get("meta", {})
    content = (
        meta.get("detail_1")
        or meta.get("news")
        or meta.get("music")
        or meta
    )

    result = {}

    # Top-level card fields.
    for key in ("app", "prompt", "bizsrc", "view"):
        val = card_json.get(key, "")
        if val:
            result[key] = val

    # Content fields from detail_1, news, music, or the fallback metadata.
    if isinstance(content, dict):
        for key in ("title", "desc", "jumpUrl", "qqdocurl", "tag"):
            val = content.get(key, "")
            if val:
                result[key] = val

    return result


class QQIMCapability(IMCapability["QQAdapter"]):
    """Convert, receive and send OneBot messages for the owning QQ account."""

    _SUPPORTED_ELEMENTS = ["text", "img", "at", "reply", "record", "emoji", "sticker", "poke", "file", "video", "forward"]

    def __init__(self, adapter: QQAdapter):
        super().__init__(adapter)
        self._metadata = MessageFormatMetadata(
            self._supported_elements, emojis=load_emoji_mapping(Path(__file__).with_name("emoji.json")),
        )

    async def get_message_metadata(self) -> MessageFormatMetadata:
        return MessageFormatMetadata(self._supported_elements, emojis=self._metadata.emojis)

    @staticmethod
    def _extract_poke_texts(msg: Dict) -> tuple[str, str]:
        """Read poke text from NapCat raw_info or OneBot action/suffix fields."""
        # Prefer the original NapCat raw_info fields.
        raw_info = msg.get("raw_info")
        if isinstance(raw_info, list) and len(raw_info) > 4:
            try:
                motion_text = raw_info[2].get("txt") if isinstance(raw_info[2], dict) else None
                object_text = raw_info[4].get("txt") if isinstance(raw_info[4], dict) else None
                if motion_text is not None and object_text is not None:
                    return str(motion_text), str(object_text)
            except Exception:
                pass

        # Fall back to SnowLuma and other OneBot extensions.
        # SnowLuma convertFriendPoke / convertGroupPoke:
        #   action=action_str, suffix=suffix_str
        motion_text = msg.get("action") or msg.get("action_str") or "戳了戳"
        object_text = msg.get("suffix") or msg.get("suffix_str") or ""
        return str(motion_text), str(object_text)

    @staticmethod
    def _sent_result_from_response(response: object, operation: str) -> KiraIMSentResult:
        if not isinstance(response, dict):
            return KiraIMSentResult(None, ok=False, err=f"Failed to {operation}: invalid response {response!r}")
        if response.get("status") != "ok":
            return KiraIMSentResult(None, ok=False, err=f"Failed to {operation}: {response}")

        message_id = (response.get("data") or {}).get("message_id")
        return KiraIMSentResult(str(message_id) if message_id is not None else None)

    @staticmethod
    async def _prepare_media_file(media: File | Video) -> tuple[str, str]:
        if media.file_type == "url":
            file_value = media.file
        else:
            file_value = f"base64://{await media.to_base64()}"
        return file_value, media.name or uuid.uuid4().hex

    async def _send_file(self, target_id, file: File, is_group: bool) -> KiraIMSentResult:
        try:
            file_value, file_name = await self._prepare_media_file(file)
            if is_group:
                response = await self.adapter.bot.upload_group_file(
                    group_id=str(target_id),
                    file=file_value,
                    name=file_name,
                )
            else:
                response = await self.adapter.bot.upload_private_file(
                    user_id=str(target_id),
                    file=file_value,
                    name=file_name,
                )
            return self._sent_result_from_response(response, "upload file")
        except Exception as e:
            return KiraIMSentResult(message_id=None, ok=False, err=f"Error occurred while uploading file: {e}")

    async def _send_video(self, target_id, video: Video, is_group: bool) -> KiraIMSentResult:
        try:
            file_value, file_name = await self._prepare_media_file(video)
            message = [{
                "type": "video",
                "data": {
                    "name": file_name,
                    "file": file_value,
                },
            }]
            if is_group:
                response = await self.adapter.bot.send_group_segments(
                    group_id=target_id,
                    message=message,
                )
            else:
                response = await self.adapter.bot.send_direct_segments(
                    user_id=target_id,
                    message=message,
                )
            return self._sent_result_from_response(response, "send video")
        except Exception as e:
            return KiraIMSentResult(message_id=None, ok=False, err=f"Error occurred while uploading video: {e}")

    async def _send_forward(self, target_id, forward: Forward, is_group: bool) -> KiraIMSentResult:
        try:
            raw_message_ids = forward.message_id
            if raw_message_ids is None:
                return KiraIMSentResult(message_id=None, ok=False, err="Forward message has no message ID")
            message_ids = [raw_message_ids] if isinstance(raw_message_ids, (str, int)) else list(raw_message_ids)
            if not message_ids:
                return KiraIMSentResult(message_id=None, ok=False, err="Forward message has no message ID")

            if forward.merge:
                message = [
                    {"type": "node", "data": {"id": message_id}}
                    for message_id in message_ids
                ]
                if is_group:
                    response = await self.adapter.bot.send_group_segments(
                        group_id=target_id,
                        message=message,
                    )
                else:
                    response = await self.adapter.bot.send_direct_segments(
                        user_id=target_id,
                        message=message,
                    )
            elif len(message_ids) == 1:
                if is_group:
                    response = await self.adapter.bot.forward_group_single_message(
                        group_id=target_id,
                        message_id=message_ids[0],
                    )
                else:
                    response = await self.adapter.bot.forward_direct_single_message(
                        user_id=target_id,
                        message_id=message_ids[0],
                    )
            else:
                self.adapter.logger.warning("Multiple non-merged forwards are not supported")
                return KiraIMSentResult(message_id=None, ok=False, err="Multiple non-merged forwards are not supported")

            return self._sent_result_from_response(response, "forward message")
        except Exception as e:
            return KiraIMSentResult(message_id=None, ok=False, err=f"Error occurred while forwarding message: {e}")

    async def send_group_message(self, group_id: AdapterTargetId, message: MessageChain) -> KiraIMSentResult:
        try:
            message_chain = await self._process_outgoing_message(message)
            if not message_chain:
                self.adapter.logger.warning("处理后的消息链为空，跳过群消息发送")
                return KiraIMSentResult(None, ok=False, err="Empty message chain after processing")
            ele = message_chain[0]
            if isinstance(ele, Poke):
                await self.adapter.bot.send_poke(user_id=ele.pid, group_id=group_id)
                return KiraIMSentResult(message_id=None, is_notice=True)
            elif isinstance(ele, File):
                return await self._send_file(target_id=group_id, file=ele, is_group=True)
            elif isinstance(ele, Video):
                return await self._send_video(target_id=group_id, video=ele, is_group=True)
            elif isinstance(ele, Forward):
                return await self._send_forward(target_id=group_id, forward=ele, is_group=True)

            message_chain = QQMessageChain(message_chain)
            result = await self.adapter.bot.send_group_message(group_id=group_id, msg=message_chain)
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
            message_id = str((result.get("data", {}) or {}).get("message_id"))
            msg_res.message_id = message_id
            return msg_res
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=str(e))

    async def send_direct_message(self, user_id: AdapterTargetId, message: MessageChain) -> KiraIMSentResult:
        msg_res = KiraIMSentResult(None)
        try:
            message_chain = await self._process_outgoing_message(message)
            if not message_chain:
                self.adapter.logger.warning("处理后的消息链为空，跳过私聊消息发送")
                msg_res.ok = False
                msg_res.err = "Empty message chain after processing"
                return msg_res
            ele = message_chain[0]
            if isinstance(ele, Poke):
                await self.adapter.bot.send_poke(user_id=ele.pid)
                msg_res.is_notice = True
                return msg_res
            elif isinstance(ele, File):
                return await self._send_file(target_id=user_id, file=ele, is_group=False)
            elif isinstance(ele, Video):
                return await self._send_video(target_id=user_id, video=ele, is_group=False)
            elif isinstance(ele, Forward):
                return await self._send_forward(target_id=user_id, forward=ele, is_group=False)

            message_chain = QQMessageChain(message_chain)
            result = await self.adapter.bot.send_direct_message(user_id=user_id, msg=message_chain)
            status = result.get("status")
            retcode = result.get("retcode")
            if status == "failed":
                msg_res.ok = False
                msg_res.err = f"未知错误，消息发送失败，错误码：{retcode}"
                return msg_res
            message_id = str((result.get("data", {}) or {}).get("message_id"))
            msg_res.message_id = message_id
        except Exception as e:
            msg_res.ok = False
            msg_res.err = str(e)
        return msg_res

    async def process_incoming_message(self, msg) -> MessageChain:
        """Convert OneBot segments into the shared message format."""
        message_type = msg.get("message_type")
        group_id = msg.get("group_id")

        message_content = []
        for ele in msg.get("message"):
            if ele.get("type") == "text":
                message_content.append(Text(ele.get("data").get("text")))
            elif ele.get("type") == "at":
                at_obj = At(str(ele.get("data").get("qq")))
                if str(ele.get("data").get("qq")) != "all":
                    try:
                        at_user_info = await self.adapter.bot.get_user_info(user_id=str(ele.get("data").get("qq")))
                        at_obj.nickname = at_user_info["data"]["nickname"]
                    except Exception as e:
                        self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
                message_content.append(at_obj)
            elif ele.get("type") == "reply":
                try:
                    reply_content = await self.adapter.bot.get_msg(ele.get("data").get("id"))
                    reply_chain = await self._process_reply_message(reply_content)
                    message_content.append(Reply(ele.get("data").get("id"), chain=reply_chain))
                except Exception as e:
                    self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
            elif ele.get("type") == "face":
                emoji_id = str(ele.get("data").get("id"))
                emoji_desc = self._metadata.emojis.get(emoji_id)
                message_content.append(Emoji(emoji_id, emoji_desc))
            elif ele.get("type") == "image":
                img_url = ele.get("data", {}).get("url", "")

                summary = ele.get("data", {}).get("summary", "")
                sub_type = ele.get("data", {}).get("sub_type", 0)

                if sub_type == 1 or summary == "[动画表情]":
                    try:
                        from core.utils.common_utils import image_to_base64
                        sticker_bs64 = await image_to_base64(img_url)
                        message_content.append(Sticker(sticker=sticker_bs64))
                    except Exception as e:
                        self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
                else:
                    message_content.append(Image(image=img_url))
            elif ele.get("type") == "video":
                try:
                    video_file_name = ele.get("data", {}).get("file", "")  # e.g. xxx.mp4
                    video_file_url = ele.get("data", {}).get("url", "")
                    video_file_size = ele.get("data", {}).get("file_size", "")  # Bytes, str
                    video_obj = Video(file=video_file_url, name=video_file_name, size=video_file_size)
                    message_content.append(video_obj)
                except Exception as e:
                    self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
            elif ele.get("type") == "json":
                json_card_info = ele.get("data", {}).get("data", "")
                card_data = extract_card_info(json_card_info)
                message_content.append(Json(card_data))
            elif ele.get("type") == "file":
                try:
                    file_name = ele.get("data").get("file")
                    file_id = ele.get("data").get("file_id")
                    file_size = ele.get("data").get("file_size")  # Bytes, str

                    if message_type == "group":
                        file_info = await self.adapter.bot.get_group_file_url(group_id=group_id, file_id=file_id)
                        if not file_info:
                            continue
                        file_url = (file_info.get("data", {}) or {}).get("url")
                    elif message_type == "private":
                        file_info = await self.adapter.bot.get_private_file_url(file_id=file_id)
                        if not file_info:
                            continue
                        file_url = (file_info.get("data", {}) or {}).get("url")
                    else:
                        continue

                    if not file_url:
                        message_content.append(Text(f"[File {file_name}]"))
                        continue

                    file_obj = File(file=file_url, name=file_name, size=file_size)
                    message_content.append(file_obj)

                    # file_info = await self.adapter.bot.send_action("get_file", {"file_id": file_id})
                    # file_b64 = file_info.get("data", {}).get("base64")
                except Exception as e:
                    self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")

            elif ele.get("type") == "forward":
                try:
                    forward_message_id = msg.get("message_id")
                    forward_message = await self.adapter.bot.get_forward_msg(forward_message_id)
                    forward_chains = await self._process_forward_message(forward_message)
                    message_content.append(Forward(chains=forward_chains))
                except Exception as e:
                    self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
            elif ele.get("type") == "record":
                try:
                    file_id = ele.get("data").get("file")

                    record_info = await self.adapter.bot.get_record(file_id, output_format="mp3")
                    audio_base64 = record_info.get("data").get("base64")
                    message_content.append(Record(record=audio_base64))
                except Exception as e:
                    self.adapter.logger.error(f"QQ message conversion failed ({type(e).__name__})")
        return MessageChain(message_content)

    def _log_message_summary(self, msg: Dict) -> None:
        """Log structural metadata without persisting message content."""
        segments = msg.get("message")
        count = len(segments) if isinstance(segments, list) else 0
        kind = "notice" if "notice_type" in msg else "message"
        self.adapter.logger.debug(f"QQ inbound {kind}: segments={count}")

    async def _on_notice_message(self, msg: Dict):
        notice_type = msg.get("notice_type")
        sub_type = msg.get("sub_type")
        self_id = msg.get("self_id")
        user_id = msg.get("user_id")
        target_id = msg.get("target_id")
        group_id = msg.get("group_id")

        if group_id:
            if not self.is_allowed(group_id, permission="im.group.receive"):
                return

        timestamp = int(msg.get("time") or time.time())

        if self.adapter.debug_mode:
            if self.adapter.debug_mode_list:
                if f"gm:{group_id}" in self.adapter.debug_mode_list:
                    self._log_message_summary(msg)
                elif not group_id and f"dm:{user_id}" in self.adapter.debug_mode_list:
                    self._log_message_summary(msg)
            else:
                self._log_message_summary(msg)

        group_obj = None
        is_mentioned = False

        if group_id:
            group_info = await self.adapter.bot.get_group_info(group_id=group_id)
            group_name = ((group_info or {}).get("data") or {}).get("group_name") or str(group_id)
            group_obj = Group(
                group_id=str(group_id),
                group_name=group_name
            )

        user_nickname = "None"
        if user_id:
            try:
                user_info = await self.adapter.bot.get_user_info(user_id=user_id)
                user_nickname = user_info.get("data", {}).get("nickname")
            except Exception as _:
                pass

        message_chain = MessageChain()

        # Poke notifications.

        if notice_type == "notify" and sub_type == "poke":
            if not group_id:
                if not self.is_allowed(user_id, permission="im.direct.receive"):
                    return

            # Normalize identifier types used by different OneBot implementations.
            if str(self_id) == str(target_id):
                is_mentioned = True
                # NapCat provides raw_info; SnowLuma provides action and suffix.
                motion_text, object_text = self._extract_poke_texts(msg)

                notice_str = f"[Poke 用户{user_id}({user_nickname}){motion_text}你{object_text}]"
                message_chain.text(notice_str)

        # Build the message event explicitly at the platform boundary.

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            supported_elements=list((await self.get_message_metadata()).supported_elements),
            message=KiraIMMessage(
                timestamp=timestamp,
                message_id="None",
                group=group_obj,
                sender=User(
                    user_id=str(user_id),
                    nickname=user_nickname
                ),
                is_notice=True,
                is_mentioned=is_mentioned,
                self_id=str(self_id),
                chain=message_chain,
                raw_message=msg
            ),
            timestamp=timestamp
        )
        self.publish(message_obj)

    async def _on_group_message(self, msg):
        group_id = str(msg.get("group_id"))
        user_id = str(msg.get("user_id"))

        if not self.is_allowed(msg.get("group_id"), permission="im.group.receive"):
            return

        timestamp = int(msg.get("time") or time.time())

        if self.adapter.debug_mode:
            if self.adapter.debug_mode_list:
                if f"gm:{group_id}" in self.adapter.debug_mode_list:
                    self._log_message_summary(msg)
            else:
                self._log_message_summary(msg)

        is_mentioned = False

        for m in msg.get("message", {}):
            at_id = m.get("data", {}).get("qq", "")
            if m.get("type") == "at" and (at_id == str(msg.get("self_id")) or at_id == "all"):
                is_mentioned = True
                break
            elif m.get("type") == "reply":
                try:
                    reply_msg_info = await self.adapter.bot.get_msg((m.get("data", {}) or {}).get("id", ""))
                except Exception as e:
                    # The quoted message may be absent from the protocol side's
                    # store, never a reason to drop the whole incoming message.
                    self.adapter.logger.warning(f"获取引用消息失败，跳过引用判定: {type(e).__name__}")
                    continue
                if (reply_msg_info.get("data", {}) or {}).get("user_id") == msg.get("self_id"):  # int int
                    is_mentioned = True
                    break

        message_chain = await self.process_incoming_message(msg)

        group_info = await self.adapter.bot.get_group_info(msg.get("group_id"))
        group_name = (group_info.get("data") or {}).get("group_name") or str(group_id)

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            supported_elements=list((await self.get_message_metadata()).supported_elements),
            message=KiraIMMessage(
                timestamp=timestamp,
                group=Group(
                    group_id=group_id,
                    group_name=group_name
                ),
                sender=User(
                    user_id=user_id,
                    nickname=msg.get("sender").get("nickname")
                ),
                is_mentioned=is_mentioned,
                message_id=str(msg.get("message_id")),
                self_id=str(msg.get("self_id")),
                chain=message_chain,
                raw_message=msg
            ),
            timestamp=timestamp
        )
        self.publish(message_obj)

    async def _on_private_message(self, msg: dict):
        user_id = str(msg.get("user_id"))

        if not self.is_allowed(msg.get("user_id"), permission="im.direct.receive"):
            return

        timestamp = int(msg.get("time") or time.time())

        if self.adapter.debug_mode:
            if self.adapter.debug_mode_list:
                if f"dm:{user_id}" in self.adapter.debug_mode_list:
                    self._log_message_summary(msg)
            else:
                self._log_message_summary(msg)

        message_chain = await self.process_incoming_message(msg)

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            supported_elements=list((await self.get_message_metadata()).supported_elements),
            message=KiraIMMessage(
                timestamp=timestamp,
                sender=User(
                    user_id=user_id,
                    nickname=msg.get("sender").get("nickname")
                ),
                message_id=str(msg.get("message_id")),
                is_mentioned=True,
                self_id=str(msg.get("self_id")),
                chain=message_chain,
                raw_message=msg
            ),
            timestamp=timestamp
        )
        self.publish(message_obj)

    async def _process_reply_message(self, message_data):
        if not message_data:
            return MessageChain()

        data = message_data.get("data") or {}
        if not data:
            return MessageChain()

        msg = data
        sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
        ts = msg.get("time", 0)
        dt = datetime.fromtimestamp(ts)
        time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

        inner_elements_chain = await self.process_incoming_message(msg)
        elements_chain = MessageChain().text(f"[{time_str}] {sender}: ")
        elements_chain.extend(inner_elements_chain)
        return elements_chain

    async def _process_forward_message(self, message_data):
        if not message_data:
            self.adapter.logger.warning("处理转发消息时获取到了空消息")
            return
        messages = message_data.get("data", {})
        if messages is None:
            self.adapter.logger.warning("处理转发消息时收到无效数据")
            return

        messages = messages.get("messages", [])

        chains = []
        for msg in messages:
            sender = msg.get("sender", {}).get("nickname", str(msg.get("user_id")))
            ts = msg.get("time", 0)
            dt = datetime.fromtimestamp(ts)  # Format the timestamp for display.
            time_str = dt.strftime("%Y-%m-%d %H:%M:%S")

            elements_chain = MessageChain().text(f"[{time_str}] {sender}: ")
            inner_elements_chain = await self.process_incoming_message(msg)
            elements_chain.extend(inner_elements_chain)
            chains.append(elements_chain)

        return chains

    async def _process_outgoing_message(self, message: MessageChain):
        """Convert shared message elements into OneBot segments."""
        message_chain_elements = []
        for ele in message:
            if isinstance(ele, Text):
                message_chain_elements.append(QQMessageType.Text(ele.text))
            elif isinstance(ele, Emoji):
                if ele.emoji_id in self._metadata.emojis:
                    message_chain_elements.append(QQMessageType.Emoji(int(ele.emoji_id)))
                else:
                    self.adapter.logger.warning(f"未定义的 Emoji ID: {ele.emoji_id}")
            elif isinstance(ele, Sticker):
                sticker_base64 = await ele.to_base64()
                message_chain_elements.append(
                    QQMessageType.Sticker(
                        ele.sticker_id or "",
                        f"base64://{sticker_base64}",
                    )
                )
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
