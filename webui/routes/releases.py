from fastapi import Depends, HTTPException, status

from core.config.default import VERSION
from core.utils.github_api import download_source_zipball, get_all_releases
from core.utils.path_utils import get_data_path
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

        if zip_path.exists():
            return {"status": "ok", "path": str(zip_path), "cached": True}

        try:
            data = await download_source_zipball("xxynet", "KiraAI", tag)
        except Exception as e:
            print(f"Failed to download release {tag}: {e}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to download release {tag}",
            )
        zip_path.write_bytes(data)
        return {"status": "ok", "path": str(zip_path)}
