from typing import Optional, Tuple, List
import hashlib
import httpx
import asyncio

from core.utils.network import test_url_speed
from core.logging_manager import get_logger

logger = get_logger("gh_api", "cyan")

GH_PROXY_LIST = [
    "https://gh-proxy.com/",
    "https://gh-proxy.org/",
    "https://hk.gh-proxy.org/",
    "https://cdn.gh-proxy.org/",
    "https://edgeone.gh-proxy.org/",
]


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
    """
    dict_keys(['url', 'assets_url', 'upload_url', 'html_url', 'id', 'author', 
    'node_id', 'tag_name', 'target_commitish', 'name', 'draft', 'immutable', 
    'prerelease', 'created_at', 'updated_at', 'published_at', 'assets', 
    'tarball_url', 'zipball_url', 'body'])
    """
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
        "published_at": data.get("published_at"),
        "prerelease": data.get("prerelease"),
        "draft": data.get("draft"),
    }


async def get_all_releases(
    owner: str,
    repo: str,
    proxy: Optional[str] = None,
    per_page: int = 30,
    max_pages: int = 10,
) -> List[dict]:
    """
    Fetch all releases of a GitHub repository (paginated).

    Returns a list of release dicts, each containing:
      tag_name, name, body, html_url, published_at, prerelease, draft
    Returns an empty list on failure.

    per_page  — results per page (max 100, default 30)
    max_pages — safety cap to avoid excessive pagination
    """
    releases: List[dict] = []
    client_kwargs: dict = {"timeout": 10.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        for page in range(1, max_pages + 1):
            url = (
                f"https://api.github.com/repos/{owner}/{repo}/releases"
                f"?per_page={per_page}&page={page}"
            )
            try:
                resp = await client.get(url)
                resp.raise_for_status()
            except httpx.HTTPError as e:
                print(f"Failed to get releases (page {page}): {e}")
                break

            data = resp.json()
            if not data:
                break

            for item in data:
                releases.append({
                    "tag_name": item.get("tag_name"),
                    "name": item.get("name"),
                    "body": item.get("body"),
                    "html_url": item.get("html_url"),
                    "published_at": item.get("published_at"),
                    "prerelease": item.get("prerelease"),
                    "draft": item.get("draft"),
                })

            # If fewer results than per_page, no more pages
            if len(data) < per_page:
                break

    return releases


async def get_release_assets(
    owner: str,
    repo: str,
    tag: str,
    proxy: Optional[str] = None,
) -> List[dict]:
    """
    Fetch the assets list for a specific release (by tag name).

    Returns a list of asset dicts, each containing:
      name, size, download_url (browser_download_url), content_type, state
    Returns an empty list on failure.
    """
    url = f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}"
    client_kwargs: dict = {"timeout": 10.0}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            print(f"Failed to get release '{tag}': {e}")
            return []

    data = resp.json()
    assets: List[dict] = []
    for item in data.get("assets", []):
        assets.append({
            "name": item.get("name"),
            "size": item.get("size"),
            "download_url": item.get("browser_download_url"),
            "content_type": item.get("content_type"),
            "state": item.get("state"),
            "digest": item.get("digest"),
        })
    return assets


async def download_asset(
    download_url: str,
    proxy: Optional[str] = None,
) -> bytes:
    """
    Download a release asset by its browser_download_url.

    Raises ValueError on HTTP errors, ConnectionError on network failures.
    """
    client_kwargs: dict = {"timeout": 120.0, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.get(download_url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            raise ValueError(f"Failed to download asset (HTTP {status})") from e
        except httpx.HTTPError as e:
            raise ConnectionError(f"Network error while downloading asset: {e}") from e

    return resp.content


def verify_sha256(data: bytes, expected_sha: str) -> bool:
    """
    Verify that the SHA-256 hash of *data* matches *expected_sha*.

    *expected_sha* may or may not be prefixed with "sha256:" — both formats
    (``<hex>`` and ``sha256:<hex>``) are accepted.

    Returns True on match, False otherwise.
    """
    digest = hashlib.sha256(data).hexdigest()
    expected = expected_sha.strip().removeprefix("sha256:").lower()
    return digest == expected


async def download_and_verify_asset(
    owner: str,
    repo: str,
    tag: str,
    expected_sha: str,
    asset_name: str = "dist.zip",
    proxy: Optional[str] = None,
) -> bytes:
    """
    Download a specific release asset and verify its SHA-256 hash.

    1. Looks up assets of the given release tag.
    2. Finds the first asset whose name matches *asset_name*.
    3. Downloads the asset content.
    4. Verifies SHA-256 against *expected_sha*.

    Raises:
      ValueError      — asset not found / HTTP error / SHA mismatch
      ConnectionError — network failure

    Returns the verified file content as bytes on success.
    """
    assets = await get_release_assets(owner, repo, tag, proxy)
    if not assets:
        raise ValueError(f"No assets found for release '{tag}'")

    target = next((a for a in assets if a["name"] == asset_name), None)
    if not target:
        available = [a["name"] for a in assets]
        raise ValueError(
            f"Asset '{asset_name}' not found in release '{tag}'. "
            f"Available: {available}"
        )

    content = await download_asset(target["download_url"], proxy)

    if not verify_sha256(content, expected_sha):
        raise ValueError(
            f"SHA-256 verification failed for '{asset_name}' in release '{tag}'"
        )

    return content


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


async def download_source_zipball(
    owner: str,
    repo: str,
    tag: str,
    proxy: Optional[str] = None,
    gh_proxy: Optional[str] = None,
) -> bytes:
    """
    Download the source code zip archive for a specific release tag.

    proxy    — standard HTTP/SOCKS proxy passed to httpx
    gh_proxy — GitHub reverse-proxy base URL

    Raises ValueError on HTTP errors, ConnectionError on network failures.
    """
    if gh_proxy:
        base = gh_proxy.rstrip("/")
        direct_url = f"https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip"
        url = f"{base}/{direct_url}"
    else:
        url = f"https://api.github.com/repos/{owner}/{repo}/zipball/{tag}"

    client_kwargs: dict = {"timeout": 120.0, "follow_redirects": True}
    if proxy:
        client_kwargs["proxy"] = proxy

    async with httpx.AsyncClient(**client_kwargs) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 404:
                raise ValueError(f"Tag {tag} not found in {owner}/{repo}") from e
            raise ValueError(f"GitHub returned HTTP {status}") from e
        except httpx.HTTPError as e:
            raise ConnectionError(f"Network error while downloading from GitHub: {e}") from e

    return resp.content


async def pick_fastest_source(
    direct_url: str,
    proxy: Optional[str] = None,
    timeout: float = 5.0,
) -> list[str]:
    """
    Speed-test all GitHub proxy candidates + direct GitHub for *direct_url*,
    return a list of download URLs ranked by latency (best first).
    Returns empty list if all fail.
    """
    candidates: list[tuple[str, str]] = [("direct", direct_url)]
    for base in GH_PROXY_LIST:
        label = base.rstrip("/").split("//", 1)[-1]
        candidates.append((label, f"{base.rstrip('/')}/{direct_url}"))

    logger.info(f"Speed-testing {len(candidates)} GitHub sources ...")

    async def _probe(label: str, url: str) -> tuple[str, Optional[float]]:
        try:
            result = await test_url_speed(url, proxy=proxy, timeout=timeout)
            return label, result["latency"]
        except Exception:
            return label, None

    results = await asyncio.gather(*[_probe(l, u) for l, u in candidates])

    for label, latency in sorted(results, key=lambda x: x[1] or 999):
        if latency is not None:
            logger.info(f"  {label}: {latency:.3f}s")
        else:
            logger.warning(f"  {label}: FAILED")

    ranked: list[str] = []
    for label, latency in sorted(results, key=lambda x: x[1] or 999):
        if latency is None:
            continue
        if label == "direct":
            ranked.append(direct_url)
        else:
            proxy_base = next(b for b in GH_PROXY_LIST if label in b)
            ranked.append(f"{proxy_base.rstrip('/')}/{direct_url}")

    if ranked:
        logger.info(f"Ranked {len(ranked)} usable source(s)")
    return ranked


if __name__ == '__main__':
    print(asyncio.run(get_latest_release("xxynet", "KiraAI")))

    # print(asyncio.run(get_all_releases("xxynet", "KiraAI")))
