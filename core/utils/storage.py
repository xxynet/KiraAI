"""Inspect and clean regular files without following filesystem links."""

import os
import stat
from collections.abc import Callable
from pathlib import Path

from core.logging_manager import get_logger

logger = get_logger("storage", "blue")


def inspect_files(
    root: Path,
    cutoff: float,
    *,
    delete: bool = False,
    include: Callable[[Path], bool] | None = None,
    recursive: bool = True,
    use_mtime: bool = False,
    boundary: Path | None = None,
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

    def safe_directory(path: Path) -> bool:
        metadata = path.lstat()
        return stat.S_ISDIR(metadata.st_mode) and not (
            stat.S_ISLNK(metadata.st_mode)
            or getattr(metadata, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        )

    boundary = root if boundary is None else boundary

    def safe_directory_tree(path: Path) -> bool:
        if not path.is_relative_to(boundary):
            return False
        parents = [path, *path.parents]
        return all(
            safe_directory(item) for item in parents[: parents.index(boundary) + 1]
        )

    def report_error(error: OSError) -> None:
        result["failed_count"] += 1
        logger.warning("Storage operation failed: %s", error)

    try:
        if not safe_directory_tree(root):
            return result
        for directory, dirs, files in os.walk(root, onerror=report_error):
            parent = Path(directory)
            safe_dirs = []
            for name in dirs if recursive else []:
                try:
                    if safe_directory(parent / name):
                        safe_dirs.append(name)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    report_error(exc)
            dirs[:] = safe_dirs if recursive else []
            for name in files:
                path = parent / name
                try:
                    if include is not None and not include(path):
                        continue
                    metadata = path.lstat()
                    if not stat.S_ISREG(metadata.st_mode) or (
                        getattr(metadata, "st_file_attributes", 0)
                        & stat.FILE_ATTRIBUTE_REPARSE_POINT
                    ):
                        continue
                    result["size_bytes"] += metadata.st_size
                    result["item_count"] += 1
                    age_timestamp = (
                        metadata.st_mtime
                        if use_mtime
                        else max(metadata.st_mtime, metadata.st_ctime)
                    )
                    if age_timestamp >= cutoff:
                        continue
                    result["cleanable_bytes"] += metadata.st_size
                    result["cleanable_count"] += 1
                    if delete:
                        # Recheck every parent before deleting; never traverse a junction or symlink.
                        if not safe_directory_tree(path.parent):
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
