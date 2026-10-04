from __future__ import annotations

import asyncio
import base64
import hashlib
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from core.adapter.base import AdapterTargetId
from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult, User
from core.chat.message_elements import Text, Image, File, Video, Record, Emoji, Sticker
from core.utils.path_utils import get_data_path

if TYPE_CHECKING:
    from .weixin_oc import WeixinOCAdapter


class WeixinOCIMCapability(IMCapability["WeixinOCAdapter"]):
    """Convert, receive and send messages for one personal WeChat account."""

    _SUPPORTED_ELEMENTS = ["text", "image", "video", "file", "record"]

    async def get_message_metadata(self) -> MessageFormatMetadata:
        return MessageFormatMetadata(self._supported_elements)

    IMAGE_ITEM_TYPE = 2
    VOICE_ITEM_TYPE = 3
    FILE_ITEM_TYPE = 4
    VIDEO_ITEM_TYPE = 5
    IMAGE_UPLOAD_TYPE = 1
    VIDEO_UPLOAD_TYPE = 2
    FILE_UPLOAD_TYPE = 3

    def _resolve_temp_dir(self) -> Path:
        temp_dir = Path(get_data_path()) / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @staticmethod
    def _normalize_filename(file_name: str, fallback_name: str) -> str:
        normalized = Path(file_name or "").name.strip()
        return normalized or fallback_name

    def _save_temp_media(
        self,
        content: bytes,
        *,
        prefix: str,
        file_name: str,
        fallback_suffix: str,
    ) -> Path:
        normalized_name = self._normalize_filename(file_name, f"{prefix}{fallback_suffix}")
        stem = Path(normalized_name).stem or prefix
        suffix = Path(normalized_name).suffix or fallback_suffix
        target = (
            self._resolve_temp_dir()
            / f"{prefix}_{uuid.uuid4().hex[:8]}_{stem}{suffix}"
        )
        target.write_bytes(content)
        return target

    @staticmethod
    def _build_plain_text_item(text: str) -> dict[str, Any]:
        return {
            "type": 1,
            "text_item": {
                "text": text,
            },
        }

    async def _prepare_media_item(
        self,
        user_id: str,
        media_path: Path,
        upload_media_type: int,
        item_type: int,
        file_name: str,
    ) -> dict[str, Any]:
        raw_bytes = await asyncio.to_thread(media_path.read_bytes)
        raw_size = len(raw_bytes)
        raw_md5 = await asyncio.to_thread(lambda: hashlib.md5(raw_bytes).hexdigest())
        file_key = uuid.uuid4().hex
        aes_key_hex = uuid.uuid4().bytes.hex()
        ciphertext_size = self.adapter.client.aes_padded_size(raw_size)

        payload = await self.adapter.client.request_json(
            "POST",
            "ilink/bot/getuploadurl",
            payload={
                "filekey": file_key,
                "media_type": upload_media_type,
                "to_user_id": user_id,
                "rawsize": raw_size,
                "rawfilemd5": raw_md5,
                "filesize": ciphertext_size,
                "no_need_thumb": True,
                "aeskey": aes_key_hex,
                "base_info": {
                    "channel_version": "kiraai",
                },
            },
            token_required=True,
            timeout_ms=self.adapter.api_timeout_ms,
        )
        self.adapter.logger.debug(
            "weixin_oc(%s): getuploadurl response user=%s media_type=%s raw_size=%s",
            self.adapter.info.name,
            user_id,
            upload_media_type,
            raw_size,
        )
        upload_param = str(payload.get("upload_param", "")).strip()
        upload_full_url = str(payload.get("upload_full_url", "")).strip()

        encrypted_query_param = await self.adapter.client.upload_to_cdn(
            upload_full_url,
            upload_param,
            file_key,
            aes_key_hex,
            media_path,
        )

        aes_key_b64 = base64.b64encode(aes_key_hex.encode("utf-8")).decode("utf-8")
        media_payload = {
            "encrypt_query_param": encrypted_query_param,
            "aes_key": aes_key_b64,
            "encrypt_type": 1,
        }

        if item_type == self.IMAGE_ITEM_TYPE:
            return {
                "type": self.IMAGE_ITEM_TYPE,
                "image_item": {
                    "media": media_payload,
                    "mid_size": ciphertext_size,
                },
            }
        if item_type == self.VIDEO_ITEM_TYPE:
            return {
                "type": self.VIDEO_ITEM_TYPE,
                "video_item": {
                    "media": media_payload,
                    "video_size": ciphertext_size,
                },
            }

        return {
            "type": self.FILE_ITEM_TYPE,
            "file_item": {
                "media": media_payload,
                "file_name": file_name,
                "len": str(raw_size),
            },
        }

    async def _resolve_inbound_media(
        self,
        item: dict[str, Any],
    ) -> Image | Video | File | Record | None:
        item_type = int(item.get("type") or 0)

        if item_type == self.IMAGE_ITEM_TYPE:
            image_item = cast(dict[str, Any], item.get("image_item", {}) or {})
            media = cast(dict[str, Any], image_item.get("media", {}) or {})
            encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
            if not encrypted_query_param:
                return None
            image_aes_key = str(image_item.get("aeskey", "")).strip()
            if image_aes_key:
                aes_key_value = base64.b64encode(bytes.fromhex(image_aes_key)).decode("utf-8")
            else:
                aes_key_value = str(media.get("aes_key", "")).strip()
            if aes_key_value:
                content = await self.adapter.client.download_and_decrypt_media(
                    encrypted_query_param, aes_key_value
                )
            else:
                content = await self.adapter.client.download_cdn_bytes(encrypted_query_param)
            image_path = await asyncio.to_thread(
                self._save_temp_media,
                content,
                prefix="weixin_img",
                file_name="image.jpg",
                fallback_suffix=".jpg",
            )
            return Image(image=str(image_path))

        if item_type == self.VIDEO_ITEM_TYPE:
            video_item = cast(dict[str, Any], item.get("video_item", {}) or {})
            media = cast(dict[str, Any], video_item.get("media", {}) or {})
            encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
            aes_key_value = str(media.get("aes_key", "")).strip()
            if not encrypted_query_param or not aes_key_value:
                return None
            content = await self.adapter.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            video_path = await asyncio.to_thread(
                self._save_temp_media,
                content,
                prefix="weixin_video",
                file_name="video.mp4",
                fallback_suffix=".mp4",
            )
            return Video(file=str(video_path))

        if item_type == self.FILE_ITEM_TYPE:
            file_item = cast(dict[str, Any], item.get("file_item", {}) or {})
            media = cast(dict[str, Any], file_item.get("media", {}) or {})
            encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
            aes_key_value = str(media.get("aes_key", "")).strip()
            if not encrypted_query_param or not aes_key_value:
                return None
            file_name = self._normalize_filename(
                str(file_item.get("file_name", "")).strip(), "file.bin"
            )
            content = await self.adapter.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            file_path = await asyncio.to_thread(
                self._save_temp_media,
                content,
                prefix="weixin_file",
                file_name=file_name,
                fallback_suffix=".bin",
            )
            return File(file=str(file_path), name=file_name)

        if item_type == self.VOICE_ITEM_TYPE:
            voice_item = cast(dict[str, Any], item.get("voice_item", {}) or {})
            media = cast(dict[str, Any], voice_item.get("media", {}) or {})
            encrypted_query_param = str(media.get("encrypt_query_param", "")).strip()
            aes_key_value = str(media.get("aes_key", "")).strip()
            if not encrypted_query_param or not aes_key_value:
                return None
            content = await self.adapter.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            voice_path = await asyncio.to_thread(
                self._save_temp_media,
                content,
                prefix="weixin_voice",
                file_name="voice.silk",
                fallback_suffix=".silk",
            )
            return Record(record=str(voice_path))

        return None

    async def _item_list_to_components(
        self, item_list: list[dict[str, Any]] | None
    ) -> list[Any]:
        if not item_list:
            return []
        parts: list[Any] = []
        for item in item_list:
            item_type = int(item.get("type") or 0)
            if item_type == 1:
                text = str(item.get("text_item", {}).get("text", "")).strip()
                if text:
                    parts.append(Text(text))
                continue
            try:
                media_component = await self._resolve_inbound_media(item)
            except Exception as e:
                self.adapter.logger.warning(
                    "weixin_oc(%s): resolve inbound media failed: %s",
                    self.adapter.info.name,
                    type(e).__name__,
                )
                media_component = None
            if media_component is not None:
                parts.append(media_component)
        return parts

    def _message_text_from_item_list(
        self, item_list: list[dict[str, Any]] | None
    ) -> str:
        if not item_list:
            return ""
        text_parts: list[str] = []
        for item in item_list:
            item_type = int(item.get("type") or 0)
            if item_type == 1:
                text = str(item.get("text_item", {}).get("text", "")).strip()
                if text:
                    text_parts.append(text)
            elif item_type == 2:
                text_parts.append("[图片]")
            elif item_type == 3:
                voice_text = str(item.get("voice_item", {}).get("text", "")).strip()
                if voice_text:
                    text_parts.append(voice_text)
                else:
                    text_parts.append("[语音]")
            elif item_type == 4:
                text_parts.append("[文件]")
            elif item_type == 5:
                text_parts.append("[视频]")
        return "\n".join(text_parts).strip()

    async def _handle_inbound_message(self, msg: dict[str, Any]) -> None:
        sender_id = msg.get("from_user_id")
        from_user_id = str(sender_id).strip() if sender_id is not None else ""
        if not from_user_id:
            self.adapter.logger.debug("weixin_oc: skip message with empty from_user_id")
            return

        if not self.is_allowed(from_user_id, permission="im.direct.receive"):
            return

        context_token = str(msg.get("context_token", "")).strip()
        if context_token:
            self.adapter._context_tokens[from_user_id] = context_token

        item_list = cast(list[dict[str, Any]], msg.get("item_list", []))
        components = await self._item_list_to_components(item_list)
        text = self._message_text_from_item_list(item_list)
        message_id = str(msg.get("message_id") or msg.get("msg_id") or uuid.uuid4().hex)
        create_time = msg.get("create_time_ms") or msg.get("create_time")
        if isinstance(create_time, (int, float)) and create_time > 1_000_000_000_000:
            ts = int(float(create_time) / 1000)
        elif isinstance(create_time, (int, float)):
            ts = int(create_time)
        else:
            ts = int(time.time())

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            supported_elements=list((await self.get_message_metadata()).supported_elements),
            message=KiraIMMessage(
                timestamp=ts,
                message_id=message_id,
                sender=User(user_id=from_user_id, nickname=from_user_id),
                is_mentioned=True,
                self_id=self.adapter.account_id or "",
                chain=MessageChain(components),
                extra=msg,
            ),
            timestamp=ts,
        )
        self.publish(message_obj)

    async def _send_items_to_session(
        self,
        user_id: str,
        item_list: list[dict[str, Any]],
    ) -> bool:
        if not self.adapter.token:
            self.adapter.logger.warning("weixin_oc(%s): missing token, skip send", self.adapter.info.name)
            return False
        if not item_list:
            self.adapter.logger.warning("weixin_oc(%s): empty message payload ignored", self.adapter.info.name)
            return False
        context_token = self.adapter._context_tokens.get(user_id)
        if not context_token:
            self.adapter.logger.warning(
                "weixin_oc(%s): context token missing for %s, skip send",
                self.adapter.info.name,
                user_id,
            )
            return False
        await self.adapter.client.request_json(
            "POST",
            "ilink/bot/sendmessage",
            payload={
                "base_info": {
                    "channel_version": "kiraai",
                },
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": uuid.uuid4().hex,
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": item_list,
                },
            },
            token_required=True,
            headers={},
        )
        return True

    async def _resolve_media_file_path(
        self, segment: Image | Video | File | Sticker
    ) -> Path | None:
        try:
            path = await segment.to_path()
        except Exception as e:
            self.adapter.logger.warning(
                "weixin_oc(%s): media resolve failed: %s",
                self.adapter.info.name,
                type(e).__name__,
            )
            return None

        if not path:
            return None
        media_path = Path(path)
        if not await asyncio.to_thread(media_path.is_file):
            return None
        return media_path

    async def _send_media_segment(
        self,
        user_id: str,
        segment: Image | Video | File | Sticker,
        text: str | None = None,
    ) -> tuple[bool, bool]:
        """Return (text_sent, media_sent) as independent send outcomes."""
        if not self.adapter.token:
            self.adapter.logger.warning(
                "weixin_oc(%s): missing token, skip media send",
                self.adapter.info.name
            )
            return False, False
        media_path = await self._resolve_media_file_path(segment)
        if media_path is None:
            self.adapter.logger.warning(
                "weixin_oc(%s): skip media segment, file not resolvable",
                self.adapter.info.name,
            )
            return False, False

        item_type = self.IMAGE_ITEM_TYPE
        upload_media_type = self.IMAGE_UPLOAD_TYPE
        if isinstance(segment, Video):
            item_type = self.VIDEO_ITEM_TYPE
            upload_media_type = self.VIDEO_UPLOAD_TYPE
        elif isinstance(segment, File):
            item_type = self.FILE_ITEM_TYPE
            upload_media_type = self.FILE_UPLOAD_TYPE

        file_name = (
            segment.name
            if isinstance(segment, File) and segment.name
            else media_path.name
        )
        try:
            media_item = await self._prepare_media_item(
                user_id,
                media_path,
                upload_media_type,
                item_type,
                file_name,
            )
        except Exception as e:
            self.adapter.logger.error(
                "weixin_oc(%s): prepare media failed: %s",
                self.adapter.info.name,
                type(e).__name__,
            )
            return False, False

        text_sent = False
        if text:
            text_sent = await self._send_items_to_session(
                user_id,
                [self._build_plain_text_item(text)],
            )
        media_sent = await self._send_items_to_session(user_id, [media_item])
        return text_sent, media_sent

    async def _send_text_message(
        self, user_id: str, text: str
    ) -> bool:
        if not text:
            self.adapter.logger.warning(
                "weixin_oc(%s): empty text message ignored",
                self.adapter.info.name,
            )
            return False
        return await self._send_items_to_session(
            user_id,
            [self._build_plain_text_item(text)],
        )

    async def send_group_message(
        self, group_id: AdapterTargetId, message: MessageChain
    ) -> KiraIMSentResult:
        """Report that personal WeChat does not support group messages."""
        self.adapter.logger.warning(
            "weixin_oc(%s): 个人微信不支持群聊消息发送",
            self.adapter.info.name,
        )
        return KiraIMSentResult(
            message_id=None,
            ok=False,
            err="个人微信不支持群聊消息",
        )

    async def send_direct_message(
        self, user_id: AdapterTargetId, message: MessageChain
    ) -> KiraIMSentResult:
        """Send text, images, videos and files to a direct session."""
        msg_res = KiraIMSentResult(None)

        if not self.adapter.token:
            msg_res.ok = False
            msg_res.err = "未登录，请先在 WebUI 配置中扫码登录"
            return msg_res

        pending_text = ""
        has_sent = False

        for segment in message:
            if isinstance(segment, Text):
                pending_text += segment.text
                continue

            if isinstance(segment, (Image, Video, File, Sticker)):
                try:
                    text_sent, media_sent = await self._send_media_segment(
                        str(user_id),
                        segment,
                        text=pending_text.strip() or None,
                    )
                    if text_sent or media_sent:
                        has_sent = True
                    if text_sent:
                        pending_text = ""
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = type(e).__name__
                    return msg_res
                continue

            # Send emoji descriptions as text.
            if isinstance(segment, Emoji):
                if segment.emoji_desc:
                    pending_text += segment.emoji_desc
                continue

            self.adapter.logger.debug(
                "weixin_oc(%s): unsupported outbound segment type %s",
                self.adapter.info.name,
                type(segment).__name__,
            )

        if pending_text.strip():
            try:
                success = await self._send_text_message(str(user_id), pending_text.strip())
                if success:
                    has_sent = True
            except Exception as e:
                msg_res.ok = False
                msg_res.err = type(e).__name__
                return msg_res

        if not has_sent:
            msg_res.ok = False
            msg_res.err = "没有可发送的消息内容"

        return msg_res
