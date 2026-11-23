"""Inspect and clean regular files without following filesystem links."""

import os
import stat
from pathlib import Path

from core.logging_manager import get_logger

logger = get_logger("storage", "blue")


def inspect_files(
    root: Path,
    cutoff: float,
    *,
    delete: bool = False,
    protected: set[Path] | None = None,
) -> dict[str, int]:
    result = {
        "size_bytes": 0,
        "item_count": 0,
        "cleanable_bytes": 0,
        "cleanable_count": 0,
        "deleted_bytes": 0,
        "deleted_count": 0,
        "failed_count": 0,
    }
    protected = protected or set()

    def safe_directory(path: Path) -> bool:
        metadata = path.lstat()
        return stat.S_ISDIR(metadata.st_mode) and not (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    def report_error(error: OSError) -> None:
        result["failed_count"] += 1
        logger.warning("Storage operation failed: %s", error)

    try:
        if not safe_directory(root):
            return result
        for directory, dirs, files in os.walk(root, onerror=report_error):
            parent = Path(directory)
            safe_dirs = []
            for name in dirs:
                try:
                    if safe_directory(parent / name):
                        safe_dirs.append(name)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    report_error(exc)
            dirs[:] = safe_dirs
            for name in files:
                path = parent / name
                try:
                    metadata = path.lstat()
                    if not stat.S_ISREG(metadata.st_mode) or (
                        getattr(metadata, "st_file_attributes", 0)
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        continue
                    result["size_bytes"] += metadata.st_size
                    result["item_count"] += 1
                    if (
                        max(metadata.st_mtime, metadata.st_ctime) >= cutoff
                        or path.resolve() in protected
                    ):
                        continue
                    result["cleanable_bytes"] += metadata.st_size
                    result["cleanable_count"] += 1
                    if delete:
                        # Recheck every parent before deleting; never traverse a junction or symlink.
                        parents = [path.parent, *path.parent.parents]
                        parents = parents[: parents.index(root) + 1]
                        if not all(safe_directory(item) for item in parents):
                            continue
                        current = path.lstat()
                        if (
                            current.st_dev,
                            current.st_ino,
                            current.st_mtime,
                            current.st_ctime,
                        ) != (
                            metadata.st_dev,
                            metadata.st_ino,
                            metadata.st_mtime,
                            metadata.st_ctime,
                        ):
                            continue
                        path.unlink()
                        result["deleted_bytes"] += metadata.st_size
                        result["deleted_count"] += 1
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    report_error(exc)
    except FileNotFoundError:
        pass
    except OSError as exc:
        report_error(exc)
    return result
