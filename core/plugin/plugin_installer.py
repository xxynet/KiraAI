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
from typing import Callable, List, Optional

from core.logging_manager import get_logger
from core.utils.github_api import parse_github_url, pick_fastest_source
from core.utils.network import download_file
from core.utils.path_utils import get_data_path, is_within_directory

logger = get_logger("plugin_installer", "cyan")


class PluginAlreadyInstalledError(ValueError):
    """Raised when an archive declares a plugin already registered at runtime."""


def _temp_dir() -> Path:
    p = get_data_path() / "temp"
    p.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
async def _run_thread_worker(func: Callable, *args):
    """Run blocking work in a thread and settle it before propagating cancellation."""
    worker = asyncio.create_task(asyncio.to_thread(func, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception as exc:
                logger.warning(f"Background plugin installer worker failed during cancellation: {exc}")
                break
        raise


async def install_from_github(
    repo_url: str,
    plugins_dir: Path,
    proxy: Optional[str] = None,
    gh_proxy: Optional[str] = None,
    commit_sha: Optional[str] = None,
    is_plugin_installed: Optional[Callable[[str], bool]] = None,
    target_dir: Optional[Path] = None,
    expected_plugin_id: Optional[str] = None,
) -> Path:
    """
    Download a plugin from GitHub, extract it, and move it into plugins_dir.

    proxy    — HTTP/SOCKS proxy forwarded to download_file
    gh_proxy — GitHub reverse-proxy URL prefix (e.g. "https://ghproxy.com/")
               The direct archive link is appended to this prefix.
    commit_sha — optional immutable 40-character Git commit SHA. When omitted,
                 the repository HEAD archive is downloaded for backward compatibility.
    is_plugin_installed — callback used to reject an archive whose manifest
                          declares an already registered plugin ID.
    target_dir — existing plugin directory to replace. Used by updates when
                 its folder name differs from the plugin ID.
    expected_plugin_id — plugin ID expected by an update request. The archive
                         is rejected before replacing target_dir if it differs.

    Returns the installed plugin directory.
    Raises ValueError for bad URL / missing manifest.
    Raises ConnectionError for network failures.
    """
    owner, repo = parse_github_url(repo_url)
    if commit_sha is not None:
        commit_sha = commit_sha.strip().lower()
        if len(commit_sha) != 40 or any(char not in "0123456789abcdef" for char in commit_sha):
            raise ValueError("commit_sha must be a full 40-character Git commit SHA")
    archive_ref = commit_sha or "HEAD"
    direct_url = f"https://github.com/{owner}/{repo}/archive/{archive_ref}.zip"

    if gh_proxy == "auto":
        ranked = await pick_fastest_source(direct_url, proxy=proxy)
        url = ranked[0] if ranked else direct_url
        logger.info(f"Auto-selected fastest source: {url}")
    elif gh_proxy:
        url = f"{gh_proxy.rstrip('/')}/{direct_url}"
    else:
        url = direct_url

    temp_zip = _temp_dir() / f"{repo}_{uuid.uuid4().hex[:8]}.zip"
    logger.info(f"Downloading plugin {owner}/{repo} → {temp_zip.name}")
    if gh_proxy and gh_proxy != "auto":
        logger.info(f"Proxy: {gh_proxy}")

    try:
        await download_file(url, str(temp_zip), proxy=proxy)
    except asyncio.CancelledError:
        temp_zip.unlink(missing_ok=True)
        raise
    except Exception as e:
        temp_zip.unlink(missing_ok=True)
        raise ConnectionError(f"Failed to download from GitHub: {e}") from e

    return await _extract_and_install(
        temp_zip,
        plugins_dir,
        preferred_name=repo,
        is_plugin_installed=is_plugin_installed,
        target_dir=target_dir,
        expected_plugin_id=expected_plugin_id,
    )


async def install_from_zip(
    zip_bytes: bytes,
    plugins_dir: Path,
    preferred_name: str = "",
    is_plugin_installed: Optional[Callable[[str], bool]] = None,
    target_dir: Optional[Path] = None,
    expected_plugin_id: Optional[str] = None,
) -> Path:
    """
    Install a plugin from an uploaded zip archive.

    Writes the bytes to data/temp/ first so large uploads are not kept in
    memory during extraction, then extracts and moves to plugins_dir.

    is_plugin_installed — callback used to reject an archive whose manifest
                          declares an already registered plugin ID.
    target_dir — existing plugin directory to replace.
    expected_plugin_id — plugin ID expected by an update request.

    Returns the installed plugin directory.
    Raises ValueError if the archive is invalid or manifest.json is missing.
    """
    temp_zip = _temp_dir() / f"upload_{uuid.uuid4().hex[:8]}.zip"
    try:
        await _run_thread_worker(temp_zip.write_bytes, zip_bytes)
    except asyncio.CancelledError:
        temp_zip.unlink(missing_ok=True)
        raise
    except Exception as e:
        temp_zip.unlink(missing_ok=True)
        raise IOError(f"Failed to write uploaded zip to temp: {e}") from e

    try:
        return await _extract_and_install(
            temp_zip,
            plugins_dir,
            preferred_name=preferred_name,
            is_plugin_installed=is_plugin_installed,
            target_dir=target_dir,
            expected_plugin_id=expected_plugin_id,
        )
    except asyncio.CancelledError:
        temp_zip.unlink(missing_ok=True)
        raise


async def install_requirements(plugin_dir: Path, pypi_mirror: Optional[str] = None) -> List[str]:
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
    pip_cmd = [sys.executable, "-m", "pip", "install", "-r", str(req_file)]
    if pypi_mirror:
        if pypi_mirror.startswith(("http://", "https://")):
            pip_cmd.extend(["-i", pypi_mirror])
        else:
            logger.warning(f"Ignoring invalid pypi_mirror (must start with http:// or https://): {pypi_mirror}")
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *pip_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            proc.terminate()
            try:
                await proc.wait()
            except ProcessLookupError:
                pass
        raise
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
    is_plugin_installed: Optional[Callable[[str], bool]] = None,
    target_dir: Optional[Path] = None,
    expected_plugin_id: Optional[str] = None,
) -> Path:
    """Extract and install a plugin archive without blocking the event loop."""
    return await _run_thread_worker(
        _extract_and_install_sync,
        temp_zip,
        plugins_dir,
        preferred_name,
        is_plugin_installed,
        target_dir,
        expected_plugin_id,
    )


def _extract_and_install_sync(
    temp_zip: Path,
    plugins_dir: Path,
    preferred_name: str = "",
    is_plugin_installed: Optional[Callable[[str], bool]] = None,
    target_dir: Optional[Path] = None,
    expected_plugin_id: Optional[str] = None,
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
            if expected_plugin_id and plugin_id != expected_plugin_id:
                raise ValueError(
                    f"Plugin identity changed: expected '{expected_plugin_id}', got '{plugin_id}'"
                )
            if is_plugin_installed and is_plugin_installed(plugin_id):
                raise PluginAlreadyInstalledError(
                    f"Plugin '{plugin_id}' is already installed. Use the update action instead."
                )

            staging = _temp_dir() / f"extract_{uuid.uuid4().hex[:8]}_{plugin_id}"
            staging.mkdir(parents=True, exist_ok=True)

            for item in zf.infolist():
                rel_path = item.filename[len(prefix):]
                if not rel_path or rel_path.endswith("/"):
                    continue
                target = staging / rel_path
                # Reject members whose path escapes the staging dir (Zip-Slip).
                if not is_within_directory(staging, target):
                    raise ValueError(
                        f"Unsafe path in plugin archive (zip-slip blocked): {item.filename}"
                    )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(item.filename))

        # Updates may preserve a legacy directory name. New installs always
        # use plugins_dir/<plugin_id>/.
        plugins_dir.mkdir(parents=True, exist_ok=True)
        if target_dir is None:
            dest = plugins_dir / plugin_id
        else:
            dest = target_dir
            if dest.resolve().parent != plugins_dir.resolve():
                raise ValueError("Plugin update target must be a direct child of the plugins directory")
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
