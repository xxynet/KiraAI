import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from fastapi import Depends, File, HTTPException, UploadFile

from core.utils.path_utils import get_data_path
from webui.models import (
    BackupCreateResponse,
    DirectoryEntry,
    RestoreResponse,
    StorageInfoResponse,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

# Backup directory lives inside the data directory
BACKUP_DIR_NAME = "backups"


def _get_backup_dir() -> Path:
    return get_data_path() / BACKUP_DIR_NAME


def _calc_dir_size(path: Path) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a directory tree."""
    total = 0
    count = 0
    if path.exists():
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = Path(dirpath) / f
                try:
                    total += fp.stat().st_size
                    count += 1
                except OSError:
                    pass
    return total, count


class SettingsRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/settings/storage",
                methods=["GET"],
                endpoint=self.get_storage_info,
                response_model=StorageInfoResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup",
                methods=["POST"],
                endpoint=self.create_backup,
                response_model=BackupCreateResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/list",
                methods=["GET"],
                endpoint=self.list_backups,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/download/{filename}",
                methods=["GET"],
                endpoint=self.download_backup,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/{filename}",
                methods=["DELETE"],
                endpoint=self.delete_backup,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/{filename}/restore",
                methods=["POST"],
                endpoint=self.restore_from_backup,
                response_model=RestoreResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/restore",
                methods=["POST"],
                endpoint=self.restore_backup,
                response_model=RestoreResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    # ── Storage ──────────────────────────────────────────────────────────────

    async def get_storage_info(self):
        data_path = get_data_path()
        disk = shutil.disk_usage(data_path)

        directories = []
        if data_path.exists():
            for entry in sorted(data_path.iterdir()):
                if not entry.is_dir():
                    continue
                size, count = _calc_dir_size(entry)
                directories.append(
                    DirectoryEntry(
                        name=entry.name,
                        path=str(entry),
                        size_bytes=size,
                        file_count=count,
                    )
                )

        total_size, _ = _calc_dir_size(data_path)

        return StorageInfoResponse(
            data_path=str(data_path),
            total_size_bytes=total_size,
            disk_total_bytes=disk.total,
            disk_used_bytes=disk.used,
            disk_free_bytes=disk.free,
            directories=directories,
        )

    # ── Backup ───────────────────────────────────────────────────────────────

    async def create_backup(self):
        data_path = get_data_path()
        backup_dir = _get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.zip"
        zip_path = backup_dir / filename

        # Directories to exclude from backup (backups themselves, dist builds)
        exclude_dirs = {BACKUP_DIR_NAME, "dist", "__pycache__"}

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(data_path):
                # Prune excluded directories
                dirs[:] = [d for d in dirs if d not in exclude_dirs]
                rel_root = Path(root).relative_to(data_path)
                for f in files:
                    full_path = Path(root) / f
                    arcname = rel_root / f
                    try:
                        zf.write(full_path, arcname)
                    except OSError:
                        pass

        size = zip_path.stat().st_size
        return BackupCreateResponse(
            filename=filename,
            size_bytes=size,
            created_at=datetime.now().isoformat(),
        )

    async def list_backups(self):
        backup_dir = _get_backup_dir()
        if not backup_dir.exists():
            return []
        backups = []
        for f in sorted(backup_dir.iterdir(), reverse=True):
            if f.suffix == ".zip" and f.is_file():
                stat = f.stat()
                backups.append({
                    "filename": f.name,
                    "size_bytes": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })
        return backups

    async def download_backup(self, filename: str):
        from fastapi.responses import FileResponse

        backup_path = _get_backup_dir() / filename
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        # Prevent path traversal
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")
        return FileResponse(
            path=str(backup_path),
            filename=filename,
            media_type="application/zip",
        )

    async def delete_backup(self, filename: str):
        backup_path = _get_backup_dir() / filename
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")
        backup_path.unlink()
        return {"success": True}

    async def restore_from_backup(self, filename: str):
        backup_path = _get_backup_dir() / filename
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")

        return self._do_restore(backup_path)

    # ── Restore ──────────────────────────────────────────────────────────────

    def _do_restore(self, zip_source) -> RestoreResponse:
        """Extract a zip into the data directory. *zip_source* can be a Path or file-like."""
        data_path = get_data_path()
        exclude_dirs = {BACKUP_DIR_NAME, "__pycache__"}

        try:
            with zipfile.ZipFile(zip_source, "r") as zf:
                for member in zf.infolist():
                    target = (data_path / member.filename).resolve()
                    if not target.is_relative_to(data_path.resolve()):
                        raise HTTPException(status_code=400, detail="Invalid archive content")

                    parts = Path(member.filename).parts
                    if parts and parts[0] in exclude_dirs:
                        continue

                    if member.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(member) as src, open(target, "wb") as dst:
                            dst.write(src.read())

            return RestoreResponse(success=True, message="Restore completed successfully")
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Invalid zip file")
        except HTTPException:
            raise
        except Exception as e:
            return RestoreResponse(success=False, message=f"Restore failed: {e}")

    async def restore_backup(self, file: UploadFile = File(...)):
        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Only .zip files are accepted")

        file.file.seek(0)
        return self._do_restore(file.file)
