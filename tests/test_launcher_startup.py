import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.launcher import KiraLauncher


@pytest.mark.anyio
@pytest.mark.parametrize(
    "host, disable_auth, ip_error",
    [
        ("127.0.0.1", False, False),
        ("localhost", False, False),
        ("0.0.0.0", False, False),
        ("0.0.0.0", False, True),
        ("0.0.0.0", True, False),
    ],
)
async def test_webui_info_is_logged_after_initialization(monkeypatch, host, disable_auth, ip_error):
    launcher = KiraLauncher(disable_webui_auth=disable_auth)
    launcher.logger = Mock()
    webui = SimpleNamespace(run=AsyncMock(), access_token="test-token")
    addresses = Mock(return_value=[("Ethernet", "192.0.2.1"), ("Local", "127.0.0.1")])
    if ip_error:
        addresses.side_effect = OSError("interfaces unavailable")

    async def initialize(on_initialized):
        await asyncio.sleep(0)
        launcher.logger.info.assert_not_called()
        on_initialized()

    monkeypatch.setattr("core.launcher.KiraLifecycle", lambda **kwargs: SimpleNamespace(
        init_and_run_system=initialize,
    ))
    monkeypatch.setattr("core.launcher.Statistics", Mock())
    monkeypatch.setattr("core.launcher.KiraWebUI", lambda **kwargs: webui)
    monkeypatch.setattr("core.utils.dist_checker.ensure_dist", AsyncMock())
    monkeypatch.setattr(launcher, "_load_webui_config", lambda: {"host": host, "port": 5267})
    monkeypatch.setattr(launcher, "_get_ip_addresses", addresses)
    loop = asyncio.get_running_loop()
    handler = loop.get_exception_handler()
    try:
        await launcher.start()
    finally:
        loop.set_exception_handler(handler)

    effective_host = "127.0.0.1" if disable_auth else host
    webui.run.assert_awaited_once_with(effective_host, 5267)
    messages = [call.args[0] for call in launcher.logger.info.call_args_list]
    assert messages[0] == f"WebUI server started at http://{effective_host}:5267"
    assert messages.count("Access Token: test-token") == (0 if disable_auth else 1)
    if not disable_auth:
        assert messages[-1] == "Access Token: test-token"
    if effective_host in ("localhost", "127.0.0.1"):
        addresses.assert_not_called()
    elif ip_error:
        launcher.logger.warning.assert_called_once_with(
            "Failed to get ip addresses: interfaces unavailable",
        )
    else:
        assert messages.index("Local: http://127.0.0.1:5267") < messages.index("Ethernet: http://192.0.2.1:5267")


@pytest.mark.anyio
async def test_failed_initialization_does_not_log_webui_info(monkeypatch):
    launcher = KiraLauncher()
    launcher.logger = Mock()
    monkeypatch.setattr("core.launcher.KiraLifecycle", lambda **kwargs: SimpleNamespace(
        init_and_run_system=AsyncMock(side_effect=RuntimeError("initialization failed")),
    ))
    monkeypatch.setattr("core.launcher.Statistics", Mock())
    monkeypatch.setattr("core.launcher.KiraWebUI", lambda **kwargs: SimpleNamespace(
        run=AsyncMock(), access_token="test-token",
    ))
    monkeypatch.setattr("core.utils.dist_checker.ensure_dist", AsyncMock())
    monkeypatch.setattr(launcher, "_load_webui_config", lambda: {"host": "127.0.0.1", "port": 5267})
    loop = asyncio.get_running_loop()
    handler = loop.get_exception_handler()
    try:
        with pytest.raises(RuntimeError, match="initialization failed"):
            await launcher.start()
    finally:
        loop.set_exception_handler(handler)

    launcher.logger.info.assert_not_called()
