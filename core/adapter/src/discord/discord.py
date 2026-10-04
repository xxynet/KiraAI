from __future__ import annotations

import asyncio
from typing import List, Optional, Union

import discord

from core.adapter.access import ListAccessPolicy
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.chat import MessageChain
from core.logging_manager import get_logger

from .im import MessageSender, DiscordIMCapability


class DiscordAdapter(BaseAdapter):
    """Discord adapter using py-cord

    py-cord provides native slash command support and is the recommended
    library for modern Discord bot development.

    Install via: pip install py-cord
    """

    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)

        # config
        self.bot_token: str = self.config.get("bot_token", "")

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

        self._intents = intents
        self._lifecycle_lock = asyncio.Lock()
        self._accepting_messages = False
        self._message_tasks: set[asyncio.Task] = set()

        self.im = self.register_capability(IMCapability, DiscordIMCapability(self))
        self._configure_access()
        self._create_bot()

        # runtime
        self.message_sender = MessageSender()
        self.logger = get_logger(self.info.name, "blue")
        self._bot_task: Optional[asyncio.Task] = None
        self._last_error: Optional[Exception] = None
        self.debug_mode = self.config.get("debug_mode", False)
        self.debug_mode_list = self.config.get("debug_mode_list", [])

    def _create_bot(self):
        self.bot = discord.Bot(
            intents=self._intents,
            proxy=self.proxy,
            auto_sync_commands=self.config.get("auto_sync_commands", True),
        )
        self._register_events()
        self.im._register_slash_commands()

    # ===== Event Registration =====

    def _register_events(self):
        """Register py-cord event handlers using decorators."""
        adapter = self  # capture reference for closures
        bot = self.bot

        @self.bot.event
        async def on_ready():
            if bot is not adapter.bot or not adapter._accepting_messages:
                return
            adapter.logger.info(
                f"Discord bot logged in as {bot.user} (ID: {bot.user.id})"
            )
            adapter.logger.info(
                f"Slash commands synced: {len(bot.pending_application_commands)} pending"
            )

        @self.bot.event
        async def on_message(message: discord.Message):
            if bot is not adapter.bot or not adapter._accepting_messages:
                return
            task = asyncio.current_task()
            adapter._message_tasks.add(task)
            try:
                await adapter.im._handle_message(message)
            finally:
                adapter._message_tasks.discard(task)

    # ===== Lifecycle =====

    async def start(self):
        async with self._lifecycle_lock:
            await self._start()

    async def _start(self):
        """Start the Discord adapter (non-blocking)."""
        if not self.bot_token:
            self.logger.error("Discord bot_token is not set")
            return
        if self._bot_task and not self._bot_task.done():
            return
        if self.bot.is_closed():
            self._create_bot()
        self._last_error = None
        self._accepting_messages = True
        self.logger.info("Starting Discord adapter, proxy configured=%s", bool(self.proxy))
        self._bot_task = asyncio.create_task(self._run_bot())
        self._bot_task.add_done_callback(self._observe_bot_task)

    def _observe_bot_task(self, task: asyncio.Task):
        if not task.cancelled():
            task.exception()

    async def _run_bot(self):
        """Run the bot in a background task."""
        try:
            await self.bot.start(self.bot_token)
        except asyncio.CancelledError:
            self.logger.info("Discord bot task cancelled")
            raise
        except Exception as e:
            self._last_error = e
            self.logger.error("Discord bot error (%s)", type(e).__name__)
            raise
        finally:
            self._accepting_messages = False

    async def stop(self):
        async with self._lifecycle_lock:
            await self._stop()

    async def _stop(self):
        """Stop the Discord adapter."""
        self._accepting_messages = False
        try:
            await self._cancel_message_tasks()
        finally:
            try:
                task = self._bot_task
                if task and task is not asyncio.current_task():
                    if not task.done():
                        task.cancel()
                    # The runner must stop issuing requests before its HTTP session closes.
                    # Runtime failures are already recorded by _run_bot.
                    await asyncio.gather(task, return_exceptions=True)
            finally:
                if self.bot and not self.bot.is_closed():
                    await self.bot.close()

        if self.bot:
            self.logger.info(f"Stopped Discord adapter for {self.config.get('bot_pid', 'bot')}")

    async def _cancel_message_tasks(self):
        tasks = [task for task in self._message_tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_client(self) -> discord.Bot:
        return self.bot

    def _configure_access(self) -> None:
        mode = self.config.get("permission_mode", "allow_list")
        valid_mode = mode in ("allow_list", "deny_list")
        for scope, target in (("direct", "user"), ("group", "group")):
            allow_list = self.config.get(f"{target}_allow_list", [])
            deny_list = self.config.get(f"{target}_deny_list", [])
            self.access.set_policy(
                capability_type=IMCapability,
                permission=f"im.{scope}.receive",
                policy=ListAccessPolicy.from_lists(
                    mode if valid_mode else "allow_list",
                    allow_list=allow_list if valid_mode and isinstance(allow_list, list) else [],
                    deny_list=deny_list if valid_mode and isinstance(deny_list, list) else [],
                ),
            )

    async def send_group_message(self, group_id: Union[int, str], send_message_obj: MessageChain):
        return await self.im.send_group_message(group_id, send_message_obj)

    async def send_direct_message(self, user_id: Union[int, str], send_message_obj: MessageChain):
        return await self.im.send_direct_message(user_id, send_message_obj)


__all__ = ["DiscordAdapter"]
