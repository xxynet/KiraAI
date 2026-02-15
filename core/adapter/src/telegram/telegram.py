import asyncio
import os
from typing import Any, Dict, Union, List
import base64
import time
import json

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from core.logging_manager import get_logger
from core.adapter.adapter_utils import IMAdapter
from core.chat import KiraMessageEvent, MessageChain
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
    Notice,
    Poke,
    File
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

    def __init__(self, info, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue, llm_api):
        super().__init__(info, loop, event_bus, llm_api)

        # config
        self.bot_token: str = self.config.get("bot_token", "")
        self.message_types = ["text", "img", "at", "reply", "record", "emoji", "sticker", "selfie"]

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
            # Start polling for updates asynchronously
            await self.app.updater.start_polling(error_callback=lambda e: logger.error(f"[{self.info.name}] Error occurred : {e}"))

            logger.info(f"start listening incoming messages for {self.config.get('bot_pid', 'your bot account')}")
        except Exception as e:
            logger.info(f"Failed to start listening for {self.config.get('bot_pid', 'your bot account')}: {e}")

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

            triggered = False
            is_mentioned = False
            # 1) Check if message is a reply to bot
            try:
                if msg.reply_to_message and getattr(msg.reply_to_message, "from_user", None):
                    if bot_id is not None and msg.reply_to_message.from_user.id == bot_id:
                        triggered = True
                        is_mentioned = True
            except Exception as e:
                logger.error(e)
            # 2) Check if bot is mentioned by username or text_mention
            if not triggered:
                try:
                    if getattr(msg, "entities", None):
                        for ent in msg.entities:
                            if ent.type == "mention" and bot_username:
                                mention_text = msg.text[ent.offset: ent.offset + ent.length]
                                if mention_text.lower() == f"@{bot_username.lower()}":
                                    triggered = True
                                    is_mentioned = True
                                    break
                            elif ent.type == "text_mention" and getattr(ent, "user", None) and bot_id is not None:
                                if ent.user.id == bot_id:
                                    is_mentioned = True
                                    triggered = True
                                    break
                except Exception as e:
                    logger.error(e)

            if not triggered:
                return

            message_list = await self._process_incoming_message(msg)

            message_obj = KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
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
                chain=message_list,
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
            message_list = await self._process_incoming_message(msg)

            message_obj = KiraMessageEvent(
                adapter=self.info,
                message_types=self.message_types,
                sender=User(
                    user_id=str(user.id),
                    nickname=user.full_name or str(user.id)
                ),
                is_mentioned=True,
                message_id=str(msg.id),
                self_id=self.config["bot_pid"],
                chain=message_list,
                timestamp=int(msg.date.timestamp() or time.time())
            )
            self.publish(message_obj)

    async def _process_incoming_message(self, tg_message) -> List:
        elements: List = []

        # Reply
        if tg_message.reply_to_message:
            replied_text = tg_message.reply_to_message.text or ""
            elements.append(Reply(str(tg_message.reply_to_message.id), replied_text))

        # Text
        if tg_message.text:
            elements.append(Text(tg_message.text))
            # Parse @ mentions in group text messages
            try:
                if getattr(tg_message, "entities", None):
                    for ent in tg_message.entities:
                        if ent.type == "mention":
                            # Handle @username mentions
                            username = tg_message.text[ent.offset: ent.offset + ent.length]
                            elements.append(At(username.lstrip("@")))
                        elif ent.type == "text_mention" and getattr(ent, "user", None):
                            # Direct user mention without username
                            elements.append(At(str(ent.user.id), ent.user.full_name))
            except Exception:
                pass

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
            elements.append(Record(base64_data.decode('utf-8')))

        elif tg_message.audio:
            audio_id = tg_message.audio.file_id
            audio_file = await self.app.bot.get_file(audio_id)
            audio_url = audio_file.file_path

            audio_content = await get_file_content(audio_url)
            base64_data = base64.b64encode(audio_content)
            elements.append(Record(base64_data.decode('utf-8')))

        # Sticker
        if tg_message.sticker:
            elements.append(Text(str(tg_message.sticker.emoji or 'sticker')))

        return elements or [Text("[Unsupported message]")]

    # ===== Send messages (called by core) =====
    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageChain):
        async def _send():
            message_id = None
            if len(send_message_obj) >= 2:
                if isinstance(send_message_obj[0], Reply):
                    # Only effective when followed by text, send as reply with text
                    if isinstance(send_message_obj[1], Text):
                        sent = await self.app.bot.send_message(chat_id=int(group_id), text=send_message_obj[1].text, reply_to_message_id=int(send_message_obj[0].message_id))
                        message_id = str(sent.message_id)
                del send_message_obj[2:]
            # merge At + Text into HTML-formatted message chunks
            idx = 0
            while idx < len(send_message_obj):
                ele = send_message_obj[idx]
                if isinstance(ele, Text) or isinstance(ele, At):
                    html_text = ""
                    # Accumulate contiguous At/Text messages
                    while idx < len(send_message_obj) and (
                            isinstance(send_message_obj[idx], Text) or isinstance(send_message_obj[idx], At)
                    ):
                        part = send_message_obj[idx]
                        if isinstance(part, Text):
                            html_text += part.text
                        else:
                            if part.pid.lower() == "all":
                                html_text += "@all"
                            else:
                                display = part.nickname if part.nickname else part.pid
                                html_text += f"<a href=\"tg://user?id={part.pid}\">{display}</a>"
                        idx += 1
                    sent = await self.app.bot.send_message(chat_id=int(group_id), text=html_text, parse_mode="HTML")
                    message_id = str(sent.message_id)
                    continue
                elif isinstance(ele, Image):
                    if ele.url:
                        sent = await self.app.bot.send_photo(chat_id=int(group_id), photo=ele.url)
                        message_id = str(sent.message_id)
                    elif ele.base64:
                        sent = await self.app.bot.send_photo(chat_id=int(group_id), photo=base64.b64decode(ele.base64))
                        message_id = str(sent.message_id)
                elif isinstance(ele, Emoji):
                    emoji_content = self.emoji_dict.get(ele.emoji_id)
                    sent = await self.app.bot.send_message(chat_id=int(group_id), text=emoji_content)
                    message_id = str(sent.message_id)
                elif isinstance(ele, Record):
                    sent = await self.app.bot.send_voice(chat_id=int(group_id), voice=base64.b64decode(ele.bs64))
                    message_id = str(sent.message_id)
                elif isinstance(ele, Sticker):
                    sent = await self.app.bot.send_photo(chat_id=int(group_id), photo=base64.b64decode(ele.sticker_bs64))
                    message_id = str(sent.message_id)
                else:
                    sent = await self.app.bot.send_message(chat_id=int(group_id), text=str(getattr(ele, 'text', '[Message]')))
                    message_id = str(sent.message_id)
                idx += 1
            return message_id

        if not self.app:
            return None
        try:
            return await self.message_sender.send_with_retry(_send)
        except Exception as e:
            logger.error(f"Failed to send group message: {e}")
            return None

    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageChain):
        async def _send():
            message_id = None
            if len(send_message_obj) >= 2:
                if isinstance(send_message_obj[0], Reply):
                    # Only effective when followed by text, send as reply with text
                    if isinstance(send_message_obj[1], Text):
                        sent = await self.app.bot.send_message(chat_id=int(user_id), text=send_message_obj[1].text, reply_to_message_id=int(send_message_obj[0].message_id))
                        message_id = str(sent.message_id)
                del send_message_obj[2:]
            # merge At + Text into HTML-formatted message chunks
            idx = 0
            while idx < len(send_message_obj):
                ele = send_message_obj[idx]
                if isinstance(ele, Text) or isinstance(ele, At):
                    html_text = ""
                    while idx < len(send_message_obj) and (
                            isinstance(send_message_obj[idx], Text) or isinstance(send_message_obj[idx], At)
                    ):
                        part = send_message_obj[idx]
                        if isinstance(part, Text):
                            html_text += part.text
                        else:
                            if part.pid.lower() == "all":
                                html_text += "@all"
                            else:
                                display = part.nickname if part.nickname else part.pid
                                html_text += f"<a href=\"tg://user?id={part.pid}\">{display}</a>"
                        idx += 1
                    sent = await self.app.bot.send_message(chat_id=int(user_id), text=html_text, parse_mode="HTML")
                    message_id = str(sent.message_id)
                    continue
                elif isinstance(ele, Image):
                    if ele.url:
                        sent = await self.app.bot.send_photo(chat_id=int(user_id), photo=ele.url)
                        message_id = str(sent.message_id)
                    elif ele.base64:
                        sent = await self.app.bot.send_photo(chat_id=int(user_id), photo=base64.b64decode(ele.base64))
                        message_id = str(sent.message_id)
                elif isinstance(ele, Emoji):
                    emoji_content = self.emoji_dict.get(ele.emoji_id)
                    sent = await self.app.bot.send_message(chat_id=int(user_id), text=emoji_content)
                    message_id = str(sent.message_id)
                elif isinstance(ele, Record):
                    sent = await self.app.bot.send_voice(chat_id=int(user_id), voice=base64.b64decode(ele.bs64))
                    message_id = str(sent.message_id)
                elif isinstance(ele, Sticker):
                    sent = await self.app.bot.send_photo(chat_id=int(user_id), photo=base64.b64decode(ele.sticker_bs64))
                    message_id = str(sent.message_id)
                else:
                    sent = await self.app.bot.send_message(chat_id=int(user_id), text=str(getattr(ele, 'text', '[Message]')))
                    message_id = str(sent.message_id)
                idx += 1
            return message_id

        if not self.app:
            return None
        try:
            return await self.message_sender.send_with_retry(_send)
        except Exception as e:
            logger.error(f"Failed to send direct message: {e}")
            return None


__all__ = ["TelegramAdapter"]
