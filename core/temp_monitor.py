import asyncio
import heapq
import stat
import time
from pathlib import Path
from watchfiles import awatch
from typing import Dict, List, Literal, Optional, Tuple

from typing import TYPE_CHECKING

from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.config import KiraConfig

logger = get_logger("atm", "yellow")


class AsyncTempMonitor:
    def __init__(self, folder_path: str, kira_config: 'KiraConfig',
                 check_interval: int = 60, batch_size: int = 20,
                 file_protection_seconds: int = 60):
        """
        Asynchronous temporary folder monitor

        Args:
            folder_path: Path of the folder to monitor
            kira_config: KiraConfig instance for dynamic config reading
            check_interval: Minimum check interval in seconds
            batch_size: Maximum number of files to clean up at once
            file_protection_seconds: File protection period in seconds, new files won't be deleted within this period
        """
        self.folder_path = Path(folder_path)
        self.kira_config = kira_config
        self._default_check_interval = check_interval
        self.check_interval = check_interval
        self.batch_size = batch_size
        self.file_protection_seconds = file_protection_seconds
        self.folder_path.mkdir(parents=True, exist_ok=True)

        # Initialize from config
        self._refresh_config()

        # Cache file information: path -> (size, mtime, creation_time)
        # creation_time is when the file was first seen by the monitor
        self.file_cache: Dict[str, Tuple[int, float, float]] = {}
        self.total_size = 0
        self.last_check_time = 0
        self._cleanup_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._config_changed_event = asyncio.Event()

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
            self.check_interval = int(interval_minutes * 60)
        else:
            self.check_interval = self._default_check_interval

    def notify_config_changed(self):
        """Apply runtime config changes and wake the periodic scheduler."""
        self._refresh_config()
        self._config_changed_event.set()

    async def _build_cache(self):
        """Build file cache asynchronously"""
        loop = asyncio.get_running_loop()

        def scan_folder():
            cache = {}
            total = 0
            current_time = time.time()
            for file_path in self.folder_path.rglob('*'):
                if file_path.is_file():
                    stat = file_path.stat()
                    # For existing files, use mtime as creation_time
                    cache[str(file_path)] = (stat.st_size, stat.st_mtime, stat.st_mtime)
                    total += stat.st_size
            return cache, total

        # Execute blocking IO operations in thread pool
        self.file_cache, self.total_size = await loop.run_in_executor(None, scan_folder)

        logger.info(f"Cache initialization completed: {len(self.file_cache)} files, "
                    f"total size: {self.total_size / 1024 / 1024:.2f}MB")

    async def _update_cache(self, change_type: int, file_path: str):
        """Update cache asynchronously"""
        path_str = str(file_path)
        loop = asyncio.get_event_loop()
        current_time = time.time()

        if change_type == 1:  # Added
            # Only add if not already in cache
            if path_str not in self.file_cache:
                def add_file():
                    p = Path(file_path)
                    if p.exists() and p.is_file():
                        stat = p.stat()
                        return stat.st_size, stat.st_mtime
                    return None, None

                result = await loop.run_in_executor(None, add_file)
                if result[0] is not None:
                    size, mtime = result
                    # Use current_time as creation_time for new files
                    self.file_cache[path_str] = (size, mtime, current_time)
                    self.total_size += size
                    logger.debug(f"File added to cache: {Path(path_str).name}, size: {size}, mtime: {mtime}, creation_time: {current_time}")

        elif change_type == 2:  # Modified
            if path_str in self.file_cache:
                old_size, old_mtime, creation_time = self.file_cache[path_str]

                def modify_file():
                    p = Path(file_path)
                    if p.exists() and p.is_file():
                        stat = p.stat()
                        return stat.st_size, stat.st_mtime
                    return None, None

                result = await loop.run_in_executor(None, modify_file)
                if result[0] is not None:
                    new_size, new_mtime = result
                    # Keep the original creation_time
                    self.file_cache[path_str] = (new_size, new_mtime, creation_time)
                    self.total_size = self.total_size - old_size + new_size

        elif change_type == 3:  # Deleted
            if path_str in self.file_cache:
                old_size, _, _ = self.file_cache[path_str]
                del self.file_cache[path_str]
                self.total_size -= old_size

    async def _get_oldest_files(self, limit: int = 10) -> List[Tuple[str, int, float, float]]:
        """Get oldest files based on creation_time, skip files within protection period"""
        current_time = time.time()
        eligible_files = []
        protected_count = 0

        for path_str, (size, mtime, creation_time) in self.file_cache.items():
            # Use creation_time to check protection period
            file_age = current_time - creation_time
            if file_age < self.file_protection_seconds:
                protected_count += 1
                continue

            eligible_files.append((path_str, size, mtime, creation_time))

        if not eligible_files:
            logger.warning("No eligible files for deletion (all files are protected)")
            return []

        # Use nsmallest to get files with smallest creation_time (oldest files)
        oldest_files = heapq.nsmallest(limit, eligible_files, key=lambda x: x[3])

        return oldest_files

    async def _get_expired_files(self) -> List[Tuple[str, int, float, float]]:
        """Get files that have exceeded the max age"""
        current_time = time.time()
        expired_files = []

        for path_str, (size, mtime, creation_time) in self.file_cache.items():
            # Check if file age exceeds max age
            file_age = current_time - creation_time
            if file_age > self.max_age_seconds:
                expired_files.append((path_str, size, mtime, creation_time))

        # Sort by age (oldest first)
        expired_files.sort(key=lambda x: x[3])
        return expired_files

    async def _get_files_exceeding_limit(self) -> List[Tuple[str, int, float, float]]:
        """Get files when total file count exceeds max_files limit, skipping protected files"""
        if len(self.file_cache) <= self.max_files:
            return []

        current_time = time.time()
        # Filter out files within protection period, consistent with _get_oldest_files
        eligible_files = []
        for path_str, (size, mtime, creation_time) in self.file_cache.items():
            file_age = current_time - creation_time
            if file_age < self.file_protection_seconds:
                continue
            eligible_files.append((path_str, size, mtime, creation_time))

        # Recalculate excess count based on eligible files plus protected ones
        # that will remain regardless
        excess_count = len(self.file_cache) - self.max_files
        if excess_count <= 0 or not eligible_files:
            return []
        return heapq.nsmallest(min(excess_count, len(eligible_files)), eligible_files, key=lambda x: x[3])

    async def _delete_file(self, path_str: str) -> Tuple[Literal["deleted", "missing", "failed"], int, Optional[str]]:
        """Delete a single file, retrying once after clearing read-only mode."""
        loop = asyncio.get_running_loop()

        def delete():
            file_path = Path(path_str)
            try:
                if not file_path.exists() or not file_path.is_file():
                    return "missing", 0, None

                size = file_path.stat().st_size
                try:
                    file_path.unlink()
                except PermissionError:
                    # Git objects are commonly read-only on Windows. Make the
                    # file owner-writable, then retry exactly once.
                    mode = file_path.stat().st_mode
                    file_path.chmod(mode | stat.S_IWRITE)
                    file_path.unlink()
                return "deleted", size, None
            except FileNotFoundError:
                return "missing", 0, None
            except OSError as e:
                return "failed", 0, f"{type(e).__name__}: {e}"

        return await loop.run_in_executor(None, delete)

    async def _cleanup_empty_dirs(self):
        """Remove empty subdirectories from deepest to shallowest."""
        loop = asyncio.get_running_loop()

        def cleanup_empty_dirs():
            if not self.folder_path.exists():
                return

            directories = (
                path for path in self.folder_path.rglob('*') if path.is_dir()
            )
            for directory in sorted(
                directories, key=lambda path: len(path.parts), reverse=True
            ):
                try:
                    directory.rmdir()
                except OSError:
                    continue

        await loop.run_in_executor(None, cleanup_empty_dirs)

    async def cleanup(self):
        """Execute cleanup asynchronously."""
        # Use lock to prevent concurrent cleanup
        async with self._cleanup_lock:
            self._refresh_config()
            current_time = time.time()

            # Control check frequency (inside lock to avoid TOCTOU race)
            if current_time - self.last_check_time < self.check_interval:
                return

            self.last_check_time = current_time

            # Check for expired files first
            expired_files = await self._get_expired_files()

            needs_cleanup = (
                self.total_size > self.max_size_bytes
                or len(self.file_cache) > self.max_files
                or expired_files
            )

            if not needs_cleanup:
                return

            logger.info(f"CLEANUP TRIGGERED - Files: {len(self.file_cache)}/{self.max_files}, "
                        f"Size: {self.total_size / 1024 / 1024:.2f}MB/{self.max_size_bytes / 1024 / 1024:.2f}MB")

            deleted_count = 0
            freed_space = 0
            attempted_paths = set()
            failed_deletions: Dict[str, str] = {}

            async def delete_candidate(path_str: str):
                nonlocal deleted_count, freed_space

                # A file can qualify as expired, excessive, and oversized in
                # the same cleanup. Never retry a failure within one cycle.
                if path_str in attempted_paths:
                    return None
                attempted_paths.add(path_str)

                status, deleted_size, error = await self._delete_file(path_str)
                if status == "failed":
                    failed_deletions[path_str] = error or "unknown error"
                    return status

                cached = self.file_cache.pop(path_str, None)
                if cached is not None:
                    self.total_size = max(0, self.total_size - cached[0])

                if status == "deleted":
                    deleted_count += 1
                    freed_space += deleted_size
                return status

            # Phase 1: Delete expired files (by max_age_hours)
            if expired_files:
                logger.debug(f"Found {len(expired_files)} expired files (older than {self.max_age_seconds / 3600:.1f}h)")
                # Use a reduced protection period for expired files to avoid
                # deleting files that are still actively in use when max_age
                # is changed at runtime
                min_expired_protection = self.file_protection_seconds // 4
                for path_str, size, mtime, creation_time in expired_files:
                    file_age = current_time - creation_time
                    if file_age < min_expired_protection:
                        logger.warning(f"Skipping recently created expired file: "
                                       f"{Path(path_str).name} (age: {file_age:.1f}s < "
                                       f"protection: {min_expired_protection}s)")
                        continue
                    status = await delete_candidate(path_str)
                    if status == "deleted":
                        file_age_hours = (current_time - creation_time) / 3600
                        logger.debug(f"DELETED expired: {Path(path_str).name} (age: {file_age_hours:.1f}h, size: {size / 1024:.2f}KB)")

            # Phase 2: Delete files exceeding max_files limit
            # Protection period already filtered inside _get_files_exceeding_limit
            excess_files = await self._get_files_exceeding_limit()
            if excess_files:
                logger.debug(f"Found {len(excess_files)} excess files (limit: {self.max_files})")
                for path_str, size, mtime, creation_time in excess_files:
                    status = await delete_candidate(path_str)
                    if status == "deleted":
                        logger.debug(f"DELETED excess: {Path(path_str).name} (size: {size / 1024:.2f}KB)")

            # Phase 3: Delete oldest files if still over size limit
            if self.total_size > self.max_size_bytes:
                oldest_files = await self._get_oldest_files(limit=self.batch_size)
                for path_str, size, mtime, creation_time in oldest_files:
                    if self.total_size <= self.max_size_bytes:
                        break

                    # Double-check protection period before deletion
                    file_age = current_time - creation_time
                    if file_age < self.file_protection_seconds:
                        logger.error(f"ATTEMPTED TO DELETE PROTECTED FILE (age: {file_age:.2f}s): {Path(path_str).name} - SKIPPING")
                        continue

                    status = await delete_candidate(path_str)
                    if status == "deleted":
                        logger.debug(f"DELETED: {Path(path_str).name} (age: {file_age:.2f}s, size: {size / 1024:.2f}KB)")

            await self._cleanup_empty_dirs()

            if deleted_count > 0:
                logger.info(f"Cleanup completed: deleted {deleted_count} files, "
                            f"freed {freed_space / 1024 / 1024:.2f}MB, "
                            f"remaining: {len(self.file_cache)} files, "
                            f"{self.total_size / 1024 / 1024:.2f}MB")

            if failed_deletions:
                failure_items = list(failed_deletions.items())
                details = "; ".join(
                    f"{path}: {error}" for path, error in failure_items[:3]
                )
                omitted = len(failure_items) - 3
                if omitted > 0:
                    details += f"; and {omitted} more"
                logger.warning(
                    f"Cleanup completed with {len(failed_deletions)} deletion failure(s); "
                    f"will retry on the next cleanup cycle. {details}"
                )

    async def _process_changes(self, changes):
        """Process file change events"""

        for change_type, file_path in changes:
            await self._update_cache(change_type, file_path)

        # Check if cleanup is needed; cleanup() handles its own rate limiting
        # and _refresh_config() inside the lock to avoid race conditions
        if self.total_size > self.max_size_bytes or len(self.file_cache) > self.max_files:
            logger.debug(f"Cleanup needed - Files: {len(self.file_cache)}/{self.max_files}, "
                        f"Size: {self.total_size / 1024 / 1024:.2f}MB/{self.max_size_bytes / 1024 / 1024:.2f}MB")
            await self.cleanup()

    async def _periodic_cleanup_loop(self):
        """Periodically check for expired files even without file changes."""
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
        """Start asynchronous monitoring"""
        logger.info("="*60)
        logger.info(f"Starting monitoring folder: {self.folder_path}")
        logger.info(f"Max size: {self.max_size_bytes / 1024 / 1024:.2f}MB")
        logger.info(f"Max files: {self.max_files}")
        logger.info(f"Max age: {self.max_age_seconds / 3600:.1f} hours")
        logger.info(f"File protection period: {self.file_protection_seconds} seconds")
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info("="*60)

        # Build cache
        await self._build_cache()

        # Cleanup once on startup (reset check interval so it runs)
        self.last_check_time = 0
        await self.cleanup()

        periodic_task = asyncio.create_task(
            self._periodic_cleanup_loop(),
            name="temp_periodic_cleanup"
        )

        try:
            # Use awatch for asynchronous monitoring
            async for changes in awatch(str(self.folder_path)):
                if changes and not self._stop_event.is_set():
                    await self._process_changes(changes)

        except asyncio.CancelledError:
            logger.info("Monitoring cancelled")
        finally:
            periodic_task.cancel()
            try:
                await periodic_task
            except asyncio.CancelledError:
                pass
            logger.info("Monitoring stopped")

    async def stop_monitoring(self):
        """Stop monitoring"""
        self._stop_event.set()
