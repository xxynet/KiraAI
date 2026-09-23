import asyncio
import heapq
import os
import stat
import time
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Literal, Optional, Tuple

from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.config import KiraConfig

logger = get_logger("atm", "yellow")

FileKey = Tuple[int, int]
FileVersion = Tuple[int, int, int, int, int]
FileCacheEntry = Tuple[int, float, float]
FileCandidate = Tuple[str, int, float, float]
DirectoryCandidate = Tuple[Path, FileKey]
DeleteStatus = Literal["deleted", "missing", "changed", "failed"]
DeleteResult = Tuple[DeleteStatus, int, Optional[str], Optional[FileVersion]]


class AsyncTempMonitor:
    def __init__(
        self,
        folder_path: str,
        kira_config: 'KiraConfig',
        check_interval: int = 60,
        batch_size: int = 20,
        file_protection_seconds: int = 60,
    ):
        """Initialize the periodic temporary-directory cleaner."""
        self.folder_path = Path(folder_path)
        self.kira_config = kira_config
        self._default_check_interval = check_interval
        self.check_interval = check_interval
        self.batch_size = batch_size
        self.file_protection_seconds = file_protection_seconds
        self.folder_path.mkdir(parents=True, exist_ok=True)

        self._refresh_config()

        # The file cache is a fresh snapshot rebuilt before every cleanup.
        self.file_cache: Dict[str, FileCacheEntry] = {}
        self.total_size = 0
        self._file_versions: Dict[str, FileVersion] = {}
        self._first_seen: Dict[str, Tuple[FileKey, float]] = {}
        self._pending_retries: Dict[str, FileVersion] = {}
        self._has_scanned = False
        self._cleanup_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._config_changed_event = asyncio.Event()

    @staticmethod
    def _file_key(file_stat: os.stat_result) -> FileKey:
        """Return the stable identity used to distinguish path replacements."""
        return file_stat.st_dev, file_stat.st_ino

    @staticmethod
    def _file_version(file_stat: os.stat_result) -> FileVersion:
        """Return the scanned version used to detect changes before deletion."""
        return (
            file_stat.st_dev,
            file_stat.st_ino,
            file_stat.st_size,
            file_stat.st_mtime_ns,
            file_stat.st_ctime_ns,
        )

    def _refresh_config(self):
        """Read latest config values from KiraConfig to support runtime changes."""
        cache_config = self.kira_config.get_config("bot_config.cache", {}) or {}
        max_size_mb = cache_config.get("max_size_mb", 50)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.max_files = cache_config.get("max_files", 50)
        max_age_hours = cache_config.get("max_age_hours", 24)
        self.max_age_seconds = max_age_hours * 3600

        interval_minutes = cache_config.get("check_interval_minutes")
        if (
            isinstance(interval_minutes, (int, float))
            and not isinstance(interval_minutes, bool)
            and interval_minutes > 0
        ):
            self.check_interval = max(1, int(interval_minutes * 60))
        else:
            self.check_interval = self._default_check_interval

    def notify_config_changed(self):
        """Apply runtime config changes and wake the periodic scheduler."""
        self._refresh_config()
        self._config_changed_event.set()

    async def _scan_folder(self) -> List[DirectoryCandidate]:
        """Rebuild the file snapshot and capture protected directory state."""
        loop = asyncio.get_running_loop()
        previous_first_seen = self._first_seen.copy()
        has_scanned = self._has_scanned
        protection_seconds = self.file_protection_seconds

        def scan_folder():
            cache: Dict[str, FileCacheEntry] = {}
            versions: Dict[str, FileVersion] = {}
            first_seen_entries: Dict[str, Tuple[FileKey, float]] = {}
            eligible_directories: List[DirectoryCandidate] = []
            total = 0
            current_time = time.time()

            def on_walk_error(error: OSError):
                logger.debug(f"Skip temporary directory during scan: {error}")

            for root, directory_names, file_names in os.walk(
                self.folder_path,
                onerror=on_walk_error,
                followlinks=False,
            ):
                root_path = Path(root)

                for directory_name in directory_names:
                    directory = root_path / directory_name
                    try:
                        directory_stat = directory.lstat()
                        if not stat.S_ISDIR(directory_stat.st_mode):
                            continue
                        if (
                            protection_seconds > 0
                            and current_time - directory_stat.st_mtime
                            < protection_seconds
                        ):
                            continue
                        eligible_directories.append(
                            (directory, self._file_key(directory_stat))
                        )
                    except OSError as e:
                        logger.debug(
                            f"Skip temporary directory {directory} due to stat error: {e}"
                        )

                for file_name in file_names:
                    file_path = root_path / file_name
                    try:
                        file_stat = file_path.stat()
                        if not stat.S_ISREG(file_stat.st_mode):
                            continue
                    except OSError as e:
                        logger.debug(
                            f"Skip temporary file {file_path} due to stat error: {e}"
                        )
                        continue

                    path_str = str(file_path)
                    file_key = self._file_key(file_stat)
                    previous = previous_first_seen.get(path_str)
                    if previous is not None and previous[0] == file_key:
                        first_seen = previous[1]
                    elif has_scanned:
                        first_seen = current_time
                    else:
                        # Preserve the previous startup behavior for files that
                        # existed before the cleaner started.
                        first_seen = file_stat.st_mtime

                    cache[path_str] = (
                        file_stat.st_size,
                        file_stat.st_mtime,
                        first_seen,
                    )
                    versions[path_str] = self._file_version(file_stat)
                    first_seen_entries[path_str] = (file_key, first_seen)
                    total += file_stat.st_size

            return (
                cache,
                versions,
                first_seen_entries,
                eligible_directories,
                total,
            )

        (
            self.file_cache,
            self._file_versions,
            self._first_seen,
            eligible_directories,
            self.total_size,
        ) = await loop.run_in_executor(None, scan_folder)
        self._has_scanned = True

        # A removed, replaced, or modified path is not the same failed
        # deletion and must not inherit its pending retry state.
        self._pending_retries = {
            path_str: pending_version
            for path_str, pending_version in self._pending_retries.items()
            if self._file_versions.get(path_str) == pending_version
        }

        logger.debug(
            f"Temporary folder scan completed: {len(self.file_cache)} files, "
            f"total size: {self.total_size / 1024 / 1024:.2f}MB"
        )
        return eligible_directories

    async def _get_oldest_files(
        self,
        limit: int = 10,
        exclude: Optional[set] = None,
    ) -> List[FileCandidate]:
        """Get oldest unattempted files outside the protection period."""
        current_time = time.time()
        eligible_files = []

        for path_str, (size, mtime, first_seen) in self.file_cache.items():
            if exclude and path_str in exclude:
                continue
            if current_time - first_seen < self.file_protection_seconds:
                continue
            eligible_files.append((path_str, size, mtime, first_seen))

        if not eligible_files and not exclude:
            logger.warning("No eligible files for deletion (all files are protected)")
            return []

        return heapq.nsmallest(limit, eligible_files, key=lambda item: item[3])

    async def _get_expired_files(self) -> List[FileCandidate]:
        """Get files that have exceeded the configured maximum age."""
        current_time = time.time()
        expired_files = []

        for path_str, (size, mtime, first_seen) in self.file_cache.items():
            if current_time - first_seen > self.max_age_seconds:
                expired_files.append((path_str, size, mtime, first_seen))

        expired_files.sort(key=lambda item: item[3])
        return expired_files

    async def _get_files_exceeding_limit(self) -> List[FileCandidate]:
        """Get count-limit candidates ordered from oldest to newest."""
        if len(self.file_cache) <= self.max_files:
            return []

        current_time = time.time()
        eligible_files = []
        for path_str, (size, mtime, first_seen) in self.file_cache.items():
            if current_time - first_seen < self.file_protection_seconds:
                continue
            eligible_files.append((path_str, size, mtime, first_seen))

        eligible_files.sort(key=lambda item: item[3])
        return eligible_files

    async def _delete_file(
        self,
        path_str: str,
        expected_version: Optional[FileVersion] = None,
    ) -> DeleteResult:
        """Delete one unchanged file and return its remaining version on failure."""
        loop = asyncio.get_running_loop()

        def delete():
            file_path = Path(path_str)
            try:
                file_stat = file_path.stat()
                if not stat.S_ISREG(file_stat.st_mode):
                    return "changed", 0, None, None
                if (
                    expected_version is not None
                    and self._file_version(file_stat) != expected_version
                ):
                    return "changed", 0, None, None

                size = file_stat.st_size
                try:
                    file_path.unlink()
                except PermissionError:
                    # Git objects are commonly read-only on Windows. Make the
                    # file owner-writable, then retry exactly once.
                    file_path.chmod(file_stat.st_mode | stat.S_IWRITE)
                    file_path.unlink()
                return "deleted", size, None, None
            except FileNotFoundError:
                return "missing", 0, None, None
            except OSError as e:
                error = f"{type(e).__name__}: {e}"
                try:
                    remaining_stat = file_path.stat()
                    remaining_version = (
                        self._file_version(remaining_stat)
                        if stat.S_ISREG(remaining_stat.st_mode)
                        else None
                    )
                    if (
                        expected_version is not None
                        and remaining_version is not None
                        and remaining_version[:4] != expected_version[:4]
                    ):
                        return "changed", 0, None, None
                except OSError:
                    remaining_version = None
                return "failed", 0, error, remaining_version

        return await loop.run_in_executor(None, delete)

    async def _cleanup_empty_dirs(
        self,
        candidates: List[DirectoryCandidate],
    ) -> None:
        """Remove empty directories that were unprotected at scan time."""
        loop = asyncio.get_running_loop()

        def cleanup_empty_dirs():
            for directory, expected_key in sorted(
                candidates,
                key=lambda item: len(item[0].parts),
                reverse=True,
            ):
                try:
                    directory_stat = directory.lstat()
                    if self._file_key(directory_stat) != expected_key:
                        continue
                    directory.rmdir()
                except OSError:
                    continue

        await loop.run_in_executor(None, cleanup_empty_dirs)

    async def cleanup(self):
        """Scan the temporary directory and execute one cleanup cycle."""
        async with self._cleanup_lock:
            self._refresh_config()
            directory_candidates = await self._scan_folder()
            current_time = time.time()
            expired_files = await self._get_expired_files()
            pending_files = [
                (path_str, *self.file_cache[path_str])
                for path_str in self._pending_retries
                if path_str in self.file_cache
            ]

            needs_cleanup = (
                self.total_size > self.max_size_bytes
                or len(self.file_cache) > self.max_files
                or expired_files
                or pending_files
            )

            if not needs_cleanup:
                await self._cleanup_empty_dirs(directory_candidates)
                return

            logger.info(
                f"CLEANUP TRIGGERED - Files: {len(self.file_cache)}/{self.max_files}, "
                f"Size: {self.total_size / 1024 / 1024:.2f}MB/"
                f"{self.max_size_bytes / 1024 / 1024:.2f}MB, "
                f"Pending retries: {len(pending_files)}"
            )

            deleted_count = 0
            freed_space = 0
            attempted_paths = set()
            failed_deletions: Dict[str, str] = {}

            async def delete_candidate(path_str: str):
                nonlocal deleted_count, freed_space

                if path_str in attempted_paths:
                    return None
                attempted_paths.add(path_str)

                expected_version = self._file_versions.get(path_str)
                status, deleted_size, error, remaining_version = (
                    await self._delete_file(path_str, expected_version)
                )
                if status == "failed":
                    failed_deletions[path_str] = error or "unknown error"
                    if remaining_version is not None:
                        self._pending_retries[path_str] = remaining_version
                    else:
                        self._pending_retries.pop(path_str, None)
                    return status

                if status == "changed":
                    self._pending_retries.pop(path_str, None)
                    logger.debug(
                        f"Skipping changed temporary file until the next scan: {path_str}"
                    )
                    return status

                cached = self.file_cache.pop(path_str, None)
                self._file_versions.pop(path_str, None)
                self._first_seen.pop(path_str, None)
                self._pending_retries.pop(path_str, None)
                if cached is not None:
                    self.total_size = max(0, self.total_size - cached[0])

                if status == "deleted":
                    deleted_count += 1
                    freed_space += deleted_size
                return status

            # Retry files that failed during an earlier cleanup cycle first.
            for path_str, _size, _mtime, _first_seen in pending_files:
                await delete_candidate(path_str)

            if expired_files:
                logger.debug(
                    f"Found {len(expired_files)} expired files "
                    f"(older than {self.max_age_seconds / 3600:.1f}h)"
                )
                min_expired_protection = self.file_protection_seconds // 4
                for path_str, _size, _mtime, first_seen in expired_files:
                    file_age = current_time - first_seen
                    if file_age < min_expired_protection:
                        logger.warning(
                            f"Skipping recently created expired file: "
                            f"{Path(path_str).name} (age: {file_age:.1f}s < "
                            f"protection: {min_expired_protection}s)"
                        )
                        continue
                    await delete_candidate(path_str)

            excess_files = await self._get_files_exceeding_limit()
            if excess_files:
                logger.debug(
                    f"Found {len(excess_files)} count-limit candidates "
                    f"(limit: {self.max_files})"
                )
                for path_str, _size, _mtime, _first_seen in excess_files:
                    if len(self.file_cache) <= self.max_files:
                        break
                    await delete_candidate(path_str)

            if self.total_size > self.max_size_bytes:
                oldest_files = await self._get_oldest_files(
                    limit=self.batch_size,
                    exclude=attempted_paths,
                )
                for path_str, _size, _mtime, first_seen in oldest_files:
                    if self.total_size <= self.max_size_bytes:
                        break

                    file_age = current_time - first_seen
                    if file_age < self.file_protection_seconds:
                        logger.error(
                            f"ATTEMPTED TO DELETE PROTECTED FILE "
                            f"(age: {file_age:.2f}s): "
                            f"{Path(path_str).name} - SKIPPING"
                        )
                        continue

                    await delete_candidate(path_str)

            await self._cleanup_empty_dirs(directory_candidates)

            if deleted_count > 0:
                logger.info(
                    f"Cleanup completed: deleted {deleted_count} files, "
                    f"freed {freed_space / 1024 / 1024:.2f}MB, "
                    f"remaining: {len(self.file_cache)} files, "
                    f"{self.total_size / 1024 / 1024:.2f}MB"
                )

            if failed_deletions:
                failure_items = list(failed_deletions.items())
                details = "; ".join(
                    f"{path}: {error}" for path, error in failure_items[:3]
                )
                omitted = len(failure_items) - 3
                if omitted > 0:
                    details += f"; and {omitted} more"
                logger.warning(
                    f"Cleanup completed with {len(failed_deletions)} "
                    f"deletion failure(s); will retry on the next cleanup cycle. "
                    f"{details}"
                )

    async def _periodic_cleanup_loop(self):
        """Run cleanup periodically and react to runtime interval changes."""
        while not self._stop_event.is_set():
            try:
                try:
                    await asyncio.wait_for(
                        self._config_changed_event.wait(),
                        timeout=self.check_interval,
                    )
                    self._config_changed_event.clear()
                    continue
                except asyncio.TimeoutError:
                    pass

                if self._stop_event.is_set():
                    break
                await self.cleanup()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    async def start_monitoring(self):
        """Start periodic temporary-directory cleanup."""
        logger.info("=" * 60)
        logger.info(f"Starting periodic cleanup for folder: {self.folder_path}")
        logger.info(f"Max size: {self.max_size_bytes / 1024 / 1024:.2f}MB")
        logger.info(f"Max files: {self.max_files}")
        logger.info(f"Max age: {self.max_age_seconds / 3600:.1f} hours")
        logger.info(
            f"File protection period: {self.file_protection_seconds} seconds"
        )
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info("=" * 60)

        try:
            await self.cleanup()
            await self._periodic_cleanup_loop()
        except asyncio.CancelledError:
            logger.info("Periodic cleanup cancelled")
        finally:
            logger.info("Periodic cleanup stopped")

    async def stop_monitoring(self):
        """Stop periodic cleanup and wake the scheduler immediately."""
        self._stop_event.set()
        self._config_changed_event.set()
