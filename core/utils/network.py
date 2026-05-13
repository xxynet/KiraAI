import time
import httpx
from typing import Optional

from core.logging_manager import get_logger

logger = get_logger("network", "cyan")


async def download_file(url: str, path: str, proxy: Optional[str] = None, timeout: float = 60.0):
    client_kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            with open(path, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    f.write(chunk)
        return resp


async def get_file_content(url: str, proxy: Optional[str] = None, timeout: float = 60.0) -> bytes:
    client_kwargs: dict = {"follow_redirects": True, "timeout": timeout}
    if proxy:
        client_kwargs["proxy"] = proxy
    async with httpx.AsyncClient(**client_kwargs) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


async def test_url_speed(
    url: str,
    proxy: Optional[str] = None,
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

    test_url = "https://github.com/xxynet/KiraAI/archive/refs/tags/v2.9.1.zip"

    result = asyncio.run(test_url_speed(test_url))
    logger.info(result)

    for proxy_url in proxies:
        url = f"{proxy_url.rstrip('/')}/https://github.com/xxynet/KiraAI/archive/refs/tags/v2.9.1.zip"
        result = asyncio.run(test_url_speed(url))
        logger.info(result)