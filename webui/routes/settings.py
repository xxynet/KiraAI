import asyncio
import os
import shutil
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path, PureWindowsPath

from fastapi import Depends, File, HTTPException, Request, UploadFile

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from webui.models import (
    BackupCreateResponse,
    BackupProgressResponse,
    ChangeTokenRequest,
    DirectoryEntry,
    RestoreResponse,
    StorageInfoResponse,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _update_access_token

# Backup directory lives inside the data directory
BACKUP_DIR_NAME = "backups"
MAX_LINK_TARGET_BYTES = 128 * 1024
logger = get_logger("webui", "blue")


def _get_backup_dir() -> Path:
    return get_data_path() / BACKUP_DIR_NAME


def _is_relative_link_target(target: str, link: Path, root: Path) -> bool:
    # Allow leading parent components, but reject paths that could cancel a symlink.
    return (
        bool(target)
        and "\x00" not in target
        and "\\" not in target
        and not PureWindowsPath(target).anchor
        and Path(target).parts == Path(os.path.normpath(target)).parts
        and Path(os.path.abspath(link.parent / target)).is_relative_to(root)
    )


def _backup_link_entry(
    path: Path, data_path: Path, metadata: os.stat_result, is_directory: bool
) -> tuple[zipfile.ZipInfo, bytes] | None:
    try:
        target = os.readlink(path).replace(os.sep, "/")
        resolved = path.resolve()
    except (OSError, RuntimeError) as exc:
        logger.warning("Skipping backup symlink %s: %s", path, exc)
        return None
    if not resolved.is_relative_to(data_path) or resolved.is_symlink():
        logger.warning("Skipping backup symlink %s -> %s", path, target)
        return None
    if not _is_relative_link_target(target, path, data_path):
        target = os.path.relpath(resolved, path.parent).replace(os.sep, "/")
    if not _is_relative_link_target(target, path, data_path):
        logger.warning("Skipping backup symlink with unsupported target %s -> %s", path, target)
        return None

    info = zipfile.ZipInfo(path.relative_to(data_path).as_posix())
    info.create_system = 3
    info.external_attr = metadata.st_mode << 16
    if is_directory or getattr(metadata, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_DIRECTORY:
        info.external_attr |= stat.FILE_ATTRIBUTE_DIRECTORY
    info.compress_type = zipfile.ZIP_DEFLATED
    return info, os.fsencode(target)


def _calc_dir_size(path: Path) -> tuple[int, int]:
    """Return logical bytes and file count without following file symlinks.

    Count hard links once per tree.
    """
    total = 0
    count = 0
    seen_hard_links: set[tuple[int, int]] = set()
    if path.exists():
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = Path(dirpath) / f
                try:
                    stat = fp.stat(follow_symlinks=False)
                    # A zero inode cannot safely identify hard links.
                    if stat.st_nlink > 1 and stat.st_ino:
                        identity = (stat.st_dev, stat.st_ino)
                        if identity in seen_hard_links:
                            continue
                        seen_hard_links.add(identity)
                    total += stat.st_size
                    count += 1
                except OSError:
                    pass
    return total, count


class SettingsRoutes(Routes):
    # Serializes backup creation and restore jobs so concurrent maintenance
    # requests cannot overlap (same-second backups share a timestamped path,
    # and restores copy into the same data directory).
    _maintenance_lock = asyncio.Lock()

    def __init__(self, app, lifecycle=None):
        super().__init__(app, lifecycle)
        self._backup_progress: dict[str, BackupProgressResponse] = {}
        self._backup_task: asyncio.Task | None = None
        self._backup_task_id: str | None = None

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
                path="/api/settings/backup/tasks",
                methods=["POST"],
                endpoint=self.start_backup,
                response_model=BackupProgressResponse,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/tasks/active",
                methods=["GET"],
                endpoint=self.get_active_backup,
                response_model=BackupProgressResponse | None,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/settings/backup/tasks/{task_id}",
                methods=["GET"],
                endpoint=self.get_backup_progress,
                response_model=BackupProgressResponse,
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
            RouteDefinition(
                path="/api/settings/change-token",
                methods=["POST"],
                endpoint=self.change_access_token,
                tags=["settings"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    # ── Storage ──────────────────────────────────────────────────────────────

    async def get_storage_info(self):
        return await asyncio.to_thread(self._collect_storage_info)

    def _collect_storage_info(self) -> StorageInfoResponse:
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

    async def start_backup(self):
        if self._backup_task and not self._backup_task.done():
            return self._backup_progress[self._backup_task_id]

        # Keep a bounded history of completed tasks for polling clients.
        while len(self._backup_progress) >= 20:
            self._backup_progress.pop(next(iter(self._backup_progress)))
        task_id = uuid.uuid4().hex
        self._backup_progress[task_id] = BackupProgressResponse(id=task_id)
        self._backup_task_id = task_id
        self._backup_task = asyncio.create_task(self._run_backup(task_id))
        return self._backup_progress[task_id]

    async def get_active_backup(self):
        if self._backup_task and not self._backup_task.done():
            return self._backup_progress[self._backup_task_id]
        return None

    async def get_backup_progress(self, task_id: str):
        progress = self._backup_progress.get(task_id)
        if progress is None:
            raise HTTPException(status_code=404, detail="Backup task not found")
        return progress

    def _set_backup_progress(self, task_id: str, stage: str, percent: int):
        progress = self._backup_progress.get(task_id)
        if progress is None or progress.status in {"completed", "failed"}:
            return
        self._backup_progress[task_id] = progress.model_copy(
            update={"status": "running", "stage": stage, "percent": percent}
        )

    async def _run_backup(self, task_id: str):
        loop = asyncio.get_running_loop()

        def report(stage: str, percent: int):
            loop.call_soon_threadsafe(self._set_backup_progress, task_id, stage, percent)

        try:
            async with self._maintenance_lock:
                result = await asyncio.to_thread(self._create_backup_sync, report)
            self._backup_progress[task_id] = BackupProgressResponse(
                id=task_id, status="completed", stage="completed", percent=100, result=result
            )
        except Exception as exc:
            progress = self._backup_progress[task_id]
            error = "backup_exists" if isinstance(exc, HTTPException) and exc.status_code == 409 else None
            self._backup_progress[task_id] = progress.model_copy(
                update={"status": "failed", "stage": "failed", "error": error}
            )

    def _create_backup_sync(
        self, report: Callable[[str, int], None] | None = None
    ) -> BackupCreateResponse:
        data_path = get_data_path().resolve()
        backup_dir = _get_backup_dir()
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.zip"
        zip_path = backup_dir / filename
        marker_path = zip_path.with_suffix(".zip.part")
        if os.path.lexists(zip_path) or os.path.lexists(marker_path):
            raise HTTPException(status_code=409, detail="Backup filename already exists")
        exclude_root_dirs = {BACKUP_DIR_NAME, "dist", "updates", "temp"}

        marker_created = False
        archive_created = False
        completed = False
        try:
            # Reserve the name before scanning and hide the archive until it is closed.
            with marker_path.open("xb"):
                marker_created = True
            with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED) as zf:
                archive_created = True
                if report:
                    report("scanning", 0)
                files_to_backup = []
                for root, dirs, files in os.walk(data_path):
                    # Scope application-owned exclusions to the data root.
                    directory = Path(root)
                    is_data_root = directory == data_path
                    subdirs = [
                        d for d in dirs
                        if d != "__pycache__" and (not is_data_root or d not in exclude_root_dirs)
                    ]
                    dirs.clear()
                    if not (is_data_root or subdirs or files):
                        zf.writestr(directory.relative_to(data_path).as_posix() + "/", b"")
                    for name in subdirs + files:
                        full_path = directory / name
                        try:
                            metadata = full_path.lstat()
                        except OSError:
                            continue
                        if stat.S_ISLNK(metadata.st_mode):
                            entry = _backup_link_entry(full_path, data_path, metadata, name in subdirs)
                            if entry is not None:
                                files_to_backup.append((full_path, max(len(entry[1]), 1), entry))
                        elif stat.S_ISDIR(metadata.st_mode):
                            if os.name == "nt" and metadata.st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT:
                                logger.warning("Skipping backup directory junction %s", full_path)
                            else:
                                dirs.append(name)
                        elif stat.S_ISREG(metadata.st_mode):
                            files_to_backup.append((full_path, max(metadata.st_size, 1), None))

                total = sum(weight for _, weight, _ in files_to_backup)
                processed = 0
                last_percent = -1

                def report_compression(current: int):
                    nonlocal last_percent
                    percent = min(99, current * 99 // max(total, 1))
                    if report and percent != last_percent:
                        report("compressing", percent)
                        last_percent = percent

                report_compression(0)
                for full_path, weight, link_entry in files_to_backup:
                    if link_entry is not None:
                        zf.writestr(*link_entry)
                        processed += weight
                        report_compression(processed)
                        continue
                    try:
                        info = zipfile.ZipInfo.from_file(
                            full_path, full_path.relative_to(data_path).as_posix()
                        )
                        src = full_path.open("rb")
                    except OSError:
                        processed += weight
                        report_compression(processed)
                        continue
                    info.compress_type = zipfile.ZIP_DEFLATED
                    with src, zf.open(info, "w", force_zip64=True) as dst:
                        written = 0
                        while chunk := src.read(1024 * 1024):
                            dst.write(chunk)
                            written += len(chunk)
                            report_compression(processed + min(written, weight))
                    processed += weight
                    report_compression(processed)
                if report:
                    report("finalizing", 99)

            result = BackupCreateResponse(
                filename=filename,
                size_bytes=zip_path.stat().st_size,
                created_at=datetime.now().isoformat(),
            )
            completed = True
            return result
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail="Backup filename already exists") from exc
        finally:
            if archive_created and not completed:
                zip_path.unlink(missing_ok=True)
            if marker_created:
                marker_path.unlink(missing_ok=True)

    async def list_backups(self):
        backup_dir = _get_backup_dir()
        if not backup_dir.exists():
            return []
        backups = []
        for f in sorted(backup_dir.iterdir(), reverse=True):
            if f.suffix == ".zip" and f.is_file():
                if os.path.lexists(f.with_suffix(".zip.part")):
                    continue
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
        if backup_path.suffix != ".zip":
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        # Prevent path traversal
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")
        if os.path.lexists(backup_path.with_name(backup_path.name + ".part")):
            raise HTTPException(status_code=409, detail="Backup is still being created")
        return FileResponse(
            path=str(backup_path),
            filename=filename,
            media_type="application/zip",
        )

    async def delete_backup(self, filename: str):
        backup_path = _get_backup_dir() / filename
        if backup_path.suffix != ".zip":
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")
        if os.path.lexists(backup_path.with_name(backup_path.name + ".part")):
            raise HTTPException(status_code=409, detail="Backup is still being created")
        backup_path.unlink()
        return {"success": True}

    async def restore_from_backup(self, filename: str):
        backup_path = _get_backup_dir() / filename
        if backup_path.suffix != ".zip":
            raise HTTPException(status_code=400, detail="Invalid filename")
        if not backup_path.exists() or not backup_path.is_file():
            raise HTTPException(status_code=404, detail="Backup not found")
        if backup_path.resolve().parent != _get_backup_dir().resolve():
            raise HTTPException(status_code=400, detail="Invalid filename")
        if os.path.lexists(backup_path.with_name(backup_path.name + ".part")):
            raise HTTPException(status_code=409, detail="Backup is still being created")

        async with self._maintenance_lock:
            return await asyncio.to_thread(self._do_restore, backup_path)

    # ── Restore ──────────────────────────────────────────────────────────────

    def _do_restore(self, zip_source) -> RestoreResponse:
        """Extract a zip into a staging dir, validate, then copy to data directory."""
        data_path = get_data_path().resolve()
        exclude_dirs = {BACKUP_DIR_NAME, "__pycache__", "updates", "temp"}

        try:
            with tempfile.TemporaryDirectory() as staging_dir:
                staging_path = Path(staging_dir).resolve()
                links: list[tuple[Path, str, bool]] = []

                # Step 1: Extract to staging
                with zipfile.ZipFile(zip_source, "r") as zf:
                    for member in zf.infolist():
                        target = (staging_path / member.filename).resolve()
                        if not target.is_relative_to(staging_path):
                            raise HTTPException(status_code=400, detail="Invalid archive content")

                        parts = target.relative_to(staging_path).parts
                        if parts and parts[0] in exclude_dirs:
                            continue

                        if stat.S_ISLNK(member.external_attr >> 16):
                            if member.file_size > MAX_LINK_TARGET_BYTES:
                                raise HTTPException(status_code=400, detail="Invalid archive content")
                            link_target = os.fsdecode(zf.read(member))
                            if not _is_relative_link_target(link_target, target, staging_path):
                                raise HTTPException(status_code=400, detail="Invalid archive content")
                            target.parent.mkdir(parents=True, exist_ok=True)
                            is_directory = bool(member.external_attr & stat.FILE_ATTRIBUTE_DIRECTORY)
                            links.append((target, link_target, is_directory))
                        elif member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with zf.open(member) as src, open(target, "wb") as dst:
                                shutil.copyfileobj(src, dst)

                # Stage links after regular entries so extraction cannot write through them.
                for path, target, is_directory in links:
                    if os.path.lexists(path):
                        raise HTTPException(status_code=400, detail="Invalid archive content")
                    path.symlink_to(target, target_is_directory=is_directory)
                for path, _, _ in links:
                    try:
                        resolved = path.resolve()
                    except RuntimeError as exc:
                        raise HTTPException(status_code=400, detail="Invalid archive content") from exc
                    if not resolved.is_relative_to(staging_path) or resolved.is_symlink():
                        raise HTTPException(status_code=400, detail="Invalid archive content")
                    # A target absent from the archive must not inherit a live symlink.
                    live_target = data_path / resolved.relative_to(staging_path)
                    if not resolved.exists() and live_target.resolve() != live_target:
                        raise HTTPException(status_code=400, detail="Invalid archive content")

                # Check the live layout before changing any files.
                entries = []
                for src_file in staging_path.rglob("*"):
                    rel = src_file.relative_to(staging_path)
                    dst_file = data_path / rel
                    is_link = src_file.is_symlink()
                    is_directory = not is_link and src_file.is_dir()
                    if dst_file.parent.resolve() != dst_file.parent:
                        raise HTTPException(status_code=400, detail="Invalid archive content")
                    if is_directory and (dst_file.resolve() != dst_file or dst_file.is_symlink()):
                        raise HTTPException(status_code=400, detail="Invalid archive content")
                    if not dst_file.is_symlink() and dst_file.exists() and dst_file.is_dir() != is_directory:
                        raise HTTPException(status_code=400, detail="Invalid archive content")
                    if not is_link:
                        entries.append((src_file, dst_file, is_directory))

                for src_file, dst_file, is_directory in entries:
                    if is_directory:
                        dst_file.mkdir(parents=True, exist_ok=True)
                    else:
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        if dst_file.is_symlink():
                            with tempfile.TemporaryDirectory(dir=dst_file.parent) as pending_dir:
                                pending = Path(pending_dir) / "file"
                                shutil.copy2(src_file, pending)
                                pending.replace(dst_file)
                        else:
                            shutil.copy2(src_file, dst_file)

                for path, target, is_directory in links:
                    dst_file = data_path / path.relative_to(staging_path)
                    if dst_file.is_symlink() and os.readlink(dst_file).replace(os.sep, "/") == target:
                        attributes = getattr(dst_file.lstat(), "st_file_attributes", None)
                        if attributes is None or bool(attributes & stat.FILE_ATTRIBUTE_DIRECTORY) == is_directory:
                            continue
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.TemporaryDirectory(dir=dst_file.parent) as pending_dir:
                        pending = Path(pending_dir) / "link"
                        pending.symlink_to(target, target_is_directory=is_directory)
                        pending.replace(dst_file)

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
        async with self._maintenance_lock:
            return await asyncio.to_thread(self._do_restore, file.file)

    # ── Access Token ────────────────────────────────────────────────────────

    async def change_access_token(self, body: ChangeTokenRequest, request: Request):
        if request.app.state.disable_auth:
            raise HTTPException(status_code=400, detail="Cannot change token when auth is disabled")
        current_token = request.app.state.access_token
        # Strip like the first-run setup endpoint does, so pasted tokens with
        # stray whitespace compare and persist identically in both flows.
        old_token = body.old_token.strip()
        new_token = body.new_token.strip()
        if old_token != current_token:
            raise HTTPException(status_code=400, detail="Old token is incorrect")
        if not new_token or len(new_token) < 6:
            raise HTTPException(status_code=400, detail="New token must be at least 6 characters")
        if new_token == "disabled":
            raise HTTPException(status_code=400, detail="The token 'disabled' is reserved and cannot be used")
        _update_access_token(new_token)
        request.app.state.access_token = new_token
        return {"success": True}
