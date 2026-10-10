import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.chat.message_history_cleanup import MessageHistoryCleanup
from core.launcher import KiraLauncher
from core.lifecycle import KiraLifecycle


@pytest.mark.anyio
async def test_launcher_finishes_shutdown_after_history_cleanup_was_cancelled(monkeypatch):
    lifecycle = KiraLifecycle(stats=Mock())
    lifecycle.message_history_cleanup = MessageHistoryCleanup(
        None, {"bot_config": {"message_history_cleanup": {"enabled": False}}},
    )
    lifecycle.db_manager = SimpleNamespace(dispose=AsyncMock())

    async def interrupted_run():
        lifecycle.message_history_cleanup.start()
        task = lifecycle.message_history_cleanup._task
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        raise asyncio.CancelledError

    monkeypatch.setattr(lifecycle, "init_and_run_system", interrupted_run)
    monkeypatch.setattr("core.launcher.KiraLifecycle", lambda **kwargs: lifecycle)
    monkeypatch.setattr("core.launcher.Statistics", Mock())
    monkeypatch.setattr("core.launcher.KiraWebUI", lambda **kwargs: SimpleNamespace(
        run=AsyncMock(), access_token="",
    ))
    monkeypatch.setattr("core.utils.dist_checker.ensure_dist", AsyncMock())
    monkeypatch.setattr("core.lifecycle.event_handler_reg.get_handlers", lambda event: [])
    launcher = KiraLauncher()
    launcher.logger = Mock()
    monkeypatch.setattr(launcher, "_load_webui_config", lambda: {"host": "127.0.0.1", "port": 5267})
    loop = asyncio.get_running_loop()
    handler = loop.get_exception_handler()
    try:
        await launcher.start()
    finally:
        loop.set_exception_handler(handler)

    lifecycle.db_manager.dispose.assert_awaited_once()
    assert lifecycle.message_history_cleanup._task is None
    assert [call.args[0] for call in launcher.logger.info.call_args_list][-2:] == [
        "✨ Exiting KiraAI...", "✔ Exited KiraAI",
    ]
