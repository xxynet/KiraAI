import asyncio
import ipaddress
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from core.logging_manager import get_logger

logger = get_logger("network", "cyan")

# Fake-IP proxies (Clash/Surge/sing-box TUN mode) answer every DNS query with an
# address from the RFC 2544 benchmarking range and resolve the real host
# themselves, so a local lookup cannot classify the destination. Rejecting the
# range would block every domain URL on those hosts.
_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def _is_public_address(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    if address.version == 4 and address in _FAKE_IP_NETWORK:
        return True
    return address.is_global


async def is_public_http_url(url: str) -> bool:
    """Return True only when every resolved address of an HTTP URL is public.

    This is a guard for URLs that originate from adapter messages or model
    output. It deliberately rejects loopback, private, link-local, reserved and
    metadata-style addresses before any request is made.
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return False
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        infos = await asyncio.get_running_loop().getaddrinfo(
            parsed.hostname, port, type=socket.SOCK_STREAM,
        )
    except (OSError, ValueError):
        return False
    if not infos:
        return False
    return all(_is_public_address(info[4][0]) for info in infos)


async def get_json(url: str, timeout: float = 60.0) -> Any:
    """Fetch and decode a JSON response, propagating HTTP and decoding errors."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.json()


async def download_file(
    url: str,
    path: str,
    proxy: str | None = None,
    timeout: float = 60.0,
    max_bytes: int | None = None,
):
    if max_bytes is not None and max_bytes <= 0:
        raise ValueError("max_bytes must be a positive integer")

    client_kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            content_length = resp.headers.get("content-length")
            if max_bytes is not None and content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > max_bytes:
                    raise ValueError(f"Download exceeds the {max_bytes} byte limit")

            downloaded_bytes = 0
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    downloaded_bytes += len(chunk)
                    if max_bytes is not None and downloaded_bytes > max_bytes:
                        raise ValueError(f"Download exceeds the {max_bytes} byte limit")
                    f.write(chunk)
        return resp


async def get_file_content(url: str, proxy: str | None = None, timeout: float = 60.0) -> bytes:
    client_kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def test_url_speed(
    url: str,
    proxy: str | None = None,
    timeout: float = 10.0,
) -> dict:
    """
    Test the connection speed to a URL by sending a HEAD request.
    Only measures latency (TTFB); does NOT download the response body.

    Returns a dict with:
      url            — the tested URL
      status_code    — HTTP status code
      latency        — time (seconds) until response headers are received
      error          — error message if the request failed, else None
    """
    result: dict = {
        "url": url,
        "status_code": None,
        "latency": None,
        "error": None,
    }

    client_kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    if proxy:
        client_kwargs["proxy"] = proxy

    try:
        async with httpx.AsyncClient(**client_kwargs) as client:
            start = time.monotonic()
            resp = await client.head(url)
            latency = time.monotonic() - start
            resp.raise_for_status()

        result["status_code"] = resp.status_code
        result["latency"] = round(latency, 4)

    except httpx.HTTPStatusError as e:
        result["status_code"] = e.response.status_code
        result["error"] = f"HTTP {e.response.status_code}"
    except httpx.TimeoutException:
        result["error"] = f"Timeout after {timeout}s"
    except httpx.HTTPError as e:
        result["error"] = str(e)

    return result

if __name__ == "__main__":
    import asyncio

    proxies = [
        "https://gh-proxy.com/",
        "https://gh-proxy.org/",
        "https://hk.gh-proxy.org/",
        "https://cdn.gh-proxy.org/",
        "https://edgeone.gh-proxy.org/"
    ]

    test_url = "https://github.com/KiraAI-Dev/KiraAI/archive/refs/tags/v2.9.1.zip"

    result = asyncio.run(test_url_speed(test_url))
    logger.info(result)

    for proxy_url in proxies:
        url = f"{proxy_url.rstrip('/')}/https://github.com/KiraAI-Dev/KiraAI/archive/refs/tags/v2.9.1.zip"
        result = asyncio.run(test_url_speed(url))
        logger.info(result)
