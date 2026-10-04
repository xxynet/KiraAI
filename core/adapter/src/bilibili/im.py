from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from bilibili_api.session import Event
from bilibili_api.user import User as BiliUser
from bilibili_api.video import Video as BiliVideo

from core.adapter.base import AdapterTargetId
from core.adapter.capabilities import IMCapability
from core.adapter.message_format_metadata import MessageFormatMetadata, load_emoji_mapping
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult, User
from core.chat.message_elements import Text, Image, Emoji

if TYPE_CHECKING:
    from .bilibili import BiliBiliAdapter


class BiliBiliIMCapability(IMCapability["BiliBiliAdapter"]):
    """Receive and send Bilibili private messages using the account's resources."""

    _SUPPORTED_ELEMENTS = ["text", "img", "at", "reply", "emoji", "share_video"]

    def __init__(self, adapter: BiliBiliAdapter):
        super().__init__(adapter)
        self._metadata = MessageFormatMetadata(
            self._supported_elements, emojis=load_emoji_mapping(Path(__file__).with_name("emoji.json")),
        )

    async def get_message_metadata(self) -> MessageFormatMetadata:
        return MessageFormatMetadata(self._supported_elements, emojis=self._metadata.emojis)

    # ===== User info cache =====
    async def _get_user_nickname(self, uid: int) -> str:
        """Fetch BiliBili user nickname via User().get_user_info(), with in-memory cache."""
        uid_int = int(uid)
        if uid_int in self.adapter._user_info_cache:
            return self.adapter._user_info_cache[uid_int]["name"]
        try:
            bili_user = BiliUser(uid=uid_int, credential=self.adapter.credential)
            info = await bili_user.get_user_info()
            nickname = info.get("name", str(uid))
            self.adapter._user_info_cache[uid_int] = info
            return nickname
        except Exception as e:
            self.adapter.logger.warning(f"[BiliDM] Failed to get user info for {uid}: {type(e).__name__}")
            return str(uid)

    # ===== Image download with cookie =====
    async def _download_image_as_base64_url(self, url: str) -> str:
        """Download an image from BiliBili with cookie auth and return as base64 data URL."""
        cookies = {}
        if self.adapter.credential.sessdata:
            cookies["SESSDATA"] = self.adapter.credential.sessdata
        if self.adapter.credential.bili_jct:
            cookies["bili_jct"] = self.adapter.credential.bili_jct
        if self.adapter.credential.buvid3:
            cookies["buvid3"] = self.adapter.credential.buvid3
        if self.adapter.credential.dedeuserid:
            cookies["DedeUserID"] = self.adapter.credential.dedeuserid
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                resp = await client.get(url, cookies=cookies, headers={
                    "Referer": "https://www.bilibili.com",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36",
                })
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "image/png")
                b64_str = base64.b64encode(resp.content).decode("utf-8")
                return f"data:{content_type};base64,{b64_str}"
        except Exception as e:
            self.adapter.logger.error(f"[BiliDM] Failed to download image: {type(e).__name__}")
            return ""

    # ===== Incoming message handler =====
    async def _handle_incoming_event(self, event: Event, msg_kind: str):
        """Unified handler for all incoming private message events.

        Args:
            event: The raw BiliBili Event object.
            msg_kind: One of 'text', 'picture', 'share_video'.
        """
        sender_uid = str(event.sender_uid)
        if not self.is_allowed(sender_uid, permission="im.direct.receive"):
            return

        try:
            # Fetch real nickname via User().get_user_info()
            nickname = await self._get_user_nickname(event.sender_uid)

            elements: list = []

            if msg_kind == "text":
                # event.content is a str for TEXT
                content = str(event.content) if event.content else ""
                elements.append(Text(content))

            elif msg_kind == "picture":
                # event.content is a Picture object with .url
                # BiliBili IM images require cookie auth; download and convert to base64
                content = event.content
                if hasattr(content, 'url') and content.url:
                    b64_url = await self._download_image_as_base64_url(content.url)
                    if b64_url:
                        elements.append(Image(b64_url))
                    else:
                        elements.append(Text("[Picture download failed]"))
                else:
                    elements.append(Text("[Picture]"))

            elif msg_kind == "share_video":
                # event.content is a Video object; fetch info to build a rich description
                content = event.content
                if isinstance(content, BiliVideo):
                    try:
                        video_info = await content.get_info()
                        title = video_info.get("title", "Unknown")
                        bvid = video_info.get("bvid", "")
                        owner_name = video_info.get("owner", {}).get("name", "Unknown")
                        view = video_info.get("stat", {}).get("view", 0)
                        like = video_info.get("stat", {}).get("like", 0)
                        url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
                        elements.append(
                            Text(f"[Shared Video] {title}\nUP主: {owner_name} | 播放: {view} | 点赞: {like}\n{url}")
                        )
                    except Exception as e:
                        self.adapter.logger.warning(f"[BiliDM] Failed to get video info: {type(e).__name__}")
                        bvid = getattr(content, 'bvid', '')
                        if bvid:
                            elements.append(Text(f"[Shared Video] https://www.bilibili.com/video/{bvid}"))
                        else:
                            elements.append(Text("[Shared Video]"))
                elif hasattr(content, 'bvid') and content.bvid:
                    elements.append(Text(f"[Shared Video] https://www.bilibili.com/video/{content.bvid}"))
                else:
                    elements.append(Text("[Shared Video]"))

            message_chain = MessageChain(elements or [Text("[Unsupported message]")])
            ts = int(event.timestamp) if event.timestamp else int(time.time())

            message_obj = KiraMessageEvent(
                adapter=self.adapter.info,
                supported_elements=list((await self.get_message_metadata()).supported_elements),
                message=KiraIMMessage(
                    timestamp=ts,
                    sender=User(
                        user_id=sender_uid,
                        nickname=nickname
                    ),
                    is_mentioned=True,
                    message_id=str(event.msg_key),
                    self_id=self.adapter.bot_uid,
                    chain=message_chain,
                ),
                timestamp=ts
            )
            self.publish(message_obj)
            self.adapter.logger.info(f"[BiliDM] Received {msg_kind} from {sender_uid}")
        except Exception as e:
            self.adapter.logger.error(f"[BiliDM] Error handling {msg_kind} message: {type(e).__name__}")

    # ===== Send messages (called by core) =====
    async def send_direct_message(self, user_id: AdapterTargetId, message: MessageChain) -> KiraIMSentResult | None:
        """Send direct message to a BiliBili user via bilibili_api send_msg.

        Merge consecutive text and emoji tokens; send images in their original order.
        """
        if not self.adapter.credential.sessdata:
            return KiraIMSentResult(ok=False, err="BiliBili credential not configured")

        try:
            from bilibili_api.session import send_msg
            from bilibili_api.session import EventType as SessionEventType
            from bilibili_api.utils.picture import Picture

            text_parts: list[str] = []

            async def flush_text() -> None:
                if text_parts:
                    await send_msg(
                        self.adapter.credential,
                        int(user_id),
                        SessionEventType.TEXT,
                        "".join(text_parts),
                    )
                    text_parts.clear()

            for ele in message:
                if isinstance(ele, Text):
                    text_parts.append(ele.text)
                elif isinstance(ele, Emoji):
                    text_parts.append(self._metadata.emojis.get(ele.emoji_id, ele.emoji_id))
                elif isinstance(ele, Image):
                    await flush_text()
                    if ele.image_type == "url":
                        pic = await Picture.load_url(ele.image)
                    else:
                        img_bytes = base64.b64decode(await ele.to_base64())
                        pic = Picture.from_content(img_bytes, "png")
                    await send_msg(
                        self.adapter.credential,
                        int(user_id),
                        SessionEventType.PICTURE,
                        pic,
                    )
                else:
                    text_parts.append(str(getattr(ele, 'text', '[Message]')))
            await flush_text()

            self.adapter.logger.info(f"[BiliDM] Sent DM to {user_id}")
            return KiraIMSentResult(ok=True)
        except Exception as e:
            self.adapter.logger.error(f"[BiliDM] Failed to send DM to {user_id}: {type(e).__name__}")
            return KiraIMSentResult(ok=False, err=f"Failed to send direct message: {type(e).__name__}")

    async def send_group_message(self, group_id: AdapterTargetId, message: MessageChain) -> KiraIMSentResult | None:
        raise NotImplementedError("Bilibili does not support group messages")
