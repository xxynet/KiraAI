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
import tempfile
from pathlib import Path
from typing import Optional

import httpx

from core.config import VERSION
from core.logging_manager import get_logger
from core.utils.path_utils import get_webui_dist_path, is_within_directory
from core.utils.network import get_file_content
from core.utils.github_api import get_release_assets, pick_fastest_source, verify_sha256
from core.utils.update_transaction import STAGE_PREFIX, UpdateTransaction, recover_interrupted_update

logger = get_logger("dist_checker", "blue")

REPO_OWNER = "xxynet"
REPO_NAME = "KiraAI"
ASSET_NAME = "dist.zip"
WEBUI_JOURNAL_NAME = ".kira-webui-update-journal.json"

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
    try:
        assets = await get_release_assets(REPO_OWNER, REPO_NAME, tag, proxy)
    except httpx.HTTPError as e:
        logger.warning(f"Failed to fetch release assets for {tag}: {e}")
        return None
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


def _extract_dist_to_directory(zip_bytes: bytes, dist_dir: Path) -> None:
    """
    Extract zip into an empty directory. Handles flat and single-folder layouts.
    """
    dist_dir.mkdir(parents=True)

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        corrupt_member = zf.testzip()
        if corrupt_member:
            raise ValueError(f"Corrupt file in dist archive: {corrupt_member}")
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
            # Reject members whose path escapes dist_dir (Zip-Slip).
            if not is_within_directory(dist_dir, out_path):
                raise ValueError(f"Unsafe path in dist archive (zip-slip blocked): {member.filename}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(out_path, "wb") as dst:
                dst.write(src.read())


async def download_dist_archive(version: str, proxy: Optional[str] = None) -> bytes:
    """Download and verify the WebUI archive for a release without applying it."""
    direct_url = f"https://github.com/{REPO_OWNER}/{REPO_NAME}/releases/download/{version}/{ASSET_NAME}"
    ranked_urls = await pick_fastest_source(direct_url, proxy)
    if not ranked_urls:
        raise RuntimeError("All WebUI download sources failed")

    expected_sha = await _fetch_asset_digest(version, proxy)
    for index, download_url in enumerate(ranked_urls):
        logger.info(f"Downloading {ASSET_NAME} (source {index + 1}/{len(ranked_urls)}) ...")
        try:
            content = await get_file_content(download_url, proxy=proxy, timeout=30.0)
        except Exception as exc:
            logger.warning(f"WebUI source {index + 1} failed: {exc}")
            continue
        if expected_sha and not verify_sha256(content, expected_sha):
            raise ValueError("WebUI archive SHA-256 verification failed")
        if not expected_sha:
            logger.warning("WebUI archive has no published SHA-256 digest")
        return content
    raise RuntimeError("Failed to download the WebUI archive")


def apply_dist_archive(
    zip_bytes: bytes,
    version: str,
    keep_backup: bool = False,
) -> UpdateTransaction | None:
    """Apply a prepared WebUI archive with the same rollback guarantees as core code."""
    dist_dir = get_dist_dir().resolve()
    root = dist_dir.parent
    root.mkdir(parents=True, exist_ok=True)
    stage_dir = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=root))
    try:
        staged_dist = stage_dir / dist_dir.name
        _extract_dist_to_directory(zip_bytes, staged_dist)
        (staged_dist / ".version").write_text(version, encoding="utf-8")
        transaction = UpdateTransaction(
            root,
            stage_dir,
            [dist_dir.name],
            journal_name=WEBUI_JOURNAL_NAME,
        )
        transaction.apply()
        if keep_backup:
            return transaction
        transaction.commit()
        return None
    finally:
        shutil.rmtree(stage_dir, ignore_errors=True)


# ─── Main entry point ────────────────────────────────────────────────────────


async def ensure_dist(proxy: Optional[str] = None, ignore_webui_version_check: bool = False) -> None:
    """
    Ensure data/dist is present and up-to-date.
    Called from the launcher before WebUI starts.
    """
    recovery_errors = recover_interrupted_update(
        get_dist_dir().parent,
        journal_name=WEBUI_JOURNAL_NAME,
    )
    if recovery_errors:
        for error in recovery_errors:
            logger.error(error)
        return

    if is_dist_complete(ignore_webui_version_check=ignore_webui_version_check):
        if ignore_webui_version_check:
            logger.info(f"✔ dist check skipped (--ignore-webui-version-check)")
        else:
            logger.info(f"✔ dist is up-to-date ({VERSION})")
        return

    logger.info(f"⬇ dist missing or outdated, downloading for {VERSION} ...")

    dist_dir = get_dist_dir()
    try:
        content = await download_dist_archive(VERSION, proxy)
        await asyncio.to_thread(apply_dist_archive, content, VERSION)
    except Exception as e:
        logger.error(
            f"✘ Failed to prepare {ASSET_NAME}: {e}. Please manually place the frontend "
            f"dist files in: {dist_dir}"
        )
        return
    logger.info(f"✔ dist installed successfully → {dist_dir}")
