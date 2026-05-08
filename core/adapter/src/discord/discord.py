import os
import json
import time
import io
import re
import base64
import asyncio
from datetime import datetime
from typing import Any, Dict, Optional, Union, List

import discord  # py-cord library
from discord.ext import commands

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
    Poke,
    File,
    Video,
)
from core.chat import Session, Group, User


class MessageSender:
    """Concurrency control & retry for Discord sends."""

    def __init__(self, max_concurrent: int = 5, max_retries: int = 3, retry_delay: float = 1.0):
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


class DiscordAdapter(IMAdapter):
    """Discord adapter using py-cord

    py-cord provides native slash command support and is the recommended
    library for modern Discord bot development.

    Install via: pip install py-cord
    """

    def __init__(self, info, loop: asyncio.AbstractEventLoop, event_bus: asyncio.Queue, llm_api):
        super().__init__(info, loop, event_bus, llm_api)

        # config
        self.bot_token: str = self.config.get("bot_token", "")
        self.message_types = [
            "text", "img", "at", "reply", "record", "emoji",
            "sticker", "selfie", "file", "video",
        ]

        # intents
        intent_names = self.config.get("intents", [
            "guilds", "guild_messages", "message_content", "direct_messages",
        ])
        intents = discord.Intents.default()
        for name in intent_names:
            if hasattr(intents, name):
                setattr(intents, name, True)
        intents.members = True  # needed for resolving user info

        # proxy
        self.proxy: str = self.config.get("proxy", "") or None

        # Slash command guild IDs (empty = global commands)
        self.slash_guild_ids: List[int] = [
            int(gid) for gid in self.config.get("slash_guild_ids", [])
        ]

        # Create py-cord Bot with slash command support
        self.bot = discord.Bot(
            intents=intents,
            proxy=self.proxy,
            # auto_sync_commands will automatically sync slash commands on startup
            auto_sync_commands=self.config.get("auto_sync_commands", True),
        )

        # Register event handlers (py-cord uses decorators)
        self._register_events()

        # Register slash commands
        self._register_slash_commands()

        # runtime
        self.message_sender = MessageSender()
        self.logger = get_logger(info.name, "blue")
        self._bot_task: Optional[asyncio.Task] = None
        self._last_error: Optional[Exception] = None
        self.debug_mode = self.config.get("debug_mode", False)
        self.debug_mode_list = self.config.get("debug_mode_list", [])

    # ===== Slash Commands =====

    def _register_slash_commands(self):
        """Register slash commands on the bot."""
        adapter = self  # capture reference for closures

        @self.bot.slash_command(
            name="ping",
            description="Check if the bot is alive",
            guild_ids=self.slash_guild_ids or None,
        )
        async def ping(ctx: discord.ApplicationContext):
            latency_ms = round(adapter.bot.latency * 1000)
            await ctx.respond(f"🏓 Pong! Latency: {latency_ms}ms", ephemeral=True)

        @self.bot.slash_command(
            name="help",
            description="Show bot help information",
            guild_ids=self.slash_guild_ids or None,
        )
        async def help_cmd(ctx: discord.ApplicationContext):
            embed = discord.Embed(
                title="KiraAI Help",
                description="I'm a cross-platform AI digital life with agent capabilities.",
                color=discord.Color.blue(),
            )
            embed.add_field(
                name="Commands",
                value="`/ping` — Check bot latency\n`/help` — Show this message",
                inline=False,
            )
            await ctx.respond(embed=embed, ephemeral=True)

    # ===== Event Registration =====

    def _register_events(self):
        """Register py-cord event handlers using decorators."""
        adapter = self  # capture reference for closures

        @self.bot.event
        async def on_ready():
            adapter.logger.info(
                f"Discord bot logged in as {adapter.bot.user} (ID: {adapter.bot.user.id})"
            )
            adapter.logger.info(
                f"Slash commands synced: {len(adapter.bot.pending_application_commands)} pending"
            )

        @self.bot.event
        async def on_message(message: discord.Message):
            await adapter._handle_message(message)

    # ===== Lifecycle =====

    async def start(self):
        """Start the Discord adapter (non-blocking)."""
        if not self.bot_token:
            self.logger.error("Discord bot_token is not set")
            return
        self.logger.info(f"Starting Discord adapter, proxy={self.proxy or 'None'} ...")
        self._bot_task = asyncio.create_task(self._run_bot())

    async def _run_bot(self):
        """Run the bot in a background task."""
        try:
            await self.bot.start(self.bot_token)
        except asyncio.CancelledError:
            self.logger.info("Discord bot task cancelled")
            raise
        except Exception as e:
            self._last_error = e
            self.logger.error(f"Discord bot error: {e}")
            raise

    async def stop(self):
        """Stop the Discord adapter."""
        if self._bot_task and not self._bot_task.done():
            self._bot_task.cancel()
            try:
                await self._bot_task
            except asyncio.CancelledError:
                pass
        if self.bot and not self.bot.is_closed():
            await self.bot.close()
            self.logger.info(f"Stopped Discord adapter for {self.config.get('bot_pid', 'bot')}")

    def get_client(self) -> discord.Bot:
        return self.bot

    # ===== Bot event handling =====

    async def _handle_message(self, message: discord.Message):
        """Handle incoming Discord messages (called by on_message event)."""
        # Ignore bot's own messages
        if message.author.id == self.bot.user.id:
            return

        # Ignore other bots if desired (optional)
        # if message.author.bot:
        #     return

        is_group = message.guild is not None
        user_id = str(message.author.id)

        if is_group:
            await self._handle_group_message(message, user_id)
        else:
            await self._handle_dm_message(message, user_id)

    async def _handle_group_message(self, message: discord.Message, user_id: str):
        """Handle incoming group/server messages."""
        channel_id = str(message.channel.id)

        # permission check
        should_process = False
        if self.permission_mode == "allow_list" and channel_id in self.group_list:
            should_process = True
        elif self.permission_mode == "deny_list" and channel_id not in self.group_list:
            should_process = True
        if not should_process:
            return

        if self.debug_mode:
            if self.debug_mode_list:
                if f"gm:{channel_id}" in self.debug_mode_list:
                    self.logger.debug(f"Raw message: {message}")
            else:
                self.logger.debug(f"Raw message: {message}")

        # Check if bot is mentioned (user mention, role mention, or everyone)
        is_mentioned = False
        # 1) Direct user mention: <@bot_id>
        if self.bot.user in message.mentions:
            is_mentioned = True
        # 2) Role mention: <@&role_id> — check if any mentioned role belongs to the bot
        if not is_mentioned and message.role_mentions:
            bot_member = message.guild.me if message.guild else None
            if bot_member:
                bot_role_ids = {r.id for r in bot_member.roles}
                for role in message.role_mentions:
                    if role.id in bot_role_ids:
                        is_mentioned = True
                        break
        # 3) @everyone / @here
        if not is_mentioned and message.mention_everyone:
            is_mentioned = True
        # 4) Check if message is a reply to bot
        if not is_mentioned and message.reference and message.reference.resolved:
            ref_msg = message.reference.resolved
            if isinstance(ref_msg, discord.Message) and ref_msg.author.id == self.bot.user.id:
                is_mentioned = True

        message_chain = await self._process_incoming_message(message)
        channel = message.channel

        # Channel name: prefer thread name if in thread, otherwise channel name
        channel_name = getattr(channel, "name", str(channel.id))
        if isinstance(channel, discord.Thread):
            channel_name = channel.name

        message_obj = KiraMessageEvent(
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=int(message.created_at.timestamp()),
                group=Group(
                    group_id=str(channel.id),
                    group_name=channel_name,
                ),
                sender=User(
                    user_id=user_id,
                    nickname=message.author.display_name or str(message.author),
                ),
                is_mentioned=is_mentioned,
                message_id=str(message.id),
                self_id=str(self.bot.user.id),
                chain=message_chain,
                raw_message={"id": str(message.id), "content": message.content},
            ),
            timestamp=int(message.created_at.timestamp()),
        )
        self.publish(message_obj)

    async def _handle_dm_message(self, message: discord.Message, user_id: str):
        """Handle incoming direct messages."""
        # permission check
        should_process = False
        if self.permission_mode == "allow_list" and user_id in self.user_list:
            should_process = True
        elif self.permission_mode == "deny_list" and user_id not in self.user_list:
            should_process = True
        if not should_process:
            return

        if self.debug_mode:
            if self.debug_mode_list:
                if f"dm:{user_id}" in self.debug_mode_list:
                    self.logger.debug(f"Raw DM: {message}")
            else:
                self.logger.debug(f"Raw DM: {message}")

        message_chain = await self._process_incoming_message(message)

        message_obj = KiraMessageEvent(
            adapter=self.info,
            message_types=self.message_types,
            message=KiraIMMessage(
                timestamp=int(message.created_at.timestamp()),
                sender=User(
                    user_id=user_id,
                    nickname=message.author.display_name or str(message.author),
                ),
                is_mentioned=True,
                message_id=str(message.id),
                self_id=str(self.bot.user.id),
                chain=message_chain,
                raw_message={"id": str(message.id), "content": message.content},
            ),
            timestamp=int(message.created_at.timestamp()),
        )
        self.publish(message_obj)

    # ===== Incoming message conversion =====

    async def _process_incoming_message(self, message: discord.Message) -> MessageChain:
        """Convert a Discord message to the project's generic MessageChain."""
        elements: List = []

        # Reply (message reference)
        if message.reference:
            ref = message.reference
            ref_msg = ref.resolved
            if isinstance(ref_msg, discord.Message):
                replied_text = ref_msg.content or ""
                elements.append(Reply(str(ref_msg.id), replied_text))
            elif ref.message_id:
                elements.append(Reply(str(ref.message_id)))

        # Text content (may contain inline mentions)
        if message.content:
            # Parse mentions within text
            text = message.content
            # Single regex pass to find every mention occurrence accurately,
            # handling <@id>, <@!id> (user) and <@&id> (role) including duplicates.
            _mention_re = re.compile(r"<@&(\d+)>|<@!?(\d+)>")
            mention_matches = list(_mention_re.finditer(text))

            if mention_matches:
                pos = 0
                for m in mention_matches:
                    # Emit any plain text before this mention
                    if m.start() > pos:
                        plain = text[pos:m.start()]
                        if plain:
                            elements.append(Text(plain))
                    # Determine mention type and extract the id
                    if m.group(1) is not None:
                        mid = m.group(1)
                        mention_type = "role"
                    else:
                        mid = m.group(2)
                        mention_type = "user"
                    # Resolve nickname
                    nick = mid
                    try:
                        if mention_type == "role" and message.guild:
                            role = message.guild.get_role(int(mid))
                            if role:
                                nick = f"@{role.name}"
                        elif message.guild:
                            member = message.guild.get_member(int(mid))
                            if member:
                                nick = member.display_name
                    except Exception:
                        pass
                    elements.append(At(pid=mid, nickname=nick))
                    pos = m.end()
                # Trailing text after last mention
                if pos < len(text):
                    trailing = text[pos:]
                    if trailing:
                        elements.append(Text(trailing))
            else:
                elements.append(Text(text))

        # Images (attachments)
        for att in message.attachments:
            content_type = att.content_type or ""
            if content_type.startswith("image/"):
                # Check if it's a sticker-like image (gif with small dimensions)
                if content_type == "image/gif" and att.width and att.width <= 200 and att.height and att.height <= 200:
                    try:
                        from core.utils.common_utils import image_to_base64
                        sticker_b64 = await image_to_base64(att.url)
                        elements.append(Sticker(sticker=sticker_b64))
                    except Exception:
                        elements.append(Image(att.url))
                else:
                    elements.append(Image(att.url))
            elif content_type.startswith("video/"):
                elements.append(Video(
                    file=att.url,
                    name=att.filename,
                    size=str(att.size) if att.size else None,
                ))
            elif content_type.startswith("audio/"):
                try:
                    from core.utils.network import get_file_content
                    audio_data = await get_file_content(att.url)
                    audio_b64 = base64.b64encode(audio_data).decode("utf-8")
                    elements.append(Record(record=audio_b64))
                except Exception:
                    elements.append(File(
                        file=att.url,
                        name=att.filename,
                        size=str(att.size) if att.size else None,
                    ))
            else:
                # Other attachments treated as files
                elements.append(File(
                    file=att.url,
                    name=att.filename,
                    size=str(att.size) if att.size else None,
                ))

        # Discord stickers
        for sticker in message.stickers:
            try:
                sticker_url = sticker.url
                from core.utils.network import get_file_content
                sticker_data = await get_file_content(sticker_url)
                sticker_b64 = base64.b64encode(sticker_data).decode("utf-8")
                mime = "image/webp"
                if sticker.format == discord.StickerFormatType.lottie:
                    # Lottie stickers can't be easily converted; use placeholder
                    elements.append(Text(f"[Sticker: {sticker.name}]"))
                    continue
                elif sticker.format == discord.StickerFormatType.gif:
                    mime = "image/gif"
                elif sticker.format == discord.StickerFormatType.apng:
                    mime = "image/apng"
                elements.append(Sticker(sticker=sticker_b64, mime=mime))
            except Exception:
                elements.append(Text(f"[Sticker: {sticker.name}]"))

        return MessageChain(elements or [Text("[Unsupported message]")])

    # ===== Outgoing message sending =====

    async def _send_message_to_channel(
        self,
        channel: Union[discord.TextChannel, discord.Thread, discord.DMChannel, discord.User, discord.Member],
        send_message_obj: MessageChain,
    ) -> Optional[str]:
        """Core send logic: iterates over MessageChain elements and sends to a Discord channel.

        Returns the ID of the last sent message, or None.
        """
        message_id = None
        idx = 0
        reply_to_id = None

        while idx < len(send_message_obj):
            ele = send_message_obj[idx]

            # Reply element: capture target message id and advance
            if isinstance(ele, Reply):
                try:
                    reply_to_id = int(ele.message_id)
                except (ValueError, TypeError):
                    reply_to_id = None
                idx += 1
                continue

            reply_kw = {}
            if reply_to_id is not None:
                try:
                    ref_msg = await channel.fetch_message(reply_to_id)
                    reply_kw["reference"] = ref_msg
                except Exception:
                    pass
                reply_to_id = None

            # ── Text / At / Emoji (merge contiguous run into one message) ──
            if isinstance(ele, (Text, At, Emoji)):
                content = ""
                files_to_send = []
                while idx < len(send_message_obj) and isinstance(send_message_obj[idx], (Text, At, Emoji)):
                    part = send_message_obj[idx]
                    if isinstance(part, Text):
                        content += part.text
                    elif isinstance(part, At):
                        if part.pid.lower() == "all":
                            content += "@everyone"
                        else:
                            content += f"<@{part.pid}>"
                    elif isinstance(part, Emoji):
                        # Discord uses custom emoji format: <:name:id> or <a:name:id>
                        # If emoji_id looks like a Discord emoji ID (numeric), try custom format
                        eid = part.emoji_id
                        edesc = part.emoji_desc or ""
                        if eid.isdigit():
                            content += f"<:{edesc}:{eid}>" if edesc else eid
                        else:
                            content += edesc or eid
                    idx += 1

                if content or files_to_send:
                    sent = await self.message_sender.send_with_retry(
                        channel.send, content=content or None, files=files_to_send or None, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                continue

            # ── Image ──
            elif isinstance(ele, Image):
                try:
                    image_path = await ele.to_path()
                    filename = ele.name or "image.png"
                    discord_file = discord.File(image_path, filename=filename)
                    sent = await self.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.logger.error(f"Failed to send image: {e}")

            # ── Record (voice) ──
            elif isinstance(ele, Record):
                try:
                    record_path = await ele.to_path()
                    discord_file = discord.File(record_path, filename="voice.mp3")
                    sent = await self.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.logger.error(f"Failed to send voice: {e}")

            # ── Sticker (send as image attachment) ──
            elif isinstance(ele, Sticker):
                try:
                    sticker_b64 = await ele.to_base64()
                    sticker_bytes = base64.b64decode(sticker_b64)
                    mime = ele.mime or "image/webp"
                    ext = "webp"
                    if "gif" in mime:
                        ext = "gif"
                    elif "png" in mime:
                        ext = "png"
                    discord_file = discord.File(io.BytesIO(sticker_bytes), filename=f"sticker.{ext}")
                    sent = await self.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.logger.error(f"Failed to send sticker: {e}")

            # ── File (document) ──
            elif isinstance(ele, File):
                try:
                    file_path = await ele.to_path()
                    filename = ele.name or "file"
                    discord_file = discord.File(file_path, filename=filename)
                    sent = await self.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.logger.error(f"Failed to send file: {e}")

            # ── Video ──
            elif isinstance(ele, Video):
                try:
                    video_path = await ele.to_path()
                    filename = ele.name or "video.mp4"
                    discord_file = discord.File(video_path, filename=filename)
                    sent = await self.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.logger.error(f"Failed to send video: {e}")

            # ── Fallback ──
            else:
                sent = await self.message_sender.send_with_retry(
                    channel.send, content=str(getattr(ele, "text", "[Message]")), **reply_kw
                )
                if sent:
                    message_id = str(sent.id)

            idx += 1

        return message_id

    async def send_group_message(
        self, group_id: Union[int, str], send_message_obj: MessageChain
    ) -> Optional[KiraIMSentResult]:
        """Send message to a Discord channel (text channel or thread)."""
        try:
            channel = self.bot.get_channel(int(group_id))
            if channel is None:
                # Try fetching the channel
                try:
                    channel = await self.bot.fetch_channel(int(group_id))
                except Exception:
                    return KiraIMSentResult(None, ok=False, err=f"Channel {group_id} not found")

            msg_id = await self._send_message_to_channel(channel, send_message_obj)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=f"Failed to send group message: {e}")

    async def send_direct_message(
        self, user_id: Union[int, str], send_message_obj: MessageChain
    ) -> Optional[KiraIMSentResult]:
        """Send a direct message to a Discord user."""
        try:
            user = self.bot.get_user(int(user_id))
            if user is None:
                try:
                    user = await self.bot.fetch_user(int(user_id))
                except Exception:
                    return KiraIMSentResult(None, ok=False, err=f"User {user_id} not found")

            # Open DM channel
            dm_channel = user.dm_channel
            if dm_channel is None:
                dm_channel = await user.create_dm()

            msg_id = await self._send_message_to_channel(dm_channel, send_message_obj)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=f"Failed to send DM: {e}")


__all__ = ["DiscordAdapter"]
