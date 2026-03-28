"""
Utilities for installing plugins at runtime from a GitHub URL or a zip archive.

Flow
----
  GitHub  : URL → stream-download to data/temp/<name>.zip
                  → extract to data/temp/extract_<id>/
                  → move   to data/plugins/<plugin_id>/
                  → delete data/temp/<name>.zip

  Upload  : zip bytes → write to data/temp/upload_<uuid>.zip
                       → (same extract / move / delete steps)

After installation call PluginManager.load_plugin_from_dir() to activate the plugin.
"""
import asyncio
import json
import shutil
import sys
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from core.logging_manager import get_logger
from core.utils.github_api import parse_github_url
from core.utils.network import download_file
from core.utils.path_utils import get_data_path

logger = get_logger("plugin_installer", "cyan")


def _temp_dir() -> Path:
    p = get_data_path() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def install_from_github(
    repo_url: str,
    plugins_dir: Path,
    proxy: Optional[str] = None,
    gh_proxy: Optional[str] = None,
) -> Path:
    """
    Download a plugin from GitHub, extract it, and move it into plugins_dir.

    proxy    — HTTP/SOCKS proxy forwarded to download_file
    gh_proxy — GitHub reverse-proxy URL prefix (e.g. "https://ghproxy.com/")
               The direct archive link is appended to this prefix.

    Returns the installed plugin directory.
    Raises ValueError for bad URL / missing manifest.
    Raises ConnectionError for network failures.
    """
    owner, repo = parse_github_url(repo_url)

    if gh_proxy:
        url = f"{gh_proxy.rstrip('/')}/https://github.com/{owner}/{repo}/archive/HEAD.zip"
    else:
        url = f"https://github.com/{owner}/{repo}/archive/HEAD.zip"

    temp_zip = _temp_dir() / f"{repo}_{uuid.uuid4().hex[:8]}.zip"
    logger.info(f"Downloading plugin {owner}/{repo} → {temp_zip.name}")

    try:
        await download_file(url, str(temp_zip), proxy=proxy)
    except Exception as e:
        temp_zip.unlink(missing_ok=True)
        raise ConnectionError(f"Failed to download from GitHub: {e}") from e

    return await _extract_and_install(temp_zip, plugins_dir, preferred_name=repo)


async def install_from_zip(
    zip_bytes: bytes,
    plugins_dir: Path,
    preferred_name: str = "",
) -> Path:
    """
    Install a plugin from an uploaded zip archive.

    Writes the bytes to data/temp/ first so large uploads are not kept in
    memory during extraction, then extracts and moves to plugins_dir.

    Returns the installed plugin directory.
    Raises ValueError if the archive is invalid or manifest.json is missing.
    """
    temp_zip = _temp_dir() / f"upload_{uuid.uuid4().hex[:8]}.zip"
    try:
        temp_zip.write_bytes(zip_bytes)
    except Exception as e:
        temp_zip.unlink(missing_ok=True)
        raise IOError(f"Failed to write uploaded zip to temp: {e}") from e

    return await _extract_and_install(temp_zip, plugins_dir, preferred_name=preferred_name)


async def install_requirements(plugin_dir: Path) -> List[str]:
    """
    Install dependencies listed in the plugin's requirements.txt using pip.

    Returns a list of warning strings (empty if everything succeeded).
    Does NOT raise; failures are returned as warnings so the caller can
    decide whether to abort or proceed with loading the plugin.
    """
    req_file = plugin_dir / "requirements.txt"
    if not req_file.exists():
        return []

    logger.info(f"Installing requirements for plugin at {plugin_dir}")
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pip", "install", "-r", str(req_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    except Exception as e:
        return [f"Failed to run pip: {e}"]

    if proc.returncode != 0:
        msg = stderr.decode(errors="replace").strip()
        logger.warning(f"pip install failed for {plugin_dir.name}: {msg}")
        return [f"pip install failed (exit {proc.returncode}): {msg}"]

    logger.info(f"Requirements installed for plugin '{plugin_dir.name}'")
    return []


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _extract_and_install(
    temp_zip: Path,
    plugins_dir: Path,
    preferred_name: str = "",
) -> Path:
    """
    Extract temp_zip into a staging directory under data/temp/, move the result
    to plugins_dir/<plugin_id>/, then delete the temp zip.

    On any failure the temp zip and staging dir are cleaned up and the exception
    is re-raised.
    """
    staging: Optional[Path] = None
    try:
        try:
            zf = zipfile.ZipFile(temp_zip)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Not a valid zip archive: {e}") from e

        with zf:
            names = zf.namelist()

            # Detect a single wrapping top-level directory (GitHub archive style)
            top_entries = {n.split("/")[0] for n in names if n.split("/")[0]}
            prefix = list(top_entries)[0] + "/" if len(top_entries) == 1 else ""

            manifest_entry = f"{prefix}manifest.json"
            if manifest_entry not in names:
                raise ValueError("Plugin archive does not contain manifest.json")

            try:
                manifest = json.loads(zf.read(manifest_entry).decode("utf-8"))
            except Exception as e:
                raise ValueError(f"Failed to parse manifest.json: {e}") from e

            plugin_id: str = manifest.get("plugin_id") or preferred_name
            if not plugin_id:
                raise ValueError(
                    "manifest.json does not contain 'plugin_id' and no name could be inferred"
                )

            staging = _temp_dir() / f"extract_{uuid.uuid4().hex[:8]}_{plugin_id}"
            staging.mkdir(parents=True, exist_ok=True)

            for item in zf.infolist():
                rel_path = item.filename[len(prefix):]
                if not rel_path or rel_path.endswith("/"):
                    continue
                target = staging / rel_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(item.filename))

        # Move staging → plugins_dir/<plugin_id>/  (replace if already exists)
        plugins_dir.mkdir(parents=True, exist_ok=True)
        dest = plugins_dir / plugin_id
        if dest.exists():
            shutil.rmtree(dest)
        shutil.move(str(staging), str(dest))
        staging = None  # moved successfully — skip cleanup

        logger.info(f"Plugin '{plugin_id}' installed to {dest}")
        return dest

    finally:
        # Always remove the temp zip
        temp_zip.unlink(missing_ok=True)
        # Remove staging dir if the move didn't happen (failure path)
        if staging and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
