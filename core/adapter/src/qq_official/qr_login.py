from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from core.adapter.qr_login import (
    QRCodeLoginHandler,
    QRCodeLoginPollResult,
    QRCodeLoginStartResult,
)


class QQOfficialQRCodeLoginHandler(QRCodeLoginHandler):
    def __init__(
        self,
        config: dict[str, Any],
        *,
        bind_host: str,
        generate_bind_key: Callable[[], str],
        post_binding_json: Callable[[str, dict[str, str]], Awaitable[dict[str, Any]]],
        decrypt_secret: Callable[[str, str], str],
    ) -> None:
        self.config = dict(config)
        self.bind_host = bind_host
        self.generate_bind_key = generate_bind_key
        self.post_binding_json = post_binding_json
        self.decrypt_secret = decrypt_secret
        self.task_id = ""
        self.bind_key = ""

    async def start(self) -> QRCodeLoginStartResult:
        self.bind_key = self.generate_bind_key()
        result = await self.post_binding_json(
            "/lite/create_bind_task",
            {"key": self.bind_key},
        )
        self.task_id = str(result.get("task_id", "")).strip()
        if not self.task_id:
            raise RuntimeError("QQ official bot binding response is missing task_id")
        return QRCodeLoginStartResult(
            qr_content=(
                f"https://{self.bind_host}/qqbot/openclaw/connect.html?"
                f"task_id={quote(self.task_id, safe='')}&_wv=2"
            ),
            poll_interval=2,
            expires_in=300,
        )

    async def poll(self) -> QRCodeLoginPollResult:
        if not self.task_id or not self.bind_key:
            return QRCodeLoginPollResult(
                status="error",
                message="QR-code login has not been started",
            )
        result = await self.post_binding_json(
            "/lite/poll_bind_result",
            {"task_id": self.task_id},
        )
        try:
            status = int(result.get("status", 0))
        except (TypeError, ValueError):
            status = 0
        if status == 3:
            return QRCodeLoginPollResult(
                status="expired",
                message="QR code expired",
            )
        if status != 2:
            return QRCodeLoginPollResult(status="pending")

        app_id = str(result.get("bot_appid", "")).strip()
        encrypted_secret = str(result.get("bot_encrypt_secret", "")).strip()
        if not app_id or not encrypted_secret:
            return QRCodeLoginPollResult(
                status="error",
                message="QQ official bot QR login returned incomplete credentials",
            )
        app_secret = self.decrypt_secret(encrypted_secret, self.bind_key)
        config_patch: dict[str, Any] = {
            "app_id": app_id,
            "app_secret": app_secret,
        }
        scanner_openid = str(result.get("user_openid", "")).strip()
        if scanner_openid and self.config.get("permission_mode", "allow_list") == "allow_list":
            user_allow_list = list(self.config.get("user_allow_list") or [])
            if scanner_openid not in {str(entry) for entry in user_allow_list}:
                user_allow_list.append(scanner_openid)
            config_patch["user_allow_list"] = user_allow_list
        return QRCodeLoginPollResult(
            status="confirmed",
            config_patch=config_patch,
        )

    async def close(self) -> None:
        self.task_id = ""
        self.bind_key = ""
