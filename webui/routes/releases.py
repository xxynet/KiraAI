import asyncio
import shutil
import tempfile
import zipfile
from pathlib import Path

from fastapi import Depends, HTTPException, status

from core.config.default import VERSION
from core.utils.github_api import download_asset, get_all_releases, pick_fastest_source
from core.utils.path_utils import get_data_path, get_root_path
from webui.models import DownloadReleaseRequest, ReleasesResponse
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes


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
            print(f"Failed to fetch releases: {e}")
            return ReleasesResponse(current_version=VERSION, releases=[])
        return ReleasesResponse(
            current_version=VERSION,
            releases=[r for r in releases if not r.get("draft")],
        )

    async def download_release(self, payload: DownloadReleaseRequest):
        tag = payload.tag_name
        safe_tag = tag.replace("/", "-")
        updates_dir = get_data_path() / "updates"
        updates_dir.mkdir(parents=True, exist_ok=True)
        zip_path = updates_dir / f"{safe_tag}.zip"
        loop = asyncio.get_running_loop()

        if not zip_path.exists():
            print(f"Downloading release {tag}...")
            direct_url = f"https://github.com/xxynet/KiraAI/archive/refs/tags/{tag}.zip"
            ranked_urls = await pick_fastest_source(direct_url)
            if not ranked_urls:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"All download sources failed for {tag}",
                )
            data = None
            for i, url in enumerate(ranked_urls):
                print(f"Trying source {i + 1}/{len(ranked_urls)}: {url}")
                try:
                    data = await download_asset(url)
                    print(f"Downloaded {len(data) / 1024 / 1024:.1f} MB from source {i + 1}")
                    break
                except Exception as e:
                    print(f"Source {i + 1} failed: {e}")
                    if i < len(ranked_urls) - 1:
                        print("Trying next source...")
            if data is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to download release {tag}",
                )
            await loop.run_in_executor(None, zip_path.write_bytes, data)
            print(f"Release {tag} downloaded to {zip_path}")

        print(f"Applying update {tag}...")
        try:
            await loop.run_in_executor(None, self._apply_update, zip_path)
        except Exception as e:
            print(f"Failed to apply update {tag}: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to apply update: {e}",
            ) from e
        print(f"Update {tag} applied successfully")
        return {"status": "ok"}

    @staticmethod
    def _apply_update(zip_path: Path) -> None:
        root = get_root_path()
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp = Path(tmp_dir)
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp)

            # GitHub zipballs have a single top-level directory (e.g. xxynet-KiraAI-abc123/)
            entries = list(tmp.iterdir())
            if len(entries) == 1 and entries[0].is_dir():
                source_root = entries[0]
            else:
                source_root = tmp

            # Collect what the zip contains (relative paths)
            zip_items: set[str] = set()
            for item in source_root.iterdir():
                zip_items.add(item.name)

            # Replace existing items: delete from root, copy from zip
            for name in zip_items:
                src = source_root / name
                dst = root / name
                if dst.exists():
                    if dst.is_dir():
                        shutil.rmtree(dst)
                    else:
                        dst.unlink()
                if src.is_dir():
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
