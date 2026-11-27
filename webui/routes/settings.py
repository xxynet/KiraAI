import asyncio
import json
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from contextlib import ExitStack, closing
from datetime import datetime
from pathlib import Path, PureWindowsPath
from time import monotonic, time
from typing import Annotated

from fastapi import Depends, File, HTTPException, Query, Request, UploadFile

from core.logging_manager import get_logger, inspect_rotated_logs
from core.utils.path_utils import get_data_path
from core.utils.storage import inspect_files
from webui import utils as webui_utils
from webui.models import (
    BackupCreateResponse,
    BackupProgressResponse,
    ChangeTokenRequest,
    DirectoryEntry,
    RestoreResponse,
    StorageCategory,
    StorageCategoryId,
    StorageCleanupResponse,
    StorageInfoResponse,
    StorageUsageEntry,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.routes.releases import update_package_maintenance
from webui.utils import _is_usable_access_token, _tokens_match, _update_webui_config

# Backup directory lives inside the data directory
BACKUP_DIR_NAME = "backups"
MAX_LINK_TARGET_BYTES = 128 * 1024
SQLITE_HEADER = b"SQLite format 3\0"
SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
logger = get_logger("webui", "blue")


def _get_backup_dir() -> Path:
    return get_data_path() / BACKUP_DIR_NAME


def _read_live_credentials(
    data_path: Path, app_state, onboarding_completed: bool = False
) -> tuple[str | None, bool, dict | None, bytes | None, bool]:
    """Snapshot the credentials a restart would load from the live data directory."""
    config = None
    try:
        with (data_path / "webui.json").open(encoding="utf-8") as source:
            loaded = json.load(source)
        if isinstance(loaded, dict):
            config = loaded
    except (OSError, ValueError, RecursionError):
        pass
    token = config.get("access_token") if config else None
    if not _is_usable_access_token(token):
        token = getattr(app_state, "access_token", None)
    if not _is_usable_access_token(token):
        token = None
    # Completed onboarding means the one-shot token setup is not offered again,
    # even on installs that predate the explicit token_setup_done flag.
    token_setup_done = bool(onboarding_completed or (config and config.get("token_setup_done")))
    try:
        secret = (data_path / ".jwt_secret").read_bytes()
    except OSError:
        secret = None
    secret_from_env = False
    if not secret:
        # Without a file the running module-level key is authoritative. When an
        # env var supplies it, the key must not be persisted (backups include
        # data/.jwt_secret), so only the deletion guard is needed later.
        secret_from_env = bool(os.environ.get("JWT_SECRET"))
        running_secret = getattr(webui_utils, "_JWT_SECRET", None)
        if secret_from_env:
            secret = os.environ["JWT_SECRET"].encode("utf-8")
        elif running_secret:
            secret = running_secret.encode("utf-8")
    return token, token_setup_done, config, secret, secret_from_env


def _restore_live_credentials(
    data_path: Path,
    token: str | None,
    token_setup_done: bool,
    live_config: dict | None,
    secret: bytes | None,
    secret_from_env: bool = False,
    app_state=None,
) -> None:
    """Put the live credentials back after an archive was applied.

    The archive may have written them through any path the platform treats as
    the same file (case-insensitive names, stream suffixes, etc.), so the guard
    works on the final live files instead of filtering archive entry names.
    An env-supplied signing key is never written to disk; a file the archive
    created is removed so the key cannot leak into later backups.
    Raises OSError listing every credential that could not be re-applied.
    """
    errors: list[str] = []
    if secret_from_env:
        try:
            (data_path / ".jwt_secret").unlink(missing_ok=True)
        except OSError as exc:
            errors.append(f"signing key file: {exc}")
    elif secret is not None:
        try:
            try:
                current_secret = (data_path / ".jwt_secret").read_bytes()
            except OSError:
                current_secret = None
            if current_secret != secret:
                _write_bytes_atomic(data_path / ".jwt_secret", secret)
                logger.warning("Restore attempted to replace the JWT signing key; kept the active one")
        except OSError as exc:
            errors.append(f"signing key: {exc}")
    # The running process is authoritative; the snapshot covers restarts where
    # auth is disabled and app.state only holds the sentinel.
    running_token = getattr(app_state, "access_token", None) if app_state is not None else None
    if _is_usable_access_token(running_token):
        token = running_token
    if token is not None:
        try:
            config_path = data_path / "webui.json"
            applied_config = None
            try:
                with config_path.open(encoding="utf-8") as source:
                    loaded = json.load(source)
                if isinstance(loaded, dict):
                    applied_config = loaded
            except (OSError, ValueError, RecursionError):
                pass
            config = applied_config if applied_config is not None else dict(live_config or {})
            if (
                applied_config is not None
                and config.get("access_token") == token
                and (not token_setup_done or config.get("token_setup_done"))
            ):
                pass
            else:
                config["access_token"] = token
                if token_setup_done:
                    # Restoring must not re-open the first-run token setup without the old token.
                    config["token_setup_done"] = True
                _write_bytes_atomic(config_path, json.dumps(config, indent=2, ensure_ascii=False).encode("utf-8"))
                logger.warning("Restore replaced webui.json credentials; restored the active access token")
        except (OSError, ValueError, RecursionError) as exc:
            errors.append(f"access token: {exc}")
    if errors:
        raise OSError("; ".join(errors))


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as target:
            target.write(data)
        os.replace(tmp_name, path)
    finally:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _has_sqlite_header(path: Path) -> bool:
    try:
        with path.open("rb") as source:
            return source.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def _snapshot_sqlite(source_path: Path, snapshot_path: Path) -> None:
    """Write a standalone snapshot including committed transactions in the WAL."""
    deadline = monotonic() + 15
    # Python 3.10 does not export these SQLite primary result codes.
    retry_statuses = (getattr(sqlite3, "SQLITE_BUSY", 5), getattr(sqlite3, "SQLITE_LOCKED", 6))

    def check_lock(status: int, _remaining: int, _total: int) -> None:
        if status in retry_statuses and monotonic() >= deadline:
            raise sqlite3.OperationalError(f"Timed out reading SQLite database {source_path.name}")

    source_uri = source_path.as_uri()
    if source_path.drive.startswith("\\\\"):
        # Keep Windows UNC and verbatim prefixes in the path, not the URI authority.
        source_uri = "file:////" + source_uri.removeprefix("file://")
    source_uri += "?mode=ro"
    with (
        closing(sqlite3.connect(source_uri, uri=True, timeout=1)) as source,
        closing(sqlite3.connect(snapshot_path)) as snapshot,
    ):
        source.backup(snapshot, progress=check_lock, sleep=0.1)
        if snapshot.execute("PRAGMA journal_mode=DELETE").fetchone() != ("delete",):
            raise sqlite3.DatabaseError(f"Could not finalize SQLite snapshot {source_path.name}")
        if snapshot.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise sqlite3.DatabaseError(f"SQLite snapshot failed integrity check: {source_path.name}")


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
        declared = Path(target)
        if os.name == "nt" and target.startswith("//?/"):
            # Windows readlink can return a verbatim drive or UNC path.
            unprefixed = target[4:]
            if unprefixed[:4].upper() == "UNC/":
                unprefixed = "//" + unprefixed[4:]
            if Path(unprefixed).is_absolute():
                declared = Path(unprefixed)

        # Keep an in-tree absolute link pointed at the declared entry, even if
        # that entry is itself a symlink.
        if declared.is_relative_to(data_path) and ".." not in declared.parts:
            relative = os.path.relpath(declared, path.parent).replace(os.sep, "/")
            if _is_relative_link_target(relative, path, data_path):
                try:
                    if (path.parent / relative).resolve() == resolved:
                        target = relative
                except (OSError, RuntimeError) as exc:
                    logger.debug("Could not verify relative backup symlink %s: %s", path, exc)
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


STORAGE_USAGE_DIRECTORIES = {
    "sessions": {"memory", "webchat"},
    "media": {"session_media", "files", "sticker"},
    "database": set(),
    "plugins": {"plugins", "plugin_data", "plugin_src"},
    "runtime": {"tools", "dist", "updates"},
    "backups": {BACKUP_DIR_NAME},
    "temp": {"temp"},
    "logs": {"logs"},
    "other": set(),
}


def _storage_usage_group(relative_path: Path) -> str:
    for category, directories in STORAGE_USAGE_DIRECTORIES.items():
        if relative_path.parts[0] in directories:
            return category
    if len(relative_path.parts) == 1:
        name = relative_path.name.lower()
        database_name = name.removesuffix("-wal").removesuffix("-shm").removesuffix("-journal")
        if database_name.endswith((".db", ".sqlite", ".sqlite3")):
            return "database"
        if name == "log.log" or name.startswith("log.log.") or name.endswith(".log"):
            return "logs"
    return "other"


def _calc_dir_size(path: Path, *, usage: dict[str, int] | None = None) -> tuple[int, int]:
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
                    if usage is not None:
                        group = _storage_usage_group(fp.relative_to(path))
                        usage[group] += stat.st_size
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
                path="/api/settings/storage/{category}/cleanup",
                methods=["POST"],
                endpoint=self.cleanup_storage,
                response_model=StorageCleanupResponse,
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

    @staticmethod
    def _validate_retention_days(retention_days: int) -> None:
        if retention_days not in (7, 30, 90):
            raise HTTPException(status_code=422, detail="Retention must be 7, 30, or 90 days")

    async def get_storage_info(self, retention_days: Annotated[int, Query()] = 30):
        self._validate_retention_days(retention_days)
        info = await asyncio.to_thread(self._collect_storage_info)
        for category in ("message_archives", "temp", "logs", "update_packages"):
            days = retention_days if category == "message_archives" else 1
            usage = await self._inspect_storage_files(category, time() - days * 86400)
            info.categories.append(StorageCategory(
                id=category,
                retention_days=retention_days if category == "message_archives" else None,
                **{key: usage[key] for key in ("size_bytes", "item_count", "cleanable_bytes", "cleanable_count")},
            ))
        db = self.lifecycle.db_service if self.lifecycle else None
        cache = StorageCategory(id="image_descriptions", available=db is not None)
        if db is not None:
            usage = await db.get_image_desc_cache_usage()
            cache.size_bytes = cache.cleanable_bytes = usage["size_bytes"]
            cache.item_count = cache.cleanable_count = usage["item_count"]
        info.categories.insert(0, cache)
        return info

    @staticmethod
    async def _run_storage_worker(action, *args, **kwargs):
        task = asyncio.create_task(asyncio.to_thread(action, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # Repeated cancellation must not release maintenance gates before the thread exits.
            while not task.done():
                try:
                    await asyncio.wait({task})
                except asyncio.CancelledError:
                    continue
            # Preserve worker exceptions on cancellation, matching the normal path.
            task.result()
            raise

    async def _inspect_storage_files(self, category: str, cutoff: float, *, delete: bool = False):
        if category == "message_archives":
            root = get_data_path() / "session_media" / "archive"
            options = {
                "delete": delete, "recursive": False, "use_mtime": True,
                "boundary": get_data_path(),
                "include": lambda path: re.fullmatch(r"[0-9a-f]{64}", path.name) is not None,
            }
            if not delete:
                return await self._run_storage_worker(inspect_files, root, cutoff, **options)
            history = getattr(self.lifecycle, "message_history", None)
            if history is None:
                raise HTTPException(status_code=503, detail="Message history service unavailable")
            async with history.maintenance() as protected:
                if protected is None:
                    raise HTTPException(status_code=409, detail="Messages are being archived; retry cleanup later")
                return await self._run_storage_worker(inspect_files, root, cutoff, **options)
        if category == "logs":
            return await self._run_storage_worker(inspect_rotated_logs, delete=delete)
        if category == "update_packages":
            root = get_data_path() / "updates"
            options = {
                "delete": delete, "recursive": False,
                "include": lambda path: path.suffix == ".zip",
            }
            if delete:
                async with update_package_maintenance():
                    return await self._run_storage_worker(inspect_files, root, cutoff, **options)
            return await self._run_storage_worker(inspect_files, root, cutoff, **options)
        if category == "temp":
            return await self._run_storage_worker(inspect_files, get_data_path() / "temp", cutoff, delete=delete)
        raise HTTPException(status_code=422, detail="Unsupported storage cleanup category")

    async def cleanup_storage(self, category: StorageCategoryId, retention_days: Annotated[int, Query()] = 30):
        self._validate_retention_days(retention_days)
        async with self._maintenance_lock:
            if category == "image_descriptions":
                db = self.lifecycle.db_service if self.lifecycle else None
                if db is None:
                    raise HTTPException(status_code=503, detail="Database service unavailable")
                return StorageCleanupResponse(deleted_count=await db.clear_image_desc_cache())
            days = retention_days if category == "message_archives" else 1
            usage = await self._inspect_storage_files(category, time() - days * 86400, delete=True)
            return StorageCleanupResponse(**{
                key: usage[key] for key in ("deleted_count", "deleted_bytes", "failed_count")
            })

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

        usage = dict.fromkeys(STORAGE_USAGE_DIRECTORIES, 0)
        total_size, _ = _calc_dir_size(data_path, usage=usage)

        return StorageInfoResponse(
            data_path=str(data_path),
            total_size_bytes=total_size,
            disk_total_bytes=disk.total,
            disk_used_bytes=disk.used,
            disk_free_bytes=disk.free,
            directories=directories,
            usage_breakdown=[StorageUsageEntry(id=key, size_bytes=size) for key, size in usage.items()],
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
            if error is None:
                logger.exception("Backup creation failed")
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

                sqlite_paths = {
                    path for path, _, link in files_to_backup
                    if link is None and _has_sqlite_header(path)
                }
                sqlite_sidecars = {
                    path.with_name(path.name + suffix)
                    for path in sqlite_paths for suffix in SQLITE_SIDECAR_SUFFIXES
                }
                files_to_backup = [
                    (path, weight, link)
                    for path, weight, link in files_to_backup
                    if link is not None or path not in sqlite_sidecars
                ]
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
                    with ExitStack() as files:
                        input_path = full_path
                        is_sqlite = full_path in sqlite_paths
                        if is_sqlite:
                            temp_dir = files.enter_context(tempfile.TemporaryDirectory(dir=backup_dir))
                            input_path = Path(temp_dir) / "snapshot.sqlite"
                            _snapshot_sqlite(full_path, input_path)
                        try:
                            info = zipfile.ZipInfo.from_file(
                                full_path, full_path.relative_to(data_path).as_posix()
                            )
                            src = files.enter_context(input_path.open("rb"))
                        except OSError:
                            if is_sqlite:
                                raise
                            processed += weight
                            report_compression(processed)
                            continue
                        info.compress_type = zipfile.ZIP_DEFLATED
                        with zf.open(info, "w", force_zip64=True) as dst:
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
        """Extract a zip into a staging dir, validate, then copy to data directory.

        The running instance's access token, token-setup flag and JWT signing
        key are re-applied afterwards, so an archive can never replace them.
        """
        data_path = get_data_path().resolve()
        exclude_dirs = {BACKUP_DIR_NAME, "__pycache__", "updates", "temp"}
        lifecycle_config = getattr(self.lifecycle, "kira_config", None)
        onboarding = lifecycle_config.get("onboarding", {}) if isinstance(lifecycle_config, dict) else {}
        onboarding_completed = isinstance(onboarding, dict) and bool(onboarding.get("completed", False))
        live_credentials = _read_live_credentials(data_path, self.app.state, onboarding_completed)

        result: RestoreResponse | None = None
        pending_error: HTTPException | None = None
        apply_started = False
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

                # From here on live files change, so credentials must be re-asserted.
                if entries or links:
                    apply_started = True
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

            result = RestoreResponse(success=True, message="Restore completed successfully")
        except zipfile.BadZipFile:
            pending_error = HTTPException(status_code=400, detail="Invalid zip file")
        except HTTPException as exc:
            pending_error = exc
        except Exception as e:
            result = RestoreResponse(success=False, message=f"Restore failed: {e}")

        # A rejected archive never touched live files, and rewriting credentials
        # then would clobber edits made after startup.
        if apply_started:
            try:
                _restore_live_credentials(
                    data_path, *live_credentials, app_state=self.app.state
                )
            except Exception as exc:
                logger.exception("Could not keep the active credentials after restore")
                credential_note = (
                    "the active credentials could not be preserved: "
                    f"{exc}. Check data/webui.json and data/.jwt_secret."
                )
                if result is not None:
                    prefix = "Restore finished, but " if result.success else f"{result.message} Additionally, "
                    result = RestoreResponse(success=False, message=prefix + credential_note)
        if pending_error is not None:
            raise pending_error
        return result

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
        # Share the maintenance lock so a concurrent restore cannot re-apply the
        # previous token between the config write and the in-memory update.
        # A restore may hold it for minutes; fail fast instead of hanging.
        try:
            await asyncio.wait_for(self._maintenance_lock.acquire(), timeout=5)
        except asyncio.TimeoutError:
            raise HTTPException(
                status_code=409, detail="Backup or restore is in progress"
            ) from None
        try:
            current_token = request.app.state.access_token
            # Strip like the first-run setup endpoint does, so pasted tokens with
            # stray whitespace compare and persist identically in both flows.
            old_token = body.old_token.strip()
            new_token = body.new_token.strip()
            if not _tokens_match(old_token, current_token):
                raise HTTPException(status_code=400, detail="Old token is incorrect")
            if not new_token or len(new_token) < 6:
                raise HTTPException(status_code=400, detail="New token must be at least 6 characters")
            if new_token == "disabled":
                raise HTTPException(status_code=400, detail="The token 'disabled' is reserved and cannot be used")
            _update_webui_config(access_token=new_token)
            request.app.state.access_token = new_token
        finally:
            self._maintenance_lock.release()
        return {"success": True}
