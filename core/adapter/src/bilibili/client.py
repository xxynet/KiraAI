from __future__ import annotations

from bilibili_api.utils import network


def get_bilibili_client() -> network.BiliAPIClient:
    """Configure the SDK-owned client shared by adapters and QR login."""
    network.select_client("aiohttp")
    client = network.get_client()
    client.get_wrapped_session().headers["Accept-Encoding"] = "gzip, deflate"
    return client
