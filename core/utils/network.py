import httpx
from typing import Optional


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


async def get_file_content(url: str):
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
