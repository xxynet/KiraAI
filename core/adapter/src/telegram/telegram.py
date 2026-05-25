import asyncio
import os
from typing import Any, Dict, Optional, Union, List
import base64
import time
import json

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from core.logging_manager import get_logger
from core.adapter.adapter_utils import IMAdapter
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult
from core.chat import Session, Group, User
from core.utils.network import get_file_content

from core.chat.message_elements import (
    Text,
    Image,
    At,
    Reply,
    Emoji,
    Sticker,
    Record,
    File,
    Video
)


logger = get_logger("tg_adapter", "green")


class MessageSender:
    """concurrency control & retry config"""

    def __init__(self, max_concurrent: int = 3, max_retries: int = 3, retry_delay: float = 1.0):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    async def send_with_retry(self, send_func, *args, **kwargs):
        async with self.semaphore:
            for attempt in range(self.max_retries + 1):
                try:
                    return await asyncio.wait_for(send_func(*args, **kwargs), timeout=30.0)
                except Exception:
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay * (2 ** attempt))
                        continue
                    raise


class TelegramAdapter(IMAdapter):
    """Telegram adapter"""

    def __init__(self, info, event_bus: asyncio.Queue):
        super().__init__(info, event_bus)

        # config
        self.bot_token: str = self.config.get("bot_token", "")
        self.message_types = ["text", "img", "at", "reply", "record", "emoji", "sticker", "selfie", "file", "video"]

        self.emoji_dict = self._load_dict(os.path.join(os.path.dirname(os.path.abspath(__file__)), "emoji.json"))

        # runtime
        base_url = self.config.get("base_url", "https://api.telegram.org/bot")
        if not base_url:
            base_url = "https://api.telegram.org/bot"

        base_file_url = self.config.get("base_file_url", "https://api.telegram.org/file/bot")
        if not base_file_url:
            base_file_url = "https://api.telegram.org/file/bot"

        self.base_url = base_url
        self.base_file_url = base_file_url

        self.app = ApplicationBuilder().token(self.bot_token).base_url(base_url).base_file_url(base_file_url).build()
        self.message_sender = MessageSender()

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """Load dictionary from file"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception as e:
            return {}

    async def start(self):
        """Start the Telegram adapter asynchronously"""
        if not self.bot_token:
            logger.error("Telegram bot_token is not set")
            return
        
        # Register command handlers
        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        # Register message handler for text, images, voice, etc. (excluding edited messages)
        self.app.add_handler(MessageHandler(filters.ALL, self._on_message))

        # Initialize and start the application asynchronously
        try:
            await self.app.initialize()
            await self.app.start()
            # Start polling, drop any pending updates that accumulated while the bot was offline
            await self.app.updater.start_polling(
                drop_pending_updates=True,
                error_callback=lambda e: logger.error(f"[{self.info.name}] Error occurred : {e}")
            )

            logger.info(f"start listening incoming messages for {self.config.get('bot_pid', 'your bot account')}")
        except Exception as e:
            logger.error(f"Failed to start listening for {self.config.get('bot_pid', 'your bot account')}: {e}")

    async def stop(self):
        """Stop the Telegram adapter asynchronously"""
        if self.app:
            try:
                await self.app.updater.stop()
                await self.app.stop()
                await self.app.shutdown()
                logger.info(f"Stopped listening messages for {self.config.get('bot_pid', 'your bot account')}")
            except Exception as e:
                logger.error(f"Error stopping Telegram adapter: {e}")

    def get_client(self):
        return self.app

    # ===== Command processing =====
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("Hi, I'm online.")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("Help: just talk to me.")

    # ===== Incoming message handler =====
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        chat = msg.chat
        user = msg.from_user

        if chat.type in ("group", "supergroup"):

            should_process = False

            if self.permission_mode == "allow_list" and str(chat.id) in self.group_list:
                should_process = True
            elif self.permission_mode == "deny_list" and str(chat.id) not in self.group_list:
                should_process = True

            if not should_process:
                return
            # Only react when replied to bot or explicitly mentioned (@mention)
            try:
                bot_id = getattr(self.app.bot, "id", None)
                bot_username = getattr(self.app.bot, "username", None)
            except Exception as e:
                bot_id = None
                bot_username = None
                logger.error(e)

            is_mentioned = False
            # 1) Check if message is a reply to bot
            try:
                if msg.reply_to_message and getattr(msg.reply_to_message, "from_user", None):
                    if bot_id is not None and msg.reply_to_message.from_user.id == bot_id:
                        is_mentioned = True
            except Exception as e:
                logger.error(e)
            # 2) Check if bot is mentioned by username or text_mention
            if not is_mentioned:
                try:
                    if getattr(msg, "entities", None):
                        for ent in msg.entities:
                            if ent.type == "mention" and bot_username:
                                mention_text = msg.text[ent.offset: ent.offset + ent.length]
                                if mention_text.lower() == f"@{bot_username.lower()}":
                                    is_mentioned = True
                                    break
                            elif ent.type == "text_mention" and getattr(ent, "user", None) and bot_id is not None:
                                if ent.user.id == bot_id:
                                    is_mentioned = True
                                    break
                except Exception as e:
                    logger.error(e)

            message_chain = await self._process_incoming_message(msg)

            message_obj = KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                message=KiraIMMessage(
                    timestamp=int(msg.date.timestamp() or time.time()),
                    group=Group(
                        group_id=str(chat.id),
                        group_name=chat.title or str(chat.id)
                    ),
                    sender=User(
                        user_id=str(user.id),
                        nickname=user.full_name or str(user.id)
                    ),
                    is_mentioned=is_mentioned,
                    message_id=str(msg.id),
                    self_id=self.config["bot_pid"],
                    chain=message_chain,
                ),
                timestamp=int(msg.date.timestamp() or time.time())
            )
            self.publish(message_obj)
        else:
            # direct message

            should_process = False

            if self.permission_mode == "allow_list" and str(user.id) in self.user_list:
                should_process = True
            elif self.permission_mode == "deny_list" and str(user.id) not in self.user_list:
                should_process = True

            if not should_process:
                return
            message_chain = await self._process_incoming_message(msg)

            message_obj = KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                message=KiraIMMessage(
                    timestamp=int(msg.date.timestamp() or time.time()),
                    sender=User(
                        user_id=str(user.id),
                        nickname=user.full_name or str(user.id)
                    ),
                    is_mentioned=True,
                    message_id=str(msg.id),
                    self_id=self.config["bot_pid"],
                    chain=message_chain,
                ),
                timestamp=int(msg.date.timestamp() or time.time())
            )
            self.publish(message_obj)

    async def _process_incoming_message(self, tg_message) -> MessageChain:
        elements: List = []

        # Reply
        if tg_message.reply_to_message:
            replied_text = tg_message.reply_to_message.text or ""
            elements.append(Reply(str(tg_message.reply_to_message.id), replied_text))

        # Text + inline mentions
        if tg_message.text:
            try:
                entities = getattr(tg_message, "entities", None) or []
                # Collect mention entities with their positions
                mentions = []
                for ent in entities:
                    if ent.type == "mention":
                        username = tg_message.text[ent.offset: ent.offset + ent.length].lstrip("@")
                        # Resolve display name: bot self → full_name directly,
                        # others → use @username (avoid per-mention get_chat to prevent rate-limit issues)
                        display = username
                        try:
                            if self.app.bot.username and username.lower() == self.app.bot.username.lower():
                                display = self.app.bot.full_name or username
                        except Exception:
                            logger.debug(f"Failed to resolve display name for @{username}", exc_info=True)
                        mentions.append((ent.offset, ent.length, At(pid=username, nickname=display)))
                    elif ent.type == "text_mention" and getattr(ent, "user", None):
                        user_obj = ent.user
                        display = getattr(user_obj, "full_name", None) or getattr(user_obj, "username", None) or str(user_obj.id)
                        mentions.append((ent.offset, ent.length, At(pid=str(user_obj.id), nickname=display)))
                # Sort by position to interleave text and At in order
                mentions.sort(key=lambda m: m[0])
                # Build elements by splitting text around mention ranges
                pos = 0
                for offset, length, at_elem in mentions:
                    if offset > pos:
                        plain = tg_message.text[pos:offset]
                        if plain:
                            elements.append(Text(plain))
                    elements.append(at_elem)
                    pos = offset + length
                # Remaining text after last mention
                if pos < len(tg_message.text):
                    trailing = tg_message.text[pos:]
                    if trailing:
                        elements.append(Text(trailing))
            except Exception:
                elements.append(Text(tg_message.text))

        # Photo
        if tg_message.photo:
            try:
                # Select the highest resolution photo
                best_photo = tg_message.photo[-1]
                tg_file = await self.app.bot.get_file(best_photo.file_id)
                # Build direct download URL

                image_url = tg_file.file_path
                elements.append(Image(image_url))
            except Exception:
                # Fallback to placeholder text to ensure non-blocking

                elements.append(Text("[Image]"))

        # Voice/Audio
        if tg_message.voice:
            voice_id = tg_message.voice.file_id
            voice_file = await self.app.bot.get_file(voice_id)
            voice_url = voice_file.file_path

            voice_content = await get_file_content(voice_url)
            base64_data = base64.b64encode(voice_content)
            elements.append(Record(record=base64_data.decode('utf-8')))

        elif tg_message.audio:
            audio_id = tg_message.audio.file_id
            audio_file = await self.app.bot.get_file(audio_id)
            audio_url = audio_file.file_path

            audio_content = await get_file_content(audio_url)
            base64_data = base64.b64encode(audio_content)
            elements.append(Record(record=base64_data.decode('utf-8')))

        # Document (File)
        if tg_message.document:
            try:
                doc = tg_message.document
                tg_file = await self.app.bot.get_file(doc.file_id)
                # tg_file.file_path is already a full URL resolved by the library
                elements.append(File(
                    file=tg_file.file_path,
                    name=getattr(doc, 'file_name', None),
                    size=str(doc.file_size) if doc.file_size else None,
                    mime=doc.mime_type,
                ))
            except Exception:
                elements.append(Text("[File]"))

        # Video
        if tg_message.video:
            try:
                vid = tg_message.video
                tg_file = await self.app.bot.get_file(vid.file_id)
                # tg_file.file_path is already a full URL resolved by the library
                elements.append(Video(
                    file=tg_file.file_path,
                    name=getattr(vid, 'file_name', None),
                    size=str(vid.file_size) if vid.file_size else None,
                    mime=vid.mime_type,
                ))
            except Exception:
                elements.append(Text("[Video]"))

        # Sticker
        if tg_message.sticker:
            try:
                stk = tg_message.sticker
                if stk.is_animated:
                    sticker_mime = "application/x-tgsticker"
                elif stk.is_video:
                    sticker_mime = "video/webm"
                else:
                    sticker_mime = "image/webp"
                tg_file = await self.app.bot.get_file(stk.file_id)
                sticker_content = await get_file_content(tg_file.file_path)
                sticker_b64 = base64.b64encode(sticker_content).decode('utf-8')
                elements.append(Sticker(
                    sticker=sticker_b64,
                    mime=sticker_mime,
                ))
            except Exception:
                elements.append(Text(str(tg_message.sticker.emoji or 'sticker')))

        return MessageChain(elements or [Text("[Unsupported message]")])

    # ===== Send messages (called by core) =====

    @staticmethod
    def _escape_html(text: str) -> str:
        """Escape special characters for Telegram HTML parse mode."""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    async def _send_message_to_chat(self, chat_id: int, send_message_obj: MessageChain) -> Optional[str]:
        """Core send logic shared by group and direct messages.

        Iterates over message elements in ``send_message_obj`` and sends them
        to ``chat_id`` via the Telegram Bot API.  Returns the id of the last
        sent Telegram message, or ``None`` if nothing was sent.
        """
        message_id = None
        idx = 0
        reply_to_id = None

        while idx < len(send_message_obj):
            ele = send_message_obj[idx]

            # Reply element: capture target message id and advance
            if isinstance(ele, Reply):
                reply_to_id = int(ele.message_id)
                idx += 1
                continue

            # Build reply kwargs (consumed by the first send_* call after a Reply)
            reply_kw = {"reply_to_message_id": reply_to_id} if reply_to_id is not None else {}
            reply_to_id = None

            # ── Text / At / Emoji (merge contiguous run into one HTML message) ──
            if isinstance(ele, (Text, At, Emoji)):
                html_text = ""
                while idx < len(send_message_obj) and isinstance(send_message_obj[idx], (Text, At, Emoji)):
                    part = send_message_obj[idx]
                    if isinstance(part, Text):
                        html_text += self._escape_html(part.text)
                    elif isinstance(part, At):
                        if part.pid.lower() == "all":
                            html_text += "@all"
                        elif part.pid.isdigit():
                            # Numeric user ID from text_mention: show display name as clickable link
                            display = part.nickname if part.nickname else part.pid
                            html_text += f"<a href=\"tg://user?id={self._escape_html(part.pid)}\">@{self._escape_html(display)}</a>"
                        else:
                            # String username from mention: use @username
                            html_text += f"@{self._escape_html(part.pid)}"
                    else:  # Emoji
                        html_text += self.emoji_dict.get(part.emoji_id, "")
                    idx += 1
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_message, chat_id=chat_id, text=html_text, parse_mode="HTML", **reply_kw
                )
                message_id = str(sent.message_id)
                continue

            # ── Image ──
            elif isinstance(ele, Image):
                # if ele.image_type == "url":
                #     sent = await self.message_sender.send_with_retry(
                #         self.app.bot.send_photo, chat_id=chat_id, photo=ele.image, **reply_kw
                #     )
                # else:

                # Some URLs may not accessible by Telegram's servers
                image_base64 = await ele.to_base64()
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_photo, chat_id=chat_id, photo=base64.b64decode(image_base64), **reply_kw
                )
                message_id = str(sent.message_id)

            # ── Record (voice) ──
            elif isinstance(ele, Record):
                record_base64 = await ele.to_base64()
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_voice, chat_id=chat_id, voice=base64.b64decode(record_base64), **reply_kw
                )
                message_id = str(sent.message_id)

            # ── Sticker ──
            elif isinstance(ele, Sticker):
                sticker_base64 = await ele.to_base64()
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_sticker, chat_id=chat_id, sticker=base64.b64decode(sticker_base64), **reply_kw
                )
                message_id = str(sent.message_id)

            # ── File (document) ──
            elif isinstance(ele, File):
                file_path = await ele.to_path()
                with open(file_path, "rb") as f:
                    file_bytes = f.read()
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_document, chat_id=chat_id, document=file_bytes, filename=ele.name or "file", **reply_kw
                )
                message_id = str(sent.message_id)

            # ── Video ──
            elif isinstance(ele, Video):
                video_path = await ele.to_path()
                with open(video_path, "rb") as f:
                    video_bytes = f.read()
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_video, chat_id=chat_id, video=video_bytes, filename=ele.name or "video", **reply_kw
                )
                message_id = str(sent.message_id)

            # ── Fallback ──
            else:
                sent = await self.message_sender.send_with_retry(
                    self.app.bot.send_message, chat_id=chat_id, text=str(getattr(ele, 'text', '[Message]')), **reply_kw
                )
                message_id = str(sent.message_id)

            idx += 1

        return message_id

    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageChain):
        if not self.app:
            return KiraIMSentResult(ok=False, err="Telegram bot not started")
        try:
            msg_id = await self._send_message_to_chat(int(group_id), send_message_obj)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(ok=False, err=f"Failed to send group message: {e}")

    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageChain):
        if not self.app:
            return KiraIMSentResult(ok=False, err="Telegram bot not started")
        try:
            msg_id = await self._send_message_to_chat(int(user_id), send_message_obj)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(ok=False, err=f"Failed to send direct message: {e}")


__all__ = ["TelegramAdapter"]
