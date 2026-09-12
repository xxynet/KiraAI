from __future__ import annotations

from typing import Any

import httpx

from core.adapter.qr_login import (
    QRCodeLoginHandler,
    QRCodeLoginPollResult,
    QRCodeLoginStartResult,
)

from .weixin_oc_client import WeixinOCClient


class WeixinOCQRCodeLoginHandler(QRCodeLoginHandler):
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = dict(config)
        self.base_url = str(
            (self.config.get("weixin_oc_base_url") or "https://ilinkai.weixin.qq.com")
        ).rstrip("/")
        self.bot_type = str(self.config.get("weixin_oc_bot_type") or "3")
        self.api_timeout_ms = int(self.config.get("weixin_oc_api_timeout_ms", 15000))
        self.long_poll_timeout_ms = int(
            self.config.get("weixin_oc_long_poll_timeout_ms", 35000)
        )
        self.poll_interval = max(
            1,
            int(self.config.get("weixin_oc_qr_poll_interval", 1)),
        )
        self.qrcode = ""
        self.client = WeixinOCClient(
            adapter_id="weixin_oc_qrcode_login",
            base_url=self.base_url,
            cdn_base_url=str(
                self.config.get("weixin_oc_cdn_base_url")
                or "https://novac2c.cdn.weixin.qq.com/c2c"
            ).rstrip("/"),
            api_timeout_ms=self.api_timeout_ms,
        )

    async def start(self) -> QRCodeLoginStartResult:
        try:
            data = await self.client.request_json(
                "GET",
                "ilink/bot/get_bot_qrcode",
                params={"bot_type": self.bot_type},
                token_required=False,
                timeout_ms=15_000,
            )
        finally:
            await self.client.close()
        self.qrcode = str(data.get("qrcode", "")).strip()
        qr_content = str(data.get("qrcode_img_content", "")).strip()
        if not self.qrcode or not qr_content:
            raise RuntimeError("qrcode response missing qrcode or qrcode_img_content")
        return QRCodeLoginStartResult(
            qr_content=qr_content,
            poll_interval=self.poll_interval,
            expires_in=300,
        )

    async def poll(self) -> QRCodeLoginPollResult:
        if not self.qrcode:
            return QRCodeLoginPollResult(
                status="error",
                message="QR-code login has not been started",
            )
        try:
            try:
                data = await self.client.request_json(
                    "GET",
                    "ilink/bot/get_qrcode_status",
                    params={"qrcode": self.qrcode},
                    token_required=False,
                    timeout_ms=self.long_poll_timeout_ms,
                    headers={"iLink-App-ClientVersion": "1"},
                )
            except httpx.TimeoutException:
                return QRCodeLoginPollResult(status="pending")
        finally:
            await self.client.close()

        status = str(data.get("status", "wait")).strip()
        if status == "expired":
            return QRCodeLoginPollResult(
                status="expired",
                message="QR code expired",
            )
        if status in {"cancel", "canceled", "denied"}:
            return QRCodeLoginPollResult(
                status="denied",
                message="Login was cancelled",
            )
        if status != "confirmed":
            return QRCodeLoginPollResult(status="pending")

        token = str(data.get("bot_token", "")).strip()
        if not token:
            return QRCodeLoginPollResult(
                status="error",
                message="Login succeeded but no bot token was returned",
            )
        account_id = str(data.get("ilink_bot_id", "")).strip()
        base_url = str(data.get("baseurl", "")).strip() or self.base_url
        return QRCodeLoginPollResult(
            status="confirmed",
            config_patch={
                "weixin_oc_token": token,
                "weixin_oc_account_id": account_id,
                "weixin_oc_base_url": base_url.rstrip("/"),
            },
        )

    async def close(self) -> None:
        self.qrcode = ""
        await self.client.close()
