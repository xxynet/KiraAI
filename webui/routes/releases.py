import asyncio
import os
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import Depends, HTTPException, status

from core.config.default import VERSION
from core.logging_manager import get_logger
from core.utils.github_api import download_asset, get_all_releases, pick_fastest_source
from core.utils.path_utils import get_data_path, get_root_path
from webui.models import DownloadReleaseRequest, ReleasesResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("releases", "green")

RESTART_EXIT_CODE = 42
RESTART_DELAY_SECONDS = 0.5  # Allow HTTP response to flush before hard exit
_install_lock = asyncio.Lock()


class ReleasesRoutes(Routes):
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
        ]

    async def get_releases(self):
        try:
            releases = await get_all_releases("xxynet", "KiraAI")
        except Exception as e:
            logger.error(f"Failed to fetch releases: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to fetch releases: {e}",
            ) from e
        return ReleasesResponse(
            current_version=VERSION,
            releases=[r for r in releases if not r.get("draft")],
        )

    async def download_release(self, payload: DownloadReleaseRequest):
        tag = payload.tag_name
        safe_tag = re.sub(r"[^A-Za-z0-9._-]", "-", tag)
        safe_tag = re.sub(r"-{2,}", "-", safe_tag)
        safe_tag = safe_tag.strip(".-")
        safe_tag = safe_tag[:128] or "unknown"
        updates_dir = get_data_path() / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        zip_path = updates_dir / f"{safe_tag}.zip"
        loop = asyncio.get_running_loop()

        async with _install_lock:
            if not zip_path.exists():
                logger.info(f"Downloading release {tag}...")
                direct_url = f"https://github.com/xxynet/KiraAI/archive/refs/tags/{tag}.zip"
                ranked_urls = await pick_fastest_source(direct_url)
                if not ranked_urls:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"All download sources failed for {tag}",
                    )
                data = None
                for i, url in enumerate(ranked_urls):
                    logger.info(f"Trying source {i + 1}/{len(ranked_urls)}: {url}")
                    try:
                        data = await download_asset(url)
                        logger.info(f"Downloaded {len(data) / 1024 / 1024:.1f} MB from source {i + 1}")
                        break
                    except Exception as e:
                        logger.warning(f"Source {i + 1} failed: {e}")
                        if i < len(ranked_urls) - 1:
                            logger.info("Trying next source...")
                if data is None:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Failed to download release {tag}",
                    )
                await loop.run_in_executor(None, zip_path.write_bytes, data)
                logger.info(f"Release {tag} downloaded to {zip_path}")

            logger.info(f"Applying update {tag}...")
            try:
                await loop.run_in_executor(None, self._apply_update, zip_path)
            except Exception as e:
                logger.error(f"Failed to apply update {tag}: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to apply update: {e}",
                ) from e
            logger.info(f"Update {tag} applied successfully")

        # Trigger restart — let the response be sent first, then exit
        logger.info("Scheduling restart after update...")
        await self.lifecycle.stop()
        if self.lifecycle.uvicorn_server:
            self.lifecycle.uvicorn_server.should_exit = True
        asyncio.get_running_loop().call_later(RESTART_DELAY_SECONDS, os._exit, RESTART_EXIT_CODE)
        return {"status": "restarting"}

    @staticmethod
    def _apply_update(zip_path: Path) -> None:
        root = get_root_path()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir).resolve()
            with zipfile.ZipFile(zip_path, "r") as zf:
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

            # Stage into a temp dir on the same filesystem so renames are atomic
            stage_dir = Path(tempfile.mkdtemp(dir=str(root.parent)))
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

                # 2. Atomic swap: rename old → .bak, then rename staged → target
                #    Track each successful step so we can reverse them on failure.
                #    (dst, bak_or_None, was_new)
                actions: list[tuple[Path, Path | None, bool]] = []
                try:
                    for name in zip_items:
                        src = stage_dir / name
                        dst = root / name
                        had_original = dst.exists()
                        bak_path: Path | None = None
                        if had_original:
                            bak_path = dst.with_suffix(dst.suffix + ".bak")
                            dst.rename(bak_path)
                        src.rename(dst)
                        actions.append((dst, bak_path, not had_original))
                except Exception:
                    for dst, bak_path, was_new in reversed(actions):
                        if was_new:
                            if dst.is_dir():
                                shutil.rmtree(dst)
                            else:
                                dst.unlink()
                        elif bak_path is not None:
                            bak_path.rename(dst)
                    raise

                # 3. Clean up .bak files
                for dst, bak_path, _ in actions:
                    if bak_path is not None and bak_path.exists():
                        if bak_path.is_dir():
                            shutil.rmtree(bak_path)
                        else:
                            bak_path.unlink()
            finally:
                shutil.rmtree(stage_dir, ignore_errors=True)
