from __future__ import annotations

import asyncio
import logging
from typing import Union

from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters

from core.adapter.access import ListAccessPolicy
from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.chat import MessageChain
from core.logging_manager import get_logger

from .im import MessageSender, TelegramIMCapability


logger = get_logger("tg_adapter", "green")

TELEGRAM_SHUTDOWN_TIMEOUT = 5.0


class _TelegramShutdownCancellationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exception = record.exc_info[1] if record.exc_info else None
        return not (
            record.name == "telegram.ext.Application"
            and isinstance(exception, asyncio.CancelledError)
            and record.getMessage().startswith("Fetching updates was aborted")
        )


class TelegramAdapter(BaseAdapter):
    """Telegram adapter"""

    def __init__(self, ctx: AdapterContext):
        super().__init__(ctx)
        self.logger = get_logger(self.info.name, "green")

        # config
        self.bot_token: str = self.config.get("bot_token", "")

        # runtime
        base_url = self.config.get("base_url", "https://api.telegram.org/bot")
        if not base_url:
            base_url = "https://api.telegram.org/bot"

        base_file_url = self.config.get("base_file_url", "https://api.telegram.org/file/bot")
        if not base_file_url:
            base_file_url = "https://api.telegram.org/file/bot"

        self.base_url = base_url
        self.base_file_url = base_file_url

        self.app = (
            ApplicationBuilder()
            .token(self.bot_token)
            .base_url(base_url)
            .base_file_url(base_file_url)
            .get_updates_connection_pool_size(2)
            .get_updates_pool_timeout(5.0)
            .build()
        )
        self._lifecycle_lock = asyncio.Lock()
        self._run_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()
        self._resources_started = True
        self._accepting_messages = False
        self._message_tasks: set[asyncio.Task] = set()
        self.message_sender = MessageSender()
        self.im = self.register_capability(IMCapability, TelegramIMCapability(self))
        self._configure_access()
        self.app.add_handler(CommandHandler("start", self.im._cmd_start))
        self.app.add_handler(CommandHandler("help", self.im._cmd_help))
        self.app.add_handler(MessageHandler(filters.ALL, self._on_message))

    async def start(self) -> None:
        async with self._lifecycle_lock:
            existing = self._run_task and not self._run_task.done()
            if not existing:
                self._shutdown_event.clear()
                self._resources_started = True
                await self._start()
                self._run_task = asyncio.create_task(self._run(), name=f"telegram:{self.info.name}")
            task = self._run_task
        if existing:
            await asyncio.shield(task)
            return
        try:
            await task
        finally:
            async with self._lifecycle_lock:
                if self._run_task is task:
                    await self._stop()

    async def _run(self) -> None:
        try:
            await self._shutdown_event.wait()
        finally:
            async with self._lifecycle_lock:
                await self._stop()

    async def _start(self):
        """Start the Telegram adapter asynchronously"""
        if not self.bot_token:
            logger.error("Telegram bot_token is not set")
            raise ValueError("Telegram bot token is required")

        if self.app.running:
            return

        # Initialize and start the application asynchronously
        try:
            await self.app.initialize()
            await self.app.start()
            self._accepting_messages = True
            # Start polling, drop any pending updates that accumulated while the bot was offline
            await self.app.updater.start_polling(
                drop_pending_updates=True,
                error_callback=lambda e: logger.error("[%s] Polling error (%s)", self.info.name, type(e).__name__)
            )

            logger.info(f"start listening incoming messages for {self.config.get('bot_pid', 'your bot account')}")
        except asyncio.CancelledError:
            await self._stop()
            raise
        except Exception as e:
            logger.error("Failed to start Telegram (%s)", type(e).__name__)
            await self._stop()
            raise

    async def stop(self) -> None:
        if hasattr(self, "_shutdown_event"):
            self._shutdown_event.set()
        async with self._lifecycle_lock:
            await self._stop()
        task = getattr(self, "_run_task", None)
        if task and task is not asyncio.current_task():
            await asyncio.gather(task, return_exceptions=True)

    async def _stop(self):
        """Stop the Telegram adapter asynchronously"""
        if not getattr(self, "_resources_started", True):
            return

        self._accepting_messages = False
        await self._cancel_message_tasks()
        if not self.app:
            return

        shutdown_steps = []
        if self.app.updater and self.app.updater.running:
            shutdown_steps.append(("updater", self.app.updater.stop))
        if self.app.running:
            shutdown_steps.append(("application", self.app.stop))
        shutdown_steps.append(("HTTP client", self.app.shutdown))
        application_logger = logging.getLogger("telegram.ext.Application")
        cancellation_filter = _TelegramShutdownCancellationFilter()
        application_logger.addFilter(cancellation_filter)
        try:
            for component, shutdown in shutdown_steps:
                try:
                    shutdown_task = asyncio.create_task(shutdown())
                    try:
                        done, _ = await asyncio.wait(
                            {shutdown_task}, timeout=TELEGRAM_SHUTDOWN_TIMEOUT
                        )
                    except asyncio.CancelledError:
                        shutdown_task.cancel()
                        await asyncio.gather(shutdown_task, return_exceptions=True)
                        raise
                    if not done:
                        shutdown_task.cancel()
                        await asyncio.gather(shutdown_task, return_exceptions=True)
                        logger.warning(
                            f"Telegram {component} stop timed out after "
                            f"{TELEGRAM_SHUTDOWN_TIMEOUT:.0f}s; continuing cleanup"
                        )
                    elif shutdown_task.cancelled():
                        logger.warning(
                            f"Telegram {component} stop was cancelled; continuing cleanup"
                        )
                    else:
                        shutdown_task.result()
                except Exception as e:
                    logger.error("Error stopping Telegram %s (%s)", component, type(e).__name__)
        finally:
            application_logger.removeFilter(cancellation_filter)

        self._resources_started = False
        logger.info(f"Stopped listening messages for {self.config.get('bot_pid', 'your bot account')}")

    async def _on_message(self, update, context):
        if not self._accepting_messages:
            return
        task = asyncio.current_task()
        self._message_tasks.add(task)
        try:
            await self.im._on_message(update, context)
        finally:
            self._message_tasks.discard(task)

    async def _cancel_message_tasks(self):
        tasks = [task for task in self._message_tasks if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_client(self):
        return self.app

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


__all__ = ["TelegramAdapter"]
