import asyncio
import heapq
import time
from pathlib import Path
from watchfiles import awatch
from typing import Dict, List, Tuple, Optional

from core.logging_manager import get_logger

logger = get_logger("atm", "yellow")


class AsyncTempMonitor:
    def __init__(self, folder_path: str, max_size_mb: int = 50,
                 check_interval: int = 60, batch_size: int = 20, file_protection_seconds: int = 60):
        """
        Asynchronous temporary folder monitor

        Args:
            folder_path: Path of the folder to monitor
            max_size_mb: Maximum allowed size in MB
            check_interval: Minimum check interval in seconds
            batch_size: Maximum number of files to clean up at once
            file_protection_seconds: File protection period in seconds, new files won't be deleted within this period
        """
        self.folder_path = Path(folder_path)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.check_interval = check_interval
        self.batch_size = batch_size
        self.file_protection_seconds = file_protection_seconds
        self.folder_path.mkdir(parents=True, exist_ok=True)

        # Cache file information: path -> (size, mtime, creation_time)
        # creation_time is when the file was first seen by the monitor
        self.file_cache: Dict[str, Tuple[int, float, float]] = {}
        self.total_size = 0
        self.last_check_time = 0
        self._cleanup_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

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
                    if Path(file_path).exists():
                        stat = Path(file_path).stat()
                        return stat.st_size, stat.st_mtime
                    return None, None

                result = await loop.run_in_executor(None, add_file)
                if result[0] is not None:
                    size, mtime = result
                    # Use current_time as creation_time for new files
                    self.file_cache[path_str] = (size, mtime, current_time)
                    self.total_size += size
                    logger.info(f"File added to cache: {Path(path_str).name}, size: {size}, mtime: {mtime}, creation_time: {current_time}")

        elif change_type == 2:  # Modified
            if path_str in self.file_cache:
                old_size, old_mtime, creation_time = self.file_cache[path_str]

                def modify_file():
                    if Path(file_path).exists():
                        stat = Path(file_path).stat()
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

    async def _delete_file(self, path_str: str) -> Optional[int]:
        """Delete a single file asynchronously"""
        loop = asyncio.get_event_loop()

        def delete():
            try:
                file_path = Path(path_str)
                if file_path.exists():
                    size = file_path.stat().st_size
                    file_path.unlink()
                    return size
            except Exception as e:
                logger.error(f"Failed to delete {path_str}: {e}")
            return None

        return await loop.run_in_executor(None, delete)

    async def cleanup(self):
        """Execute cleanup asynchronously"""
        current_time = time.time()

        # Control check frequency
        if current_time - self.last_check_time < self.check_interval:
            return

        # Use lock to prevent concurrent cleanup
        async with self._cleanup_lock:
            self.last_check_time = current_time

            if self.total_size <= self.max_size_bytes:
                return

            logger.info(f"CLEANUP TRIGGERED - Current size: {self.total_size / 1024 / 1024:.2f}MB, Max: {self.max_size_bytes / 1024 / 1024:.2f}MB")

            # Get oldest files
            oldest_files = await self._get_oldest_files(limit=self.batch_size)
            deleted_count = 0
            freed_space = 0

            # Batch delete
            for path_str, size, mtime, creation_time in oldest_files:
                if self.total_size <= self.max_size_bytes:
                    break

                # Double-check protection period before deletion
                file_age = current_time - creation_time
                if file_age < self.file_protection_seconds:
                    logger.error(f"ATTEMPTED TO DELETE PROTECTED FILE (age: {file_age:.2f}s): {Path(path_str).name} - SKIPPING")
                    continue

                deleted_size = await self._delete_file(path_str)
                if deleted_size:
                    self.total_size -= deleted_size
                    if path_str in self.file_cache:
                        del self.file_cache[path_str]
                    deleted_count += 1
                    freed_space += deleted_size
                    logger.info(f"DELETED: {Path(path_str).name} (age: {file_age:.2f}s, size: {deleted_size / 1024:.2f}KB)")

            if deleted_count > 0:
                logger.info(f"Cleanup completed: deleted {deleted_count} files, "
                            f"freed {freed_space / 1024 / 1024:.2f}MB, "
                            f"current size: {self.total_size / 1024 / 1024:.2f}MB")

    async def _process_changes(self, changes):
        """Process file change events"""

        for change_type, file_path in changes:
            await self._update_cache(change_type, file_path)

        # Check if cleanup is needed (but respect check_interval)
        if self.total_size > self.max_size_bytes:
            logger.info(f"Total size ({self.total_size / 1024 / 1024:.2f}MB) exceeds max ({self.max_size_bytes / 1024 / 1024:.2f}MB)")
            await self.cleanup()

    async def start_monitoring(self):
        """Start asynchronous monitoring"""
        logger.info("="*60)
        logger.info(f"Starting monitoring folder: {self.folder_path}")
        logger.info(f"Max size: {self.max_size_bytes / 1024 / 1024:.2f}MB")
        logger.info(f"File protection period: {self.file_protection_seconds} seconds")
        logger.info(f"Check interval: {self.check_interval} seconds")
        logger.info("="*60)

        # Build cache
        await self._build_cache()

        # Cleanup once on startup
        await self.cleanup()

        try:
            # Use awatch for asynchronous monitoring
            async for changes in awatch(str(self.folder_path)):
                if changes and not self._stop_event.is_set():
                    await self._process_changes(changes)

        except asyncio.CancelledError:
            logger.info("Monitoring cancelled")
        finally:
            logger.info("Monitoring stopped")

    async def stop_monitoring(self):
        """Stop monitoring"""
        self._stop_event.set()
