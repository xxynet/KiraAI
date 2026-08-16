"""Crash-safe file replacement for in-place application updates."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any


JOURNAL_NAME = ".kira-update-journal.json"
BACKUP_PREFIX = ".kira-update-backup-"
STAGE_PREFIX = ".kira-update-stage-"


def _is_direct_child(root: Path, path: Path, prefix: str | None = None) -> bool:
    try:
        is_child = path.resolve().parent == root.resolve()
    except OSError:
        return False
    return is_child and (prefix is None or path.name.startswith(prefix))


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _write_journal(root: Path, data: dict[str, Any]) -> None:
    journal = root / JOURNAL_NAME
    fd, tmp_name = tempfile.mkstemp(prefix=f"{JOURNAL_NAME}.", suffix=".tmp", dir=root)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, journal)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


class UpdateTransaction:
    """Replace direct children of an application root with crash recovery."""

    def __init__(self, root: Path, stage_dir: Path, names: list[str]) -> None:
        self.root = root.resolve()
        self.stage_dir = stage_dir.resolve()
        if not _is_direct_child(self.root, self.stage_dir, STAGE_PREFIX):
            raise ValueError("Update staging directory must be a direct child of the application root")
        if any(not name or Path(name).name != name for name in names):
            raise ValueError("Update items must be direct children of the application root")

        self.backup_dir = Path(tempfile.mkdtemp(prefix=BACKUP_PREFIX, dir=self.root)).resolve()
        self.data: dict[str, Any] = {
            "phase": "applying",
            "backup_dir": self.backup_dir.name,
            "actions": [
                {"name": name, "had_original": (self.root / name).exists(), "state": "pending"}
                for name in names
            ],
        }
        _write_journal(self.root, self.data)

    def _save(self) -> None:
        _write_journal(self.root, self.data)

    def apply(self) -> None:
        """Move staged files into place while retaining rollback backups."""
        try:
            for action in self.data["actions"]:
                name = action["name"]
                src = self.stage_dir / name
                dst = self.root / name
                backup = self.backup_dir / name
                if not src.exists():
                    raise ValueError(f"Staged update item is missing: {name}")
                if action["had_original"]:
                    action["state"] = "moving_original"
                    self._save()
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    dst.rename(backup)
                    action["state"] = "original_moved"
                    self._save()
                action["state"] = "installing"
                self._save()
                src.rename(dst)
                action["state"] = "applied"
                self._save()
            self.data["phase"] = "applied"
            self._save()
        except Exception:
            self.rollback()
            raise

    def commit(self) -> None:
        """Finalize the transaction after all post-update checks succeed."""
        self.data["phase"] = "committed"
        self._save()
        _remove_path(self.backup_dir)
        (self.root / JOURNAL_NAME).unlink(missing_ok=True)

    def rollback(self) -> None:
        """Restore the pre-update tree without overwriting unknown user files."""
        _rollback_from_data(self.root, self.data)


def _rollback_from_data(root: Path, data: dict[str, Any]) -> list[str]:
    backup_dir = root / str(data.get("backup_dir") or "")
    if not _is_direct_child(root, backup_dir, BACKUP_PREFIX):
        return ["Update recovery skipped because its backup path is unsafe."]

    errors: list[str] = []
    for action in reversed(data.get("actions") or []):
        name = action.get("name")
        if not isinstance(name, str) or not name or Path(name).name != name:
            errors.append("Update recovery skipped an invalid item name.")
            continue
        dst = root / name
        backup = backup_dir / name
        had_original = bool(action.get("had_original"))
        try:
            # A backup is proof that the original was moved. The destination,
            # if present, is therefore the partially applied update and must be
            # removed before the original can be restored.
            if had_original and backup.exists():
                if dst.exists():
                    _remove_path(dst)
                backup.rename(dst)
            elif action.get("state") in {"installing", "applied"} and dst.exists():
                _remove_path(dst)
        except OSError as exc:
            errors.append(f"Update recovery could not restore '{name}': {exc}")

    if errors:
        return errors
    _remove_path(backup_dir)
    (root / JOURNAL_NAME).unlink(missing_ok=True)
    return []


def recover_interrupted_update(root: Path) -> list[str]:
    """Recover or finalize the one update transaction recorded under ``root``."""
    root = root.resolve()
    journal = root / JOURNAL_NAME
    if not journal.exists():
        return []
    try:
        data = json.loads(journal.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("journal is not an object")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Update recovery skipped an unreadable journal: {exc}"]

    backup_dir = root / str(data.get("backup_dir") or "")
    if data.get("phase") == "committed":
        if not _is_direct_child(root, backup_dir, BACKUP_PREFIX):
            return ["Update cleanup skipped because its backup path is unsafe."]
        try:
            _remove_path(backup_dir)
            journal.unlink(missing_ok=True)
            return []
        except OSError as exc:
            return [f"Update cleanup failed: {exc}"]
    return _rollback_from_data(root, data)
