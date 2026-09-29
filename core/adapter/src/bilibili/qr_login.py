from __future__ import annotations

import asyncio
from typing import Any

import httpx
from bilibili_api.utils import network

from core.adapter.qr_login import (
    QRCodeLoginHandler,
    QRCodeLoginPollResult,
    QRCodeLoginStartResult,
)

from .client import get_bilibili_client


QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"
REQUEST_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://passport.bilibili.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
}


class BiliBiliQRCodeLoginHandler(QRCodeLoginHandler):
    """Use Bilibili's web QR endpoints independently of bilibili-api login."""

    def __init__(self, *, http_client: httpx.AsyncClient | None = None):
        self._owns_http_client = http_client is None
        self._http_client = http_client if http_client is not None else httpx.AsyncClient(
            headers=REQUEST_HEADERS, follow_redirects=True, timeout=10.0,
        )
        self._qrcode_key = ""
        self._buvid3 = ""

    async def _request_data(
        self, url: str, *, params: dict[str, str] | None = None,
    ) -> tuple[httpx.Response, dict[str, Any]]:
        try:
            response = await self._http_client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException:
            raise TimeoutError("adapter.qrcode_failed") from None
        except (httpx.HTTPError, ValueError):
            # Request URLs, response bodies and exceptions may contain login secrets.
            raise RuntimeError("adapter.qrcode_failed") from None
        if not isinstance(payload, dict) or payload.get("code") != 0:
            raise RuntimeError("adapter.qrcode_failed")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise RuntimeError("adapter.qrcode_invalid_response")
        return response, data

    async def start(self) -> QRCodeLoginStartResult:
        self._qrcode_key = ""
        self._buvid3 = ""
        self._http_client.cookies.clear()
        try:
            get_bilibili_client()
            buvid3, buvid4 = await asyncio.wait_for(network.get_buvid(), timeout=10.0)
        except Exception:
            raise RuntimeError("adapter.qrcode_failed") from None
        if not isinstance(buvid3, str) or not buvid3 or not isinstance(buvid4, str) or not buvid4:
            raise RuntimeError("adapter.qrcode_invalid_response")
        self._buvid3 = buvid3
        self._http_client.cookies.set("buvid3", buvid3, domain=".bilibili.com", path="/")
        self._http_client.cookies.set("buvid4", buvid4, domain=".bilibili.com", path="/")
        _, data = await self._request_data(QR_GENERATE_URL)
        key = data.get("qrcode_key")
        url = data.get("url")
        if not isinstance(key, str) or not key or not isinstance(url, str) or not url:
            raise RuntimeError("adapter.qrcode_invalid_response")
        self._qrcode_key = key
        return QRCodeLoginStartResult(qr_content=url, poll_interval=2, expires_in=180)

    async def poll(self) -> QRCodeLoginPollResult:
        if not self._qrcode_key:
            return QRCodeLoginPollResult(
                status="error", message="adapter.qrcode_failed",
            )
        try:
            response, data = await self._request_data(
                QR_POLL_URL, params={"qrcode_key": self._qrcode_key},
            )
        except TimeoutError:
            return QRCodeLoginPollResult(status="pending")
        except RuntimeError as exc:
            return QRCodeLoginPollResult(status="error", message=str(exc))

        code = data.get("code")
        if code in (86101, 86090):
            return QRCodeLoginPollResult(status="pending")
        if code == 86038:
            return QRCodeLoginPollResult(status="expired")
        if code != 0:
            return QRCodeLoginPollResult(
                status="error", message="adapter.qrcode_invalid_response",
            )

        cookies = {cookie.name: cookie.value for cookie in self._http_client.cookies.jar}
        for current_response in (*response.history, response):
            for cookie in current_response.cookies.jar:
                cookies[cookie.name] = cookie.value
        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            return QRCodeLoginPollResult(
                status="error", message="adapter.qrcode_incomplete_credentials",
            )
        return QRCodeLoginPollResult(
            status="confirmed",
            config_patch={
                "sessdata": cookies["SESSDATA"],
                "bili_jct": cookies["bili_jct"],
                "buvid3": cookies.get("buvid3") or self._buvid3,
                "dedeuserid": cookies.get("DedeUserID", ""),
                "bot_uid": cookies.get("DedeUserID", ""),
                "ac_time_value": str(data.get("refresh_token") or ""),
            },
        )

    async def close(self) -> None:
        self._qrcode_key = ""
        self._buvid3 = ""
        if self._owns_http_client:
            await self._http_client.aclose()
        self._http_client.cookies.clear()
