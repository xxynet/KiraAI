from __future__ import annotations

import io
import re
import base64
import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Union

import discord

from core.adapter.capabilities import IMCapability
from core.logging_manager import get_logger
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, KiraIMSentResult, Group, User
from core.chat.message_elements import Text, Image, At, Reply, Emoji, Sticker, Record, File, Video

if TYPE_CHECKING:
    from .discord import DiscordAdapter


_msg_sender_logger = get_logger("discord.send", "blue")


class MessageSender:
    """Concurrency control & retry for Discord sends."""

    def __init__(self, max_concurrent: int = 5, max_retries: int = 3, retry_delay: float = 1.0):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    @staticmethod
    def _refresh_discord_files(kwargs: dict):
        """Recreate discord.File objects for retry.

        After a failed attempt the internal file handle may be closed or at
        EOF.  For path-backed files we reopen from ``fp.name``; for seekable
        streams (BytesIO) we just rewind.
        """
        def _recreate(f: discord.File) -> discord.File:
            fp = f.fp
            # path-backed file (BufferedReader with .name)
            if hasattr(fp, "name"):
                new_f = discord.File(fp.name, filename=f.filename, spoiler=f.spoiler)
                if f.description:
                    new_f.description = f.description
                return new_f
            # seekable stream (BytesIO etc.) – just rewind
            if hasattr(fp, "seek"):
                fp.seek(0)
            return f

        file_val = kwargs.get("file")
        if isinstance(file_val, discord.File):
            kwargs["file"] = _recreate(file_val)

        files_val = kwargs.get("files")
        if files_val and isinstance(files_val, list):
            kwargs["files"] = [_recreate(f) if isinstance(f, discord.File) else f for f in files_val]

    async def send_with_retry(self, send_func, *args, **kwargs):
        async with self.semaphore:
            for attempt in range(self.max_retries + 1):
                if attempt > 0:
                    try:
                        await asyncio.to_thread(self._refresh_discord_files, kwargs)
                    except Exception as e:
                        _msg_sender_logger.warning(f"Failed to refresh discord files for retry ({type(e).__name__})")
                try:
                    return await asyncio.wait_for(send_func(*args, **kwargs), timeout=30.0)
                except Exception:
                    if attempt < self.max_retries:
                        await asyncio.sleep(self.retry_delay * (2 ** attempt))
                        continue
                    raise


class DiscordIMCapability(IMCapability["DiscordAdapter"]):
    """Receive, convert and send messages for one Discord account."""

    # ===== Slash Commands =====

    def _register_slash_commands(self):
        """Register slash commands on the bot."""
        adapter = self.adapter  # capture reference for closures

        @self.adapter.bot.slash_command(
            name="ping",
            description="Check if the bot is alive",
            guild_ids=self.adapter.slash_guild_ids or None,
        )
        async def ping(ctx: discord.ApplicationContext):
            latency_ms = round(adapter.bot.latency * 1000)
            await ctx.respond(f"🏓 Pong! Latency: {latency_ms}ms", ephemeral=True)

        @self.adapter.bot.slash_command(
            name="help",
            description="Show bot help information",
            guild_ids=self.adapter.slash_guild_ids or None,
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

    # ===== Bot event handling =====

    async def _handle_message(self, message: discord.Message):
        """Handle incoming Discord messages (called by on_message event)."""
        # Ignore bot's own messages
        if self.adapter.bot.user is None or message.author.id is None or message.author.id == self.adapter.bot.user.id:
            return

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
        if not self.is_allowed(message.channel.id, permission="im.group.receive"):
            return

        if self.adapter.debug_mode:
            if self.adapter.debug_mode_list:
                if f"gm:{channel_id}" in self.adapter.debug_mode_list:
                    self.adapter.logger.debug("Received Discord group message id=%s", message.id)
            else:
                self.adapter.logger.debug("Received Discord group message id=%s", message.id)

        # Check if bot is mentioned (user mention, role mention, or everyone)
        is_mentioned = False
        # 1) Direct user mention: <@bot_id>
        if self.adapter.bot.user in message.mentions:
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
            if isinstance(ref_msg, discord.Message) and ref_msg.author.id == self.adapter.bot.user.id:
                is_mentioned = True

        message_chain = await self._process_incoming_message(message)
        channel = message.channel

        # Channel name: prefer thread name if in thread, otherwise channel name
        channel_name = getattr(channel, "name", str(channel.id))
        if isinstance(channel, discord.Thread):
            channel_name = channel.name

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            message_types=self.adapter.message_types,
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
                self_id=str(self.adapter.bot.user.id),
                chain=message_chain,
                raw_message={"id": str(message.id), "content": message.content},
            ),
            timestamp=int(message.created_at.timestamp()),
        )
        self.publish(message_obj)

    async def _handle_dm_message(self, message: discord.Message, user_id: str):
        """Handle incoming direct messages."""
        # permission check
        if not self.is_allowed(user_id, permission="im.direct.receive"):
            return

        if self.adapter.debug_mode:
            if self.adapter.debug_mode_list:
                if f"dm:{user_id}" in self.adapter.debug_mode_list:
                    self.adapter.logger.debug("Received Discord direct message id=%s", message.id)
            else:
                self.adapter.logger.debug("Received Discord direct message id=%s", message.id)

        message_chain = await self._process_incoming_message(message)

        message_obj = KiraMessageEvent(
            adapter=self.adapter.info,
            message_types=self.adapter.message_types,
            message=KiraIMMessage(
                timestamp=int(message.created_at.timestamp()),
                sender=User(
                    user_id=user_id,
                    nickname=message.author.display_name or str(message.author),
                ),
                is_mentioned=True,
                message_id=str(message.id),
                self_id=str(self.adapter.bot.user.id),
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
        message: MessageChain,
    ) -> Optional[str]:
        """Core send logic: iterates over MessageChain elements and sends to a Discord channel.

        Returns the ID of the last sent message, or None.
        """
        message_id = None
        idx = 0
        reply_to_id = None

        while idx < len(message):
            ele = message[idx]

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
                except discord.NotFound:
                    self.adapter.logger.warning(f"Reply target message {reply_to_id} not found")
                except discord.Forbidden:
                    self.adapter.logger.warning(f"No permission to fetch reply target message {reply_to_id}")
                except discord.HTTPException as e:
                    self.adapter.logger.debug(f"Failed to fetch reply target message {reply_to_id} ({type(e).__name__})")
                reply_to_id = None

            # ── Text / At / Emoji (merge contiguous run into one message) ──
            if isinstance(ele, (Text, At, Emoji)):
                content = ""
                files_to_send = []
                while idx < len(message) and isinstance(message[idx], (Text, At, Emoji)):
                    part = message[idx]
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
                        eid = part.emoji_id or ""
                        edesc = part.emoji_desc or ""
                        if eid.isdigit():
                            content += f"<:{edesc or 'unknown'}:{eid}>"
                        else:
                            content += edesc or eid or ""
                    idx += 1

                if content or files_to_send:
                    sent = await self.adapter.message_sender.send_with_retry(
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
                    image_bytes = await asyncio.to_thread(Path(image_path).read_bytes)
                    discord_file = discord.File(io.BytesIO(image_bytes), filename=filename)
                    sent = await self.adapter.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.adapter.logger.error(f"Failed to send image ({type(e).__name__})")

            # ── Record (voice) ──
            elif isinstance(ele, Record):
                try:
                    record_path = await ele.to_path()
                    record_bytes = await asyncio.to_thread(Path(record_path).read_bytes)
                    discord_file = discord.File(io.BytesIO(record_bytes), filename="voice.mp3")
                    sent = await self.adapter.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.adapter.logger.error(f"Failed to send voice ({type(e).__name__})")

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
                    sent = await self.adapter.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.adapter.logger.error(f"Failed to send sticker ({type(e).__name__})")

            # ── File (document) ──
            elif isinstance(ele, File):
                try:
                    file_path = await ele.to_path()
                    filename = ele.name or "file"
                    file_bytes = await asyncio.to_thread(Path(file_path).read_bytes)
                    discord_file = discord.File(io.BytesIO(file_bytes), filename=filename)
                    sent = await self.adapter.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.adapter.logger.error(f"Failed to send file ({type(e).__name__})")

            # ── Video ──
            elif isinstance(ele, Video):
                try:
                    video_path = await ele.to_path()
                    filename = ele.name or "video.mp4"
                    video_bytes = await asyncio.to_thread(Path(video_path).read_bytes)
                    discord_file = discord.File(io.BytesIO(video_bytes), filename=filename)
                    sent = await self.adapter.message_sender.send_with_retry(
                        channel.send, file=discord_file, **reply_kw
                    )
                    if sent:
                        message_id = str(sent.id)
                except Exception as e:
                    self.adapter.logger.error(f"Failed to send video ({type(e).__name__})")

            # ── Fallback ──
            else:
                sent = await self.adapter.message_sender.send_with_retry(
                    channel.send, content=str(getattr(ele, "text", "[Message]")), **reply_kw
                )
                if sent:
                    message_id = str(sent.id)

            idx += 1

        return message_id

    async def send_group_message(
        self, group_id: Union[int, str], message: MessageChain
    ) -> Optional[KiraIMSentResult]:
        """Send message to a Discord channel (text channel or thread)."""
        try:
            channel = self.adapter.bot.get_channel(int(group_id))
            if channel is None:
                # Try fetching the channel
                try:
                    channel = await self.adapter.bot.fetch_channel(int(group_id))
                except Exception:
                    return KiraIMSentResult(None, ok=False, err=f"Channel {group_id} not found")

            msg_id = await self._send_message_to_channel(channel, message)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=f"Failed to send group message ({type(e).__name__})")

    async def send_direct_message(
        self, user_id: Union[int, str], message: MessageChain
    ) -> Optional[KiraIMSentResult]:
        """Send a direct message to a Discord user."""
        try:
            user = self.adapter.bot.get_user(int(user_id))
            if user is None:
                try:
                    user = await self.adapter.bot.fetch_user(int(user_id))
                except Exception:
                    return KiraIMSentResult(None, ok=False, err=f"User {user_id} not found")

            # Open DM channel
            dm_channel = user.dm_channel
            if dm_channel is None:
                dm_channel = await user.create_dm()

            msg_id = await self._send_message_to_channel(dm_channel, message)
            return KiraIMSentResult(msg_id)
        except Exception as e:
            return KiraIMSentResult(None, ok=False, err=f"Failed to send DM ({type(e).__name__})")
