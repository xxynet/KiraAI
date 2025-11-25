import asyncio
from typing import Any, Dict, Union, List
import threading
import base64
import requests
import json

from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

from core.logging_manager import get_logger
from utils.adapter_utils import IMAdapter
from utils.message_utils import KiraMessageEvent, MessageSending, MessageType


logger = get_logger("tg_adapter", "green")


class MessageSender:
    """简单的并发控制与重试封装"""

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
    """Telegram 平台适配器，接入主事件总线"""

    def __init__(self, config: Dict[str, Any], loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue):
        super().__init__(config, loop, event_bus)
        self.name: str = "Telegram"

        # 配置
        self.bot_token: str = self.config.get("bot_token", "")
        self.message_types = [MessageType.Text, MessageType.Image, MessageType.At, MessageType.Reply, MessageType.Sticker, MessageType.Record, MessageType.Notice, MessageType.Emoji]

        self.emoji_dict = self._load_dict("adapters/telegram/emoji.json")

        # 运行时
        self.app = None
        self.message_sender = MessageSender()

    @staticmethod
    def _load_dict(path: str) -> Dict[str, Any]:
        """加载字典"""
        try:
            with open(path, 'r', encoding="utf-8") as f:
                emoji_json = f.read()
            return json.loads(emoji_json)
        except Exception as e:
            return {}

    def _start_blocking(self):
        # 在线程中手动创建并设置事件循环，避免 get_event_loop 报错
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.app = ApplicationBuilder().token(self.bot_token).build()

        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        # 文本、图片、语音等（不处理已编辑的消息）
        self.app.add_handler(MessageHandler(filters.ALL, self._on_message))

        self.app.run_polling()

    async def start(self):
        if not self.bot_token:
            logger.error("Telegram bot_token 未配置，跳过启动")
            return
        threading.Thread(target=self._start_blocking, daemon=True).start()

    # ===== 命令处理 =====
    async def _cmd_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("Hi, I'm online.")

    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.effective_message.reply_text("Help: just talk to me.")

    # ===== 收消息入口 =====
    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        msg = update.effective_message
        chat = msg.chat
        user = msg.from_user

        if chat.type in ("group", "supergroup"):
            if self.group_list and chat.id not in self.group_list:
                return
            # Only react when replied to bot or explicitly mentioned
            try:
                bot_id = getattr(self.app.bot, "id", None)
                bot_username = getattr(self.app.bot, "username", None)
            except Exception:
                bot_id = None
                bot_username = None

            triggered = False
            # 1) reply to bot
            try:
                if msg.reply_to_message and getattr(msg.reply_to_message, "from_user", None):
                    if bot_id is not None and msg.reply_to_message.from_user.id == bot_id:
                        triggered = True
            except Exception:
                pass
            # 2) @mention bot by username or text_mention
            if not triggered:
                try:
                    if getattr(msg, "entities", None):
                        for ent in msg.entities:
                            if ent.type == "mention" and bot_username:
                                mention_text = msg.text[ent.offset: ent.offset + ent.length]
                                if mention_text.lower() == f"@{bot_username.lower()}":
                                    triggered = True
                                    break
                            elif ent.type == "text_mention" and getattr(ent, "user", None) and bot_id is not None:
                                if ent.user.id == bot_id:
                                    triggered = True
                                    break
                except Exception:
                    pass

            if not triggered:
                return

            message_list = await self._process_incoming_message(msg)
            message_obj = KiraMessageEvent(
                platform=self.name,
                adapter_name=self.config.get('adapter_name', 'tg'),
                message_types=self.message_types,
                group_id=str(chat.id),
                group_name=chat.title or str(chat.id),
                user_id=str(user.id),
                user_nickname=user.full_name or str(user.id),
                message_id=str(msg.id),
                # str(context.bot.id)
                self_id=self.config["bot_pid"],
                content=message_list,
                timestamp=int(msg.date.timestamp())
            )
            self.publish(message_obj)
        else:
            # direct message
            if self.user_list and user.id not in self.user_list:
                return
            message_list = await self._process_incoming_message(msg)
            message_obj = KiraMessageEvent(
                platform=self.name,
                adapter_name=self.config.get('adapter_name', 'tg'),
                message_types=self.message_types,
                user_id=str(user.id),
                user_nickname=user.full_name or str(user.id),
                message_id=str(msg.id),
                # str(context.bot.id)
                self_id=self.config["bot_pid"],
                content=message_list,
                timestamp=int(msg.date.timestamp())
            )
            self.publish(message_obj)

    async def _process_incoming_message(self, tg_message) -> List:
        elements: List = []

        # Reply
        if tg_message.reply_to_message:
            replied_text = tg_message.reply_to_message.text or ""
            elements.append(MessageType.Reply(str(tg_message.reply_to_message.id), replied_text))

        # Text
        if tg_message.text:
            elements.append(MessageType.Text(tg_message.text))
            # Parse @ mentions in group text
            try:
                if getattr(tg_message, "entities", None):
                    for ent in tg_message.entities:
                        if ent.type == "mention":
                            # like @username
                            username = tg_message.text[ent.offset: ent.offset + ent.length]
                            elements.append(MessageType.At(username.lstrip("@")))
                        elif ent.type == "text_mention" and getattr(ent, "user", None):
                            # direct user mention without username
                            elements.append(MessageType.At(str(ent.user.id), ent.user.full_name))
            except Exception:
                pass

        # Photo
        if tg_message.photo:
            try:
                # 选择分辨率最高的尺寸
                best_photo = tg_message.photo[-1]
                tg_file = await self.app.bot.get_file(best_photo.file_id)
                # 构建可直链下载的 URL

                image_url = tg_file.file_path
                elements.append(MessageType.Image(image_url))
            except Exception:
                # 回退为占位文本，确保不阻塞

                elements.append(MessageType.Text("[Image]"))

        # Voice/Audio
        if tg_message.voice:
            voice_id = tg_message.voice.file_id
            voice_file = await self.app.bot.get_file(voice_id)
            voice_url = voice_file.file_path

            voice_content = requests.get(voice_url).content
            base64_data = base64.b64encode(voice_content)
            elements.append(MessageType.Record(base64_data.decode('utf-8')))

        elif tg_message.audio:
            audio_id = tg_message.audio.file_id
            audio_file = await self.app.bot.get_file(audio_id)
            audio_url = audio_file.file_path

            audio_content = requests.get(audio_url).content
            base64_data = base64.b64encode(audio_content)
            elements.append(MessageType.Record(base64_data.decode('utf-8')))

        # Sticker
        if tg_message.sticker:
            elements.append(MessageType.Text(str(tg_message.sticker.emoji or 'sticker')))

        return elements or [MessageType.Text("[Unsupported message]")]

    # ===== 发消息（供核心调用） =====
    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageSending):
        async def _send():
            message_id = None
            if len(send_message_obj.message_list) >= 2:
                if isinstance(send_message_obj.message_list[0], MessageType.Reply):
                    # 仅在有后续文本时生效，这里作为引用发送一条空文本
                    if isinstance(send_message_obj.message_list[1], MessageType.Text):
                        sent = await self.app.bot.send_message(chat_id=int(group_id), text=send_message_obj.message_list[1].text, reply_to_message_id=int(send_message_obj.message_list[0].message_id))
                        message_id = str(sent.message_id)
                send_message_obj.message_list = send_message_obj.message_list[2:]
            # merge At + Text into HTML-formatted message chunks
            idx = 0
            while idx < len(send_message_obj.message_list):
                ele = send_message_obj.message_list[idx]
                if isinstance(ele, MessageType.Text) or isinstance(ele, MessageType.At):
                    html_text = ""
                    # accumulate contiguous At/Text
                    while idx < len(send_message_obj.message_list) and (
                        isinstance(send_message_obj.message_list[idx], MessageType.Text) or isinstance(send_message_obj.message_list[idx], MessageType.At)
                    ):
                        part = send_message_obj.message_list[idx]
                        if isinstance(part, MessageType.Text):
                            html_text += part.text
                        else:
                            # MessageType.At
                            if part.pid.lower() == "all":
                                html_text += "@all"
                            else:
                                display = part.nickname if part.nickname else part.pid
                                html_text += f"<a href=\"tg://user?id={part.pid}\">{display}</a>"
                        idx += 1
                    sent = await self.app.bot.send_message(chat_id=int(group_id), text=html_text, parse_mode="HTML")
                    message_id = str(sent.message_id)
                    continue
                elif isinstance(ele, MessageType.Image):
                    sent = await self.app.bot.send_photo(chat_id=int(group_id), photo=ele.url)
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Emoji):
                    emoji_content = self.emoji_dict.get(ele.emoji_id)
                    sent = await self.app.bot.send_message(chat_id=int(group_id), text=emoji_content)
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Record):
                    sent = await self.app.bot.send_voice(chat_id=int(group_id), voice=base64.b64decode(ele.bs64))
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Sticker):
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
            logger.error(f"发送群消息失败: {e}")
            return None

    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageSending):
        async def _send():
            message_id = None
            if len(send_message_obj.message_list) >= 2:
                if isinstance(send_message_obj.message_list[0], MessageType.Reply):
                    # 仅在有后续文本时生效，这里作为引用发送一条空文本
                    if isinstance(send_message_obj.message_list[1], MessageType.Text):
                        sent = await self.app.bot.send_message(chat_id=int(user_id), text=send_message_obj.message_list[1].text, reply_to_message_id=int(send_message_obj.message_list[0].message_id))
                        message_id = str(sent.message_id)
                send_message_obj.message_list = send_message_obj.message_list[2:]
            # merge At + Text into HTML-formatted message chunks
            idx = 0
            while idx < len(send_message_obj.message_list):
                ele = send_message_obj.message_list[idx]
                if isinstance(ele, MessageType.Text) or isinstance(ele, MessageType.At):
                    html_text = ""
                    while idx < len(send_message_obj.message_list) and (
                        isinstance(send_message_obj.message_list[idx], MessageType.Text) or isinstance(send_message_obj.message_list[idx], MessageType.At)
                    ):
                        part = send_message_obj.message_list[idx]
                        if isinstance(part, MessageType.Text):
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
                elif isinstance(ele, MessageType.Image):
                    sent = await self.app.bot.send_photo(chat_id=int(user_id), photo=ele.url)
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Emoji):
                    emoji_content = self.emoji_dict.get(ele.emoji_id)
                    sent = await self.app.bot.send_message(chat_id=int(user_id), text=emoji_content)
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Record):
                    sent = await self.app.bot.send_voice(chat_id=int(user_id), voice=base64.b64decode(ele.bs64))
                    message_id = str(sent.message_id)
                elif isinstance(ele, MessageType.Sticker):
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
            logger.error(f"发送私聊消息失败: {e}")
            return None


__all__ = ["TelegramAdapter"]
