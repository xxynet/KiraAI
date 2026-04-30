"""
Frontend dist checker — ensure data/dist exists and is complete.

Called at startup (before WebUI init). If the dist is missing or outdated:
  1. Speed-test GitHub proxy list + direct GitHub, pick the fastest
  2. Download dist.zip from the matching release
  3. Verify SHA-256 (from checksums.txt release asset, optional)
  4. Extract into data/dist
  5. Write .version marker
"""

import asyncio
import shutil
import zipfile
import io
from pathlib import Path
from typing import Optional

from core.config import VERSION
from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from core.utils.network import test_url_speed, get_file_content
from core.utils.github_api import get_release_assets, verify_sha256

logger = get_logger("dist_checker", "blue")

REPO_OWNER = "xxynet"
REPO_NAME = "KiraAI"
ASSET_NAME = "dist.zip"
CHECKSUM_NAME = "checksums.txt"

GH_PROXY_LIST = [
    "https://gh-proxy.com/",
    "https://gh-proxy.org/",
    "https://hk.gh-proxy.org/",
    "https://cdn.gh-proxy.org/",
    "https://edgeone.gh-proxy.org/",
]

# Files / dirs that must exist for dist to be considered complete
REQUIRED_ENTRIES = ["index.html", "assets"]


def get_dist_dir() -> Path:
    return get_data_path() / "dist"


def get_version_marker() -> Path:
    return get_dist_dir() / ".version"


def is_dist_complete() -> bool:
    """Check if dist exists, has required files, and version matches."""
    dist_dir = get_dist_dir()
    if not dist_dir.exists():
        return False

    # Check required entries
    for entry in REQUIRED_ENTRIES:
        if not (dist_dir / entry).exists():
            logger.warning(f"dist missing required entry: {entry}")
            return False

    # Check version marker
    marker = get_version_marker()
    if not marker.exists():
        logger.warning("dist .version marker missing")
        return False

    stored_version = marker.read_text(encoding="utf-8").strip()
    if stored_version != VERSION:
        logger.warning(f"dist version mismatch: {stored_version} != {VERSION}")
        return False

    return True


# ─── Speed test helpers ───────────────────────────────────────────────────────


async def _test_latency(url: str, proxy: Optional[str] = None, timeout: float = 8.0) -> Optional[float]:
    """Return latency in seconds, or None on failure. Wraps network.test_url_speed."""
    result = await test_url_speed(url, proxy=proxy, timeout=timeout)
    return result["latency"]


async def pick_fastest_source(
    tag: str,
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Speed-test all GitHub proxy candidates + direct GitHub, return the
    base URL with the lowest latency.  Returns None if all fail.
    """
    # Build the direct GitHub asset download URL (for HEAD probing)
    direct_url = (
        f"https://github.com/{REPO_OWNER}/{REPO_NAME}"
        f"/releases/download/{tag}/{ASSET_NAME}"
    )

    candidates: list[tuple[str, str]] = []  # (label, probe_url)
    candidates.append(("direct", direct_url))
    for base in GH_PROXY_LIST:
        label = base.rstrip("/").split("//", 1)[-1]
        candidates.append((label, f"{base.rstrip('/')}/{direct_url}"))

    logger.info(f"Speed-testing {len(candidates)} GitHub sources for {ASSET_NAME} ...")

    # Fire all HEAD probes concurrently
    tasks = {
        label: asyncio.create_task(_test_latency(url, proxy))
        for label, url in candidates
    }
    results: dict[str, Optional[float]] = {}
    for label, task in tasks.items():
        results[label] = await task

    # Log results
    for label, latency in sorted(results.items(), key=lambda x: x[1] or 999):
        if latency is not None:
            logger.info(f"  {label}: {latency:.3f}s")
        else:
            logger.info(f"  {label}: FAILED")

    # Pick winner
    valid = {k: v for k, v in results.items() if v is not None}
    if not valid:
        return None

    winner = min(valid, key=valid.get)
    logger.info(f"Selected source: {winner} ({valid[winner]:.3f}s)")

    # Return the download URL for the winner
    if winner == "direct":
        return direct_url
    else:
        proxy_base = next(b for b in GH_PROXY_LIST if winner in b)
        return f"{proxy_base.rstrip('/')}/{direct_url}"


# ─── Download + verify ─────


async def _fetch_release_checksums(
    tag: str,
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Try to download checksums.txt from the release assets and return the
    expected SHA-256 for ASSET_NAME.  Returns None if not available.
    Uses github_api.get_release_assets to fetch the asset list.
    """
    assets = await get_release_assets(REPO_OWNER, REPO_NAME, tag, proxy)
    if not assets:
        return None

    checksum_asset = next((a for a in assets if a["name"] == CHECKSUM_NAME), None)
    if not checksum_asset:
        logger.info(f"No {CHECKSUM_NAME} found in release {tag}, skipping SHA verification")
        return None

    try:
        content = await get_file_content(checksum_asset["download_url"], proxy=proxy)
        text = content.decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to download {CHECKSUM_NAME}: {e}")
        return None

    # Parse: expect lines like "<sha256>  dist.zip" or "sha256:<hex>  dist.zip"
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1] == ASSET_NAME:
            sha = parts[0].removeprefix("sha256:").lower()
            if len(sha) == 64 and all(c in "0123456789abcdef" for c in sha):
                return sha

    logger.warning(f"{ASSET_NAME} not listed in {CHECKSUM_NAME}")
    return None


def _extract_dist(zip_bytes: bytes, dist_dir: Path) -> None:
    """
    Extract zip into dist_dir.  Handles both flat and single-folder layouts.
    """
    # Remove old dist
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    dist_dir.mkdir(parents=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("Empty zip archive")

        # Detect if all entries share a common top-level folder
        top_levels = {n.split("/")[0] for n in names if "/" in n}
        strip_prefix = ""
        if len(top_levels) == 1:
            # Check if index.html is at <prefix>/index.html
            prefix = top_levels.pop()
            if f"{prefix}/index.html" in names:
                strip_prefix = prefix + "/"

        for member in zf.infolist():
            if member.is_dir():
                continue
            # Strip common prefix so files land directly in dist_dir
            out_name = member.filename
            if strip_prefix and out_name.startswith(strip_prefix):
                out_name = out_name[len(strip_prefix):]
            if not out_name:
                continue

            out_path = dist_dir / out_name
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out_path, "wb") as dst:
                dst.write(src.read())


# ─── Main entry point ────────────────────────────────────────────────────────


async def ensure_dist(proxy: Optional[str] = None) -> None:
    """
    Ensure data/dist is present and up-to-date.
    Called from the launcher before WebUI starts.
    """
    if is_dist_complete():
        logger.info(f"✔ dist is up-to-date ({VERSION})")
        return

    logger.info(f"⬇ dist missing or outdated, downloading for {VERSION} ...")

    tag = VERSION  # e.g. "v2.11.0"
    dist_dir = get_dist_dir()

    # 1. Pick fastest source
    download_url = await pick_fastest_source(tag, proxy)
    if not download_url:
        logger.error(
            "✘ All GitHub sources failed. Please manually place the frontend "
            f"dist files in: {dist_dir}"
        )
        return

    # 2. Fetch checksums (optional)
    expected_sha = await _fetch_release_checksums(tag, proxy)

    # 3. Download
    logger.info(f"Downloading {ASSET_NAME} ...")
    try:
        content = await get_file_content(download_url, proxy=proxy, timeout=120.0)
    except Exception as e:
        logger.error(f"✘ Download failed: {e}")
        return
    logger.info(f"Downloaded {len(content) / 1024 / 1024:.1f} MB")

    # 4. SHA verification
    if expected_sha:
        if verify_sha256(content, expected_sha):
            logger.info("✔ SHA-256 verified")
        else:
            logger.error(
                "✘ SHA-256 mismatch! The downloaded file may be corrupted. "
                "Aborting extraction."
            )
            return
    else:
        logger.warning("⚠ SHA-256 not verified (no checksums.txt in release)")

    # 5. Extract
    try:
        _extract_dist(content, dist_dir)
    except Exception as e:
        logger.error(f"✘ Failed to extract {ASSET_NAME}: {e}")
        return

    # 6. Write version marker
    get_version_marker().write_text(VERSION, encoding="utf-8")
    logger.info(f"✔ dist installed successfully → {dist_dir}")
