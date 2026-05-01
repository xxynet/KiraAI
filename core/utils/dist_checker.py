"""
Frontend dist checker — ensure data/dist exists and is complete.

Called at startup (before WebUI init). If the dist is missing or outdated:
  1. Speed-test GitHub proxy list + direct GitHub, pick the fastest
  2. Download dist.zip from the matching release
  3. Verify SHA-256 (from Release API digest field, optional)
  4. Extract into data/dist
  5. Write .version marker
"""

import asyncio
import shutil
import zipfile
import io
import re
import hashlib
import time
from pathlib import Path
from typing import Optional

from core.config import VERSION
from core.logging_manager import get_logger
from core.utils.path_utils import get_webui_dist_path
from core.utils.network import test_url_speed, get_file_content
from core.utils.github_api import get_release_assets, verify_sha256

logger = get_logger("dist_checker", "blue")

REPO_OWNER = "xxynet"
REPO_NAME = "KiraAI"
ASSET_NAME = "dist.zip"

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
    return get_webui_dist_path()


def get_version_marker() -> Path:
    return get_dist_dir() / ".version"


def is_dist_complete(ignore_webui_version_check: bool = False) -> bool:
    """Check if dist exists, has required files, and version matches."""
    dist_dir = get_dist_dir()
    if not dist_dir.exists():
        return False

    # Check required entries
    for entry in REQUIRED_ENTRIES:
        if not (dist_dir / entry).exists():
            logger.warning(f"dist missing required entry: {entry}")
            return False

    # When --ignore-webui-version-check is set, skip version marker entirely
    if ignore_webui_version_check:
        return True

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
) -> list[str]:
    """
    Speed-test all GitHub proxy candidates + direct GitHub, return a list of
    download URLs ranked by latency (best first).  Returns empty list if all fail.
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

    # Build ranked list of download URLs (best latency first)
    ranked: list[str] = []
    for label, latency in sorted(results.items(), key=lambda x: x[1] or 999):
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


# ─── Download + verify ─────


async def _fetch_asset_digest(
    tag: str,
    proxy: Optional[str] = None,
) -> Optional[str]:
    """
    Get the SHA-256 digest for ASSET_NAME directly from the GitHub Release
    API (``digest`` field on the asset object, e.g.
    ``sha256:5d5756ce005168262868e4e049c2c7365d01982fc940708988f87a271cdb06be``).

    Returns the hex digest string (without the ``sha256:`` prefix), or None
    if the information is unavailable.
    """
    assets = await get_release_assets(REPO_OWNER, REPO_NAME, tag, proxy)
    if not assets:
        return None

    target = next((a for a in assets if a["name"] == ASSET_NAME), None)
    if not target:
        logger.warning(f"{ASSET_NAME} not found in release {tag} assets")
        return None

    digest = target.get("digest")
    if not digest:
        logger.info(f"No digest available for {ASSET_NAME} in release {tag}")
        return None

    return digest.removeprefix("sha256:").lower()


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


async def ensure_dist(proxy: Optional[str] = None, ignore_webui_version_check: bool = False) -> None:
    """
    Ensure data/dist is present and up-to-date.
    Called from the launcher before WebUI starts.
    """
    if is_dist_complete(ignore_webui_version_check=ignore_webui_version_check):
        if ignore_webui_version_check:
            logger.info(f"✔ dist check skipped (--ignore-webui-version-check)")
        else:
            logger.info(f"✔ dist is up-to-date ({VERSION})")
        return

    logger.info(f"⬇ dist missing or outdated, downloading for {VERSION} ...")

    tag = VERSION  # e.g. "v2.11.0"
    dist_dir = get_dist_dir()

    # 1. Rank all sources by latency
    ranked_urls = await pick_fastest_source(tag, proxy)
    if not ranked_urls:
        logger.error(
            "✘ All GitHub sources failed. Please manually place the frontend "
            f"dist files in: {dist_dir}"
        )
        return

    # 2. Fetch expected digest from Release API (optional)
    expected_sha = await _fetch_asset_digest(tag, proxy)

    # 3. Download with fallback across sources
    content = None
    for i, download_url in enumerate(ranked_urls):
        logger.info(f"Downloading {ASSET_NAME} (source {i + 1}/{len(ranked_urls)}) ...")
        try:
            content = await get_file_content(download_url, proxy=proxy, timeout=30.0)
            logger.info(f"Downloaded {len(content) / 1024 / 1024:.1f} MB")
            break
        except Exception as e:
            logger.warning(f"✘ Source {i + 1} failed: {e}")
            if i < len(ranked_urls) - 1:
                logger.info("↻ Switching to next source ...")
            continue

    if content is None:
        logger.error(
            "✘ All download sources failed. Please manually place the frontend "
            f"dist files in: {dist_dir}"
        )
        return

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
        logger.warning("⚠ SHA-256 not verified (no digest in Release API)")

    # 5. Extract
    try:
        _extract_dist(content, dist_dir)
    except Exception as e:
        logger.error(f"✘ Failed to extract {ASSET_NAME}: {e}")
        return

    # 6. Write version marker
    get_version_marker().write_text(VERSION, encoding="utf-8")
    logger.info(f"✔ dist installed successfully → {dist_dir}")
