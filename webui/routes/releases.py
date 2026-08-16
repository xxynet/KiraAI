import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import Depends, HTTPException, status

from core.config.default import VERSION
from core.logging_manager import get_logger
from core.plugin.plugin_installer import install_requirements
from core.utils.github_api import download_asset, get_all_releases, pick_fastest_source
from core.utils.path_utils import get_data_path, get_root_path
from core.utils.update_transaction import STAGE_PREFIX, UpdateTransaction
from webui.models import DownloadReleaseRequest, ReleaseUpdateProgress, ReleasesResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("releases", "green")

RESTART_EXIT_CODE = 42
RESTART_DELAY_SECONDS = 0.5  # Allow HTTP response to flush before hard exit
_install_lock = asyncio.Lock()

_RELEASES_CACHE_TTL = 300  # 5 minutes
_releases_cache: list[dict] | None = None
_releases_cache_time: float = 0


class ReleasesRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._progress: dict[str, dict] = {}
        self._active_task: asyncio.Task | None = None
        self._active_task_id: str | None = None

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/releases",
                methods=["GET"],
                endpoint=self.get_releases,
                response_model=ReleasesResponse,
                tags=["system"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/releases/download",
                methods=["POST"],
                endpoint=self.download_release,
                tags=["system"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/releases/progress/{task_id}",
                methods=["GET"],
                endpoint=self.get_update_progress,
                response_model=ReleaseUpdateProgress,
                tags=["system"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_releases(self):
        global _releases_cache, _releases_cache_time
        now = time.monotonic()
        if _releases_cache is not None and now - _releases_cache_time < _RELEASES_CACHE_TTL:
            releases = _releases_cache
        else:
            try:
                releases = await get_all_releases("xxynet", "KiraAI")
            except Exception as e:
                if _releases_cache is not None:
                    logger.warning(f"Failed to fetch releases, using stale cache: {e}")
                    releases = _releases_cache
                else:
                    logger.error(f"Failed to fetch releases: {e}")
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Failed to fetch releases: {e}",
                    ) from e
            else:
                _releases_cache = releases
                _releases_cache_time = now
        return ReleasesResponse(
            current_version=VERSION,
            releases=[r for r in releases if not r.get("draft")],
        )

    async def download_release(self, payload: DownloadReleaseRequest):
        tag = payload.tag_name
        async with _install_lock:
            if self._active_task and not self._active_task.done():
                return self._progress[self._active_task_id]

            releases = await self.get_releases()
            if not any(release.tag_name == tag for release in releases.releases):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown release tag")

            task_id = uuid.uuid4().hex
            self._progress[task_id] = self._new_progress(task_id, tag)
            self._active_task_id = task_id
            self._active_task = asyncio.create_task(self._run_update(task_id, tag))
            return self._progress[task_id]

    async def get_update_progress(self, task_id: str):
        progress = self._progress.get(task_id)
        if progress is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Update task not found")
        return progress

    @staticmethod
    def _new_progress(task_id: str, tag: str) -> dict:
        return {
            "id": task_id,
            "target_version": tag,
            "status": "running",
            "stage": "preparing",
            "message": "Preparing update...",
            "overall_percent": 0,
            "stages": {
                name: {"status": "pending", "percent": 0}
                for name in ("download", "verify", "apply", "dependencies", "restart")
            },
        }

    def _set_progress(self, task_id: str, stage: str, message: str, percent: int, status: str = "running") -> None:
        progress = self._progress[task_id]
        progress.update({"stage": stage, "message": message, "overall_percent": percent})
        progress["stages"][stage].update({"status": status, "percent": percent})

    async def _run_update(self, task_id: str, tag: str) -> None:
        transaction: UpdateTransaction | None = None
        try:
            async with _install_lock:
                safe_tag = re.sub(r"[^A-Za-z0-9._-]", "-", tag)
                safe_tag = re.sub(r"-{2,}", "-", safe_tag).strip(".-")[:128] or "unknown"
                updates_dir = get_data_path() / "updates"
                updates_dir.mkdir(parents=True, exist_ok=True)
                zip_path = updates_dir / f"{safe_tag}.zip"
                loop = asyncio.get_running_loop()

                self._set_progress(task_id, "download", "Downloading release source...", 5)
                if not zip_path.exists():
                    direct_url = f"https://github.com/xxynet/KiraAI/archive/refs/tags/{tag}.zip"
                    ranked_urls = await pick_fastest_source(direct_url)
                    if not ranked_urls:
                        raise RuntimeError("All download sources failed")
                    data = None
                    for i, url in enumerate(ranked_urls):
                        logger.info(f"Trying source {i + 1}/{len(ranked_urls)}: {url}")
                        try:
                            data = await download_asset(url)
                            logger.info(f"Downloaded {len(data) / 1024 / 1024:.1f} MB from source {i + 1}")
                            break
                        except Exception as exc:
                            logger.warning(f"Source {i + 1} failed: {exc}")
                    if data is None:
                        raise RuntimeError("Failed to download release source")
                    await loop.run_in_executor(None, zip_path.write_bytes, data)
                self._set_progress(task_id, "download", "Release source downloaded.", 35, "done")

                self._set_progress(task_id, "verify", "Verifying update package...", 40)
                transaction = await asyncio.to_thread(self._apply_update, zip_path, True)
                self._set_progress(task_id, "verify", "Update package verified.", 50, "done")
                self._set_progress(task_id, "apply", "Update files applied; keeping rollback backup...", 70, "done")

                self._set_progress(task_id, "dependencies", "Installing dependencies...", 75)
                config = getattr(self.lifecycle, "kira_config", None)
                pypi_mirror = ((config.get("network") or {}).get("pypi_mirror") if config else None)
                warnings = await install_requirements(get_root_path(), pypi_mirror=pypi_mirror)
                if warnings:
                    raise RuntimeError("Dependency installation failed: " + "; ".join(warnings))
                await asyncio.to_thread(transaction.commit)
                transaction = None
                self._set_progress(task_id, "dependencies", "Dependencies installed.", 90, "done")

            self._set_progress(task_id, "restart", "Update complete. Restarting KiraAI...", 98)
            self._progress[task_id]["status"] = "restarting"
            logger.info("Scheduling restart after update...")
            await self.lifecycle.stop()
            if self.lifecycle.uvicorn_server:
                self.lifecycle.uvicorn_server.should_exit = True
            asyncio.get_running_loop().call_later(RESTART_DELAY_SECONDS, os._exit, RESTART_EXIT_CODE)
        except Exception as exc:
            if transaction is not None:
                rollback_errors = await asyncio.to_thread(transaction.rollback)
                for message in rollback_errors:
                    logger.error(message)
            logger.exception(f"Update {tag} failed")
            self._progress[task_id].update({
                "status": "failed",
                "stage": "failed",
                "message": "Update failed. Existing files were restored when possible; check the server log for details.",
            })

    @staticmethod
    def _apply_update(zip_path: Path, keep_backup: bool = False) -> UpdateTransaction | None:
        root = get_root_path()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir).resolve()
            with zipfile.ZipFile(zip_path, "r") as zf:
                corrupt_member = zf.testzip()
                if corrupt_member:
                    raise ValueError(f"Corrupt file in update archive: {corrupt_member}")
                for member in zf.infolist():
                    target = (tmp / member.filename).resolve()
                    if not target.is_relative_to(tmp):
                        raise ValueError(f"Path traversal detected: {member.filename}")
                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target, "wb") as dst:
                            dst.write(src.read())

            # GitHub zipballs have a single top-level directory (e.g. xxynet-KiraAI-abc123/)
            entries = list(tmp.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                source_root = entries[0]
            else:
                source_root = tmp

            # Collect what the zip contains (top-level names only)
            zip_items: list[str] = [item.name for item in source_root.iterdir()]

            # Place staging inside root: root.parent can be a different Docker
            # mount, which makes rename() fail with EXDEV (cross-device link).
            stage_dir = Path(tempfile.mkdtemp(prefix=STAGE_PREFIX, dir=str(root)))
            try:
                # 1. Copy zip contents into staging
                for name in zip_items:
                    src = source_root / name
                    staged = stage_dir / name
                    if src.is_dir():
                        shutil.copytree(src, staged)
                    else:
                        staged.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, staged)

                transaction = UpdateTransaction(root, stage_dir, zip_items)
                transaction.apply()
                if keep_backup:
                    return transaction
                transaction.commit()
                return None
            finally:
                shutil.rmtree(stage_dir, ignore_errors=True)
