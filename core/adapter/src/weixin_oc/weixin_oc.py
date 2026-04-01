from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import time
import uuid
from pathlib import Path
from typing import Any, cast
from urllib.parse import quote

import qrcode as qrcode_lib

from core.adapter.adapter_utils import IMAdapter
from core.logging_manager import get_logger
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult
from core.chat.message_elements import (
    Text,
    Image,
    File,
    Video,
    Record,
    Emoji,
    Sticker,
)
from core.chat import User
from core.utils.path_utils import get_data_path

from .weixin_oc_client import WeixinOCClient


class OpenClawLoginSession:
    """登录会话状态"""
    def __init__(
        self,
        session_key: str,
        qrcode: str,
        qrcode_img_content: str,
        started_at: float,
    ):
        self.session_key = session_key
        self.qrcode = qrcode
        self.qrcode_img_content = qrcode_img_content
        self.started_at = started_at
        self.status = "wait"
        self.bot_token = None
        self.account_id = None
        self.base_url = None
        self.user_id = None
        self.error = None


class TypingSessionState:
    """输入状态会话"""
    def __init__(self):
        self.ticket = None
        self.ticket_context_token = None
        self.refresh_after = 0.0
        self.keepalive_task = None
        self.cancel_task = None
        self.owners = set()
        self.lock = asyncio.Lock()


class WeixinOCAdapter(IMAdapter):
    """
    微信个人号适配器（基于 OpenClaw API）
    
    注意：个人微信不支持群聊，只能发送私聊消息
    """
    
    IMAGE_ITEM_TYPE = 2
    VOICE_ITEM_TYPE = 3
    FILE_ITEM_TYPE = 4
    VIDEO_ITEM_TYPE = 5
    IMAGE_UPLOAD_TYPE = 1
    VIDEO_UPLOAD_TYPE = 2
    FILE_UPLOAD_TYPE = 3

    def __init__(self, info, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue, llm_api):
        super().__init__(info, loop, event_bus, llm_api)
        self.message_types = ["text", "image", "video", "file", "record"]
        self.logger = get_logger(info.name, "green")
        
        self.base_url = str(
            self.config.get("weixin_oc_base_url", "https://ilinkai.weixin.qq.com")
        ).rstrip("/")
        self.cdn_base_url = str(
            self.config.get(
                "weixin_oc_cdn_base_url",
                "https://novac2c.cdn.weixin.qq.com/c2c",
            )
        ).rstrip("/")
        self.bot_type = str(self.config.get("weixin_oc_bot_type", "3"))
        self.api_timeout_ms = int(self.config.get("weixin_oc_api_timeout_ms", 15000))
        self.long_poll_timeout_ms = int(
            self.config.get("weixin_oc_long_poll_timeout_ms", 35000)
        )
        self.qr_poll_interval = max(1, int(self.config.get("weixin_oc_qr_poll_interval", 1)))
        
        self._shutdown_event = asyncio.Event()
        self._login_session: OpenClawLoginSession | None = None
        self._sync_buf = ""
        self._qr_expired_count = 0
        self._context_tokens: dict[str, str] = {}
        self._typing_states: dict[str, TypingSessionState] = {}
        self._last_inbound_error = ""
        self._typing_keepalive_interval_s = max(
            1, int(self.config.get("weixin_oc_typing_keepalive_interval", 5))
        )
        self._typing_ticket_ttl_s = max(
            5, int(self.config.get("weixin_oc_typing_ticket_ttl", 60))
        )
        
        self.token = str(self.config.get("weixin_oc_token", "")).strip() or None
        self.account_id = str(self.config.get("weixin_oc_account_id", "")).strip() or None
        self._sync_buf = str(self.config.get("weixin_oc_sync_buf", "")).strip()
        
        self.client = WeixinOCClient(
            adapter_id=self.info.name,
            base_url=self.base_url,
            cdn_base_url=self.cdn_base_url,
            api_timeout_ms=self.api_timeout_ms,
            token=self.token,
        )
        
        if self.token:
            self.logger.info("weixin_oc adapter loaded with existing token")
        else:
            self.logger.info("weixin_oc adapter initialized, waiting for QR login")

    def _sync_client_state(self) -> None:
        self.client.base_url = self.base_url
        self.client.cdn_base_url = self.cdn_base_url
        self.client.api_timeout_ms = self.api_timeout_ms
        self.client.token = self.token

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
        raw_bytes = media_path.read_bytes()
        raw_size = len(raw_bytes)
        raw_md5 = hashlib.md5(raw_bytes).hexdigest()
        file_key = uuid.uuid4().hex
        aes_key_hex = uuid.uuid4().bytes.hex()
        ciphertext_size = self.client.aes_padded_size(raw_size)

        payload = await self.client.request_json(
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
            timeout_ms=self.api_timeout_ms,
        )
        self.logger.debug(
            "weixin_oc(%s): getuploadurl response user=%s media_type=%s raw_size=%s",
            self.info.name,
            user_id,
            upload_media_type,
            raw_size,
        )
        upload_param = str(payload.get("upload_param", "")).strip()
        upload_full_url = str(payload.get("upload_full_url", "")).strip()

        encrypted_query_param = await self.client.upload_to_cdn(
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
                content = await self.client.download_and_decrypt_media(
                    encrypted_query_param, aes_key_value
                )
            else:
                content = await self.client.download_cdn_bytes(encrypted_query_param)
            image_path = self._save_temp_media(
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
            content = await self.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            video_path = self._save_temp_media(
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
            content = await self.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            file_path = self._save_temp_media(
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
            content = await self.client.download_and_decrypt_media(
                encrypted_query_param, aes_key_value
            )
            voice_path = self._save_temp_media(
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
                self.logger.warning(
                    "weixin_oc(%s): resolve inbound media failed: %s",
                    self.info.name,
                    e,
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
        from_user_id = str(msg.get("from_user_id", "")).strip()
        if not from_user_id:
            self.logger.debug("weixin_oc: skip message with empty from_user_id")
            return

        # 权限检查
        should_process = False
        if self.permission_mode == "allow_list":
            if str(from_user_id) in self.user_list:
                should_process = True
        elif self.permission_mode == "deny_list":
            if str(from_user_id) not in self.user_list:
                should_process = True
        
        if not should_process:
            return

        context_token = str(msg.get("context_token", "")).strip()
        if context_token:
            self._context_tokens[from_user_id] = context_token

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
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=ts,
                message_id=message_id,
                sender=User(user_id=from_user_id, nickname=from_user_id),
                is_mentioned=True,
                self_id=self.account_id or "",
                chain=MessageChain(components),
                extra=msg,
            ),
            timestamp=ts,
        )
        self.publish(message_obj)

    async def _poll_inbound_updates(self) -> None:
        data = await self.client.request_json(
            "POST",
            "ilink/bot/getupdates",
            payload={
                "base_info": {
                    "channel_version": "kiraai",
                },
                "get_updates_buf": self._sync_buf,
            },
            token_required=True,
            timeout_ms=self.long_poll_timeout_ms,
        )
        ret = int(data.get("ret") or 0)
        errcode = data.get("errcode", 0)
        if ret != 0 and ret is not None:
            errmsg = str(data.get("errmsg", ""))
            self._last_inbound_error = f"ret={ret}, errcode={errcode}, errmsg={errmsg}"
            self.logger.warning(
                "weixin_oc(%s): getupdates error: %s",
                self.info.name,
                self._last_inbound_error,
            )
            return
        if errcode and int(errcode) != 0:
            errmsg = str(data.get("errmsg", ""))
            self._last_inbound_error = f"ret={ret}, errcode={errcode}, errmsg={errmsg}"
            # 会话超时(errcode=-14)需要重新登录
            if int(errcode) == -14:
                self.logger.warning(
                    "weixin_oc(%s): session timeout, clearing token for re-login",
                    self.info.name,
                )
                self.token = None
                self._sync_buf = ""
                self._context_tokens.clear()
                self._login_session = None
                await self._save_account_state()
                return
            self.logger.warning(
                "weixin_oc(%s): getupdates error: %s",
                self.info.name,
                self._last_inbound_error,
            )
            return

        if data.get("get_updates_buf"):
            self._sync_buf = str(data.get("get_updates_buf"))
            # sync_buf 只在内存中更新，不需要每次都持久化

        for msg in data.get("msgs", []) if isinstance(data.get("msgs"), list) else []:
            if self._shutdown_event.is_set():
                return
            if not isinstance(msg, dict):
                continue
            await self._handle_inbound_message(msg)

    async def _send_items_to_session(
        self,
        user_id: str,
        item_list: list[dict[str, Any]],
    ) -> bool:
        if not self.token:
            self.logger.warning("weixin_oc(%s): missing token, skip send", self.info.name)
            return False
        if not item_list:
            self.logger.warning("weixin_oc(%s): empty message payload ignored", self.info.name)
            return False
        context_token = self._context_tokens.get(user_id)
        if not context_token:
            self.logger.warning(
                "weixin_oc(%s): context token missing for %s, skip send",
                self.info.name,
                user_id,
            )
            return False
        await self.client.request_json(
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
        self, segment: Image | Video | File
    ) -> Path | None:
        try:
            path = await segment.to_path()
        except Exception as e:
            self.logger.warning(
                "weixin_oc(%s): media resolve failed: %s",
                self.info.name,
                e
            )
            return None

        if not path:
            return None
        media_path = Path(path)
        if not media_path.exists() or not media_path.is_file():
            return None
        return media_path

    async def _send_media_segment(
        self,
        user_id: str,
        segment: Image | Video | File,
        text: str | None = None,
    ) -> bool:
        if not self.token:
            self.logger.warning(
                "weixin_oc(%s): missing token, skip media send",
                self.info.name
            )
            return False
        media_path = await self._resolve_media_file_path(segment)
        if media_path is None:
            self.logger.warning(
                "weixin_oc(%s): skip media segment, file not resolvable",
                self.info.name,
            )
            return False

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
            self.logger.error(
                "weixin_oc(%s): prepare media failed: %s",
                self.info.name,
                e
            )
            return False

        if text:
            await self._send_items_to_session(
                user_id,
                [self._build_plain_text_item(text)],
            )
        return await self._send_items_to_session(user_id, [media_item])

    async def _send_text_message(
        self, user_id: str, text: str
    ) -> bool:
        if not text:
            self.logger.warning(
                "weixin_oc(%s): empty text message ignored",
                self.info.name,
            )
            return False
        return await self._send_items_to_session(
            user_id,
            [self._build_plain_text_item(text)],
        )

    async def _start_login_session(self) -> OpenClawLoginSession:
        endpoint = "ilink/bot/get_bot_qrcode"
        params = {"bot_type": self.bot_type}
        self.logger.info("weixin_oc(%s): requesting QR code from %s", self.info.name, endpoint)
        data = await self.client.request_json(
            "GET",
            endpoint,
            params=params,
            token_required=False,
            timeout_ms=15_000,
        )
        qrcode = str(data.get("qrcode", "")).strip()
        qrcode_url = str(data.get("qrcode_img_content", "")).strip()
        if not qrcode or not qrcode_url:
            raise RuntimeError("qrcode response missing qrcode or qrcode_img_content")
        qr_console_url = (
            f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data="
            f"{quote(qrcode_url)}"
        )
        self.logger.info(
            "weixin_oc(%s): QR session started, qr_link=%s 请使用手机微信扫码登录",
            self.info.name,
            qr_console_url,
        )
        try:
            qr = qrcode_lib.QRCode(border=1)
            qr.add_data(qrcode_url)
            qr.make(fit=True)
            qr_buffer = io.StringIO()
            qr.print_ascii(out=qr_buffer, tty=False)
            self.logger.info(
                "weixin_oc(%s): terminal QR code:\n%s",
                self.info.name,
                qr_buffer.getvalue(),
            )
        except Exception as e:
            self.logger.warning(
                "weixin_oc(%s): failed to render terminal QR code: %s",
                self.info.name,
                e,
            )
        login_session = OpenClawLoginSession(
            session_key=str(uuid.uuid4()),
            qrcode=qrcode,
            qrcode_img_content=qrcode_url,
            started_at=time.time(),
        )
        self._login_session = login_session
        self._qr_expired_count = 0
        self._last_inbound_error = ""
        return login_session

    async def _poll_qr_status(self, login_session: OpenClawLoginSession) -> None:
        endpoint = "ilink/bot/get_qrcode_status"
        self.logger.debug("weixin_oc(%s): polling qrcode status", self.info.name)
        data = await self.client.request_json(
            "GET",
            endpoint,
            params={"qrcode": login_session.qrcode},
            token_required=False,
            timeout_ms=self.long_poll_timeout_ms,
            headers={"iLink-App-ClientVersion": "1"},
        )
        status = str(data.get("status", "wait")).strip()
        login_session.status = status
        if status == "expired":
            self._qr_expired_count += 1
            if self._qr_expired_count > 3:
                login_session.error = "二维码已过期，超过重试次数"
                self._login_session = None
                return
            self.logger.warning(
                "weixin_oc(%s): qr expired, refreshing (%s/3)",
                self.info.name,
                self._qr_expired_count,
            )
            new_session = await self._start_login_session()
            self._login_session = new_session
            return

        if status == "confirmed":
            bot_token = data.get("bot_token")
            account_id = data.get("ilink_bot_id")
            base_url = data.get("baseurl")
            user_id = data.get("ilink_user_id")
            if not bot_token:
                login_session.error = "登录成功但未返回 bot_token"
                return
            login_session.bot_token = str(bot_token)
            login_session.account_id = str(account_id) if account_id else None
            login_session.base_url = str(base_url) if base_url else self.base_url
            login_session.user_id = str(user_id) if user_id else None
            self.token = login_session.bot_token
            self.account_id = login_session.account_id
            if login_session.base_url:
                self.base_url = login_session.base_url.rstrip("/")
            await self._save_account_state()
            self.logger.info(
                "weixin_oc(%s): login confirmed, account=%s",
                self.info.name,
                self.account_id or "",
            )

    def _is_login_session_valid(
        self, login_session: OpenClawLoginSession | None
    ) -> bool:
        if not login_session:
            return False
        return (time.time() - login_session.started_at) * 1000 < 5 * 60_000

    async def _save_account_state(self) -> None:
        """保存登录状态到配置文件"""
        try:
            # 更新内存中的配置
            self.info.config["weixin_oc_token"] = self.token or ""
            self.info.config["weixin_oc_account_id"] = self.account_id or ""
            self.info.config["weixin_oc_sync_buf"] = self._sync_buf
            self.info.config["weixin_oc_base_url"] = self.base_url
            
            # 保存到配置文件
            from core.config.config_loader import KiraConfig
            kira_config = KiraConfig()
            adapters = kira_config.get("adapters", {})
            if self.info.adapter_id in adapters:
                adapters[self.info.adapter_id]["config"] = dict(self.info.config)
                kira_config.save_config()
                self.logger.info("weixin_oc(%s): account state saved", self.info.name)
            else:
                self.logger.warning("weixin_oc(%s): adapter not found in config", self.info.name)
        except Exception as e:
            self.logger.error("weixin_oc(%s): failed to save account state: %s", self.info.name, e)
        self._sync_client_state()

    async def start(self):
        asyncio.create_task(self._run_loop())

    async def _run_loop(self) -> None:
        try:
            while not self._shutdown_event.is_set():
                if not self.token:
                    if not self._is_login_session_valid(self._login_session):
                        try:
                            self._login_session = await self._start_login_session()
                            self._qr_expired_count = 0
                        except Exception as e:
                            self.logger.error(
                                "weixin_oc(%s): start login failed: %s",
                                self.info.name,
                                e,
                            )
                            await asyncio.sleep(5)
                            continue

                    current_login = self._login_session
                    if current_login is None:
                        continue

                    try:
                        await self._poll_qr_status(current_login)
                    except asyncio.TimeoutError:
                        self.logger.debug(
                            "weixin_oc(%s): qr status long-poll timeout",
                            self.info.name,
                        )
                    except Exception as e:
                        self.logger.error(
                            "weixin_oc(%s): poll qr status failed: %s",
                            self.info.name,
                            e,
                        )
                        current_login.error = str(e)
                        await asyncio.sleep(2)

                    if self.token:
                        continue

                    if current_login.error:
                        await asyncio.sleep(2)
                    else:
                        await asyncio.sleep(self.qr_poll_interval)
                    continue

                try:
                    await self._poll_inbound_updates()
                except asyncio.TimeoutError:
                    self.logger.debug(
                        "weixin_oc(%s): inbound long-poll timeout",
                        self.info.name,
                    )
                except Exception as e:
                    self.logger.error(
                        "weixin_oc(%s): poll inbound failed, retry in 5s: %s",
                        self.info.name,
                        e,
                    )
                    await asyncio.sleep(5)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.logger.exception("weixin_oc(%s): run loop failed: %s", self.info.name, e)
        finally:
            await self.client.close()

    async def stop(self):
        self._shutdown_event.set()
        await self.client.close()
        self.logger.info("weixin_oc(%s): adapter stopped", self.info.name)

    def get_client(self) -> WeixinOCClient:
        return self.client

    async def send_group_message(
        self, group_id, send_message_obj: MessageChain
    ) -> KiraIMSentResult:
        """
        微信个人号不支持群聊消息发送
        """
        self.logger.warning(
            "weixin_oc(%s): 个人微信不支持群聊消息发送",
            self.info.name,
        )
        return KiraIMSentResult(
            message_id=None,
            ok=False,
            err="个人微信不支持群聊消息",
        )

    async def send_direct_message(
        self, user_id, send_message_obj: MessageChain
    ) -> KiraIMSentResult:
        """
        发送私聊消息
        
        支持文本、图片、视频、文件
        """
        msg_res = KiraIMSentResult(None)
        
        if not self.token:
            msg_res.ok = False
            msg_res.err = "未登录，请先扫码登录"
            return msg_res
        
        pending_text = ""
        has_sent = False
        
        for segment in send_message_obj:
            if isinstance(segment, Text):
                pending_text += segment.text
                continue

            if isinstance(segment, (Image, Video, File, Sticker)):
                try:
                    success = await self._send_media_segment(
                        str(user_id),
                        segment,
                        text=pending_text.strip() or None,
                    )
                    if success:
                        has_sent = True
                    pending_text = ""
                except Exception as e:
                    msg_res.ok = False
                    msg_res.err = str(e)
                    return msg_res
                continue
            
            # Emoji 转换为文本发送
            if isinstance(segment, Emoji):
                if segment.emoji_desc:
                    pending_text += segment.emoji_desc
                continue

            self.logger.debug(
                "weixin_oc(%s): unsupported outbound segment type %s",
                self.info.name,
                type(segment).__name__,
            )

        if pending_text.strip():
            try:
                success = await self._send_text_message(str(user_id), pending_text.strip())
                if success:
                    has_sent = True
            except Exception as e:
                msg_res.ok = False
                msg_res.err = str(e)
                return msg_res

        if not has_sent:
            msg_res.ok = False
            msg_res.err = "没有可发送的消息内容"
        
        return msg_res
