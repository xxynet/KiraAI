import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.adapter.qr_login import (
    QRCodeLoginHandler,
    QRCodeLoginPollResult,
    QRCodeLoginStartResult,
)
from core.adapter.src.qq_official.qr_login import QQOfficialQRCodeLoginHandler
from core.adapter.src.weixin_oc.qr_login import WeixinOCQRCodeLoginHandler
from core.adapter.src.weixin_oc.weixin_oc import WeixinOCAdapter
from webui.models import QRCodeLoginStartRequest
from webui.routes.adapters import AdaptersRoutes


@pytest.mark.asyncio
async def test_qq_official_qrcode_handler_returns_config_patch():
    calls = []

    async def post_binding_json(path, payload):
        calls.append((path, payload))
        if path == "/lite/create_bind_task":
            return {"task_id": "task-id"}
        return {
            "status": 2,
            "bot_appid": "app-id",
            "bot_encrypt_secret": "encrypted-secret",
            "user_openid": "scanner-openid",
        }

    handler = QQOfficialQRCodeLoginHandler(
        {"permission_mode": "allow_list", "user_allow_list": ["existing"]},
        bind_host="q.qq.com",
        generate_bind_key=lambda: "bind-key",
        post_binding_json=post_binding_json,
        decrypt_secret=lambda encrypted, key: f"secret:{encrypted}:{key}",
    )

    started = await handler.start()
    result = await handler.poll()

    assert started.qr_content == (
        "https://q.qq.com/qqbot/openclaw/connect.html?task_id=task-id&_wv=2"
    )
    assert started.poll_interval == 2
    assert result.status == "confirmed"
    assert result.config_patch == {
        "app_id": "app-id",
        "app_secret": "secret:encrypted-secret:bind-key",
        "user_allow_list": ["existing", "scanner-openid"],
    }
    assert calls == [
        ("/lite/create_bind_task", {"key": "bind-key"}),
        ("/lite/poll_bind_result", {"task_id": "task-id"}),
    ]


@pytest.mark.asyncio
async def test_weixin_oc_qrcode_handler_returns_config_patch(monkeypatch):
    handler = WeixinOCQRCodeLoginHandler({})
    responses = [
        {"qrcode": "qr-id", "qrcode_img_content": "weixin-login-content"},
        {
            "status": "confirmed",
            "bot_token": "bot-token",
            "ilink_bot_id": "account-id",
            "baseurl": "https://example.weixin.test/",
        },
    ]
    closed = 0

    async def request_json(*args, **kwargs):
        return responses.pop(0)

    async def close():
        nonlocal closed
        closed += 1

    monkeypatch.setattr(handler.client, "request_json", request_json)
    monkeypatch.setattr(handler.client, "close", close)

    started = await handler.start()
    result = await handler.poll()

    assert started.qr_content == "weixin-login-content"
    assert started.poll_interval == 1
    assert result.status == "confirmed"
    assert result.config_patch == {
        "weixin_oc_token": "bot-token",
        "weixin_oc_account_id": "account-id",
        "weixin_oc_base_url": "https://example.weixin.test",
    }
    assert closed == 2


@pytest.mark.asyncio
async def test_weixin_oc_empty_token_does_not_start_adapter(monkeypatch):
    adapter = WeixinOCAdapter(
        AdapterInfo(
            adapter_id="weixin-oc-test",
            enabled=True,
            name="weixin_oc",
            platform="weixin_oc",
            config={},
        ),
        asyncio.Queue(),
    )
    run_loop_started = False

    async def fake_run_loop():
        nonlocal run_loop_started
        run_loop_started = True

    monkeypatch.setattr(adapter, "_run_loop", fake_run_loop)

    await adapter.start()
    await asyncio.sleep(0)

    assert adapter.token is None
    assert not run_loop_started
    assert not hasattr(adapter, "_login_session")
    await adapter.client.close()


class _FakeQRCodeLoginHandler(QRCodeLoginHandler):
    def __init__(self):
        self.closed = False

    async def start(self):
        return QRCodeLoginStartResult(
            qr_content="test-content",
            poll_interval=3,
            expires_in=120,
        )

    async def poll(self):
        return QRCodeLoginPollResult(
            status="confirmed",
            config_patch={"token": "filled"},
        )

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_adapter_routes_manage_qrcode_login_session():
    handler = _FakeQRCodeLoginHandler()

    class FakeAdapter:
        @classmethod
        def create_qrcode_login_handler(cls, config):
            assert config == {"existing": "value"}
            return handler

    class FakeAdapterManager:
        @staticmethod
        def get_manifest(platform):
            assert platform == "fake"
            return {"login_method": "qrcode"}

        @staticmethod
        def get_adapter_class(platform):
            assert platform == "fake"
            return FakeAdapter

    routes = AdaptersRoutes(
        None,
        SimpleNamespace(adapter_manager=FakeAdapterManager()),
    )

    started = await routes.start_qrcode_login(
        "fake",
        QRCodeLoginStartRequest(config={"existing": "value"}),
    )
    polled = await routes.poll_qrcode_login(started["session_id"])

    assert started["qrcode_image"].startswith("data:image/svg+xml;base64,")
    assert started["poll_interval"] == 3
    assert polled == {
        "status": "confirmed",
        "config_patch": {"token": "filled"},
        "message": "",
    }
    assert handler.closed


@pytest.mark.parametrize("platform", ["qq_official", "weixin_oc"])
def test_qrcode_login_manifest_matches_adapter_factory(platform):
    adapter_root = Path(__file__).parents[1] / "core" / "adapter" / "src" / platform
    manifest = json.loads((adapter_root / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["login_method"] == "qrcode"
