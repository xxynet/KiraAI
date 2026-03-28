from typing import Optional, Tuple
import httpx
import asyncio


def parse_github_url(url: str) -> Tuple[str, str]:
    """
    Parse a GitHub URL or 'owner/repo' shorthand into (owner, repo).
    Accepted formats:
      - https://github.com/owner/repo
      - https://github.com/owner/repo/tree/branch  (extra path is ignored)
      - owner/repo
    """
    url = url.strip().rstrip("/")
    if "github.com/" in url:
        path = url.split("github.com/", 1)[1]
    elif url.startswith("http"):
        raise ValueError(f"Not a GitHub URL: {url}")
    else:
        path = url

    parts = path.strip("/").split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Cannot parse owner/repo from: {url}")
    return parts[0], parts[1]


async def get_latest_release(owner: str, repo: str, proxy: Optional[str] = None):
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/latest"
    client_kwargs: dict = {"timeout": 10.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Failed to get latest release: {e}")
            return None

    data = resp.json()
    return {
        "tag_name": data.get("tag_name"),
        "name": data.get("name"),
        "body": data.get("body"),
        "html_url": data.get("html_url"),
        "published_at": data.get("published_at")
    }


async def download_zipball(
    owner: str,
    repo: str,
    proxy: Optional[str] = None,
    gh_proxy: Optional[str] = None,
) -> bytes:
    """
    Download the default branch zip archive of a GitHub repository.

    proxy    — standard HTTP/SOCKS proxy passed to httpx (e.g. "http://127.0.0.1:7890")
    gh_proxy — GitHub reverse-proxy base URL; the direct download link is appended to it
               (e.g. "https://ghproxy.com/" → "https://ghproxy.com/https://github.com/...")

    When gh_proxy is set the direct archive URL is used instead of the API endpoint,
    because most gh_proxy services only handle github.com/* URLs.

    Raises ValueError on HTTP errors, ConnectionError on network failures.
    """
    if gh_proxy:
        base = gh_proxy.rstrip("/")
        direct_url = f"https://github.com/{owner}/{repo}/archive/HEAD.zip"
        url = f"{base}/{direct_url}"
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/zipball"

    client_kwargs: dict = {"timeout": 60.0, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                raise ValueError(f"Repository {owner}/{repo} not found") from e
            raise ValueError(f"GitHub returned HTTP {status}") from e
        except httpx.HTTPError as e:
            raise ConnectionError(f"Network error while downloading from GitHub: {e}") from e

    return resp.content


if __name__ == '__main__':
    print(asyncio.run(get_latest_release("xxynet", "KiraAI")))
