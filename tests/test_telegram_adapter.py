import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from core.adapter.src.telegram.telegram import (
    TelegramAdapter,
    _TelegramShutdownCancellationFilter,
)
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
