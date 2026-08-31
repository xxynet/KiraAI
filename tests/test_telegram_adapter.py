import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.adapter.src.telegram.telegram import (
    TelegramAdapter,
    _TelegramShutdownCancellationFilter,
)
from core.adapter.src.discord.discord import DiscordAdapter
from core.adapter.adapter_registry import AdapterManager
from core.adapter.adapter_info import AdapterInfo


def test_uses_a_separate_get_updates_connection_for_shutdown_cleanup():
    builder = Mock()
    builder.token.return_value = builder
    builder.base_url.return_value = builder
    builder.base_file_url.return_value = builder
    builder.get_updates_connection_pool_size.return_value = builder
    builder.get_updates_pool_timeout.return_value = builder

    info = AdapterInfo(
        adapter_id="telegram-test",
        enabled=True,
        name="telegram-test",
        platform="Telegram",
        description="",
        config={"bot_token": "token"},
    )
    with patch(
        "core.adapter.src.telegram.telegram.ApplicationBuilder",
        return_value=builder,
    ):
        TelegramAdapter(info, asyncio.Queue())

    builder.get_updates_connection_pool_size.assert_called_once_with(2)
    builder.get_updates_pool_timeout.assert_called_once_with(5.0)


def test_filters_only_telegram_shutdown_cancellation_log():
    cancellation = asyncio.CancelledError()
    record = logging.LogRecord(
        name="telegram.ext.Application",
        level=logging.CRITICAL,
        pathname="",
        lineno=0,
        msg="Fetching updates was aborted due to %r",
        args=(cancellation,),
        exc_info=(asyncio.CancelledError, cancellation, None),
    )

    assert not _TelegramShutdownCancellationFilter().filter(record)


@pytest.mark.asyncio
async def test_stop_closes_application_after_updater_stop_failure():
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    updater_stop = AsyncMock(side_effect=RuntimeError("connection pool timeout"))
    application_stop = AsyncMock()
    application_shutdown = AsyncMock()
    adapter.app = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=updater_stop),
        running=True,
        stop=application_stop,
        shutdown=application_shutdown,
    )
    adapter.config = {"bot_pid": "test-bot"}

    await adapter.stop()

    updater_stop.assert_awaited_once()
    application_stop.assert_awaited_once()
    application_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_stop_attempts_http_client_shutdown_after_application_stop_failure():
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    updater_stop = AsyncMock()
    application_stop = AsyncMock(side_effect=RuntimeError("application stop failed"))
    application_shutdown = AsyncMock()
    adapter.app = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=updater_stop),
        running=True,
        stop=application_stop,
        shutdown=application_shutdown,
    )
    adapter.config = {"bot_pid": "test-bot"}

    await adapter.stop()

    updater_stop.assert_awaited_once()
    application_stop.assert_awaited_once()
    application_shutdown.assert_awaited_once()

@pytest.mark.asyncio
async def test_stop_continues_after_updater_stop_times_out(monkeypatch):
    monkeypatch.setattr(
        "core.adapter.src.telegram.telegram.TELEGRAM_SHUTDOWN_TIMEOUT", 0.01
    )
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    updater_stop = AsyncMock(side_effect=asyncio.Event().wait)
    application_stop = AsyncMock()
    application_shutdown = AsyncMock()
    adapter.app = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=updater_stop),
        running=True,
        stop=application_stop,
        shutdown=application_shutdown,
    )
    adapter.config = {"bot_pid": "test-bot"}

    await adapter.stop()

    updater_stop.assert_awaited_once()
    application_stop.assert_awaited_once()
    application_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_adapter_stop_timeout_propagates_to_telegram_stop(monkeypatch):
    monkeypatch.setattr("core.adapter.adapter_registry.ADAPTER_STOP_TIMEOUT", 0.01)
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    updater_stop = AsyncMock(side_effect=asyncio.Event().wait)
    application_stop = AsyncMock()
    application_shutdown = AsyncMock()
    adapter.app = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=updater_stop),
        running=True,
        stop=application_stop,
        shutdown=application_shutdown,
    )
    adapter.config = {"bot_pid": "test-bot"}

    manager = AdapterManager.__new__(AdapterManager)
    manager._adapter_tasks = {}
    manager._adapters = {"telegram-test": adapter}

    await manager.stop_adapter("telegram-test")

    updater_stop.assert_awaited_once()
    application_stop.assert_not_awaited()
    application_shutdown.assert_not_awaited()
    assert "telegram-test" not in manager._adapters


@pytest.mark.asyncio
async def test_stop_continues_after_application_stop_is_cancelled():
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    updater_stop = AsyncMock()
    application_stop = AsyncMock(side_effect=asyncio.CancelledError())
    application_shutdown = AsyncMock()
    adapter.app = SimpleNamespace(
        updater=SimpleNamespace(running=True, stop=updater_stop),
        running=True,
        stop=application_stop,
        shutdown=application_shutdown,
    )
    adapter.config = {"bot_pid": "test-bot"}

    await adapter.stop()

    updater_stop.assert_awaited_once()
    application_stop.assert_awaited_once()
    application_shutdown.assert_awaited_once()


@pytest.mark.asyncio
async def test_discord_stop_closes_gateway_before_cancelling_bot_task():
    events = []

    async def wait_for_cancellation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            events.append("bot-task-cancelled")
            raise

    async def close_bot():
        events.append("bot-closed")

    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._bot_task = asyncio.create_task(wait_for_cancellation())
    adapter.bot = SimpleNamespace(
        is_closed=Mock(return_value=False),
        close=AsyncMock(side_effect=close_bot),
    )
    adapter.config = {"bot_pid": "test-bot"}
    adapter.logger = Mock()

    await asyncio.sleep(0)
    await adapter.stop()

    adapter.bot.close.assert_awaited_once()
    assert events == ["bot-closed", "bot-task-cancelled"]


@pytest.mark.asyncio
async def test_discord_stop_propagates_outer_cancellation_after_closing_gateway():
    task_release = asyncio.Event()
    gateway_closed = asyncio.Event()
    task_cancelled = asyncio.Event()

    async def wait_after_cancellation():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            task_cancelled.set()
            await task_release.wait()

    async def close_bot():
        gateway_closed.set()

    adapter = DiscordAdapter.__new__(DiscordAdapter)
    adapter._bot_task = asyncio.create_task(wait_after_cancellation())
    adapter.bot = SimpleNamespace(
        is_closed=Mock(return_value=False),
        close=AsyncMock(side_effect=close_bot),
    )
    adapter.config = {"bot_pid": "test-bot"}
    adapter.logger = Mock()

    await asyncio.sleep(0)
    stop_task = asyncio.create_task(adapter.stop())
    await gateway_closed.wait()
    await task_cancelled.wait()
    stop_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    task_release.set()
    await adapter._bot_task
