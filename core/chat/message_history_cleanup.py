"""Retention of structured messages and reclamation of unreferenced archive media."""

from __future__ import annotations

import asyncio
import re
import time

from sqlalchemy import and_, delete, or_, select

from core.config.default import DEFAULT_CONFIG
from core.db.models import MessageRecord
from core.logging_manager import get_logger
from core.utils.media_refs import MEDIA_ROOT_NAME, collect_media_reference_paths
from core.utils.path_utils import get_data_path, is_within_directory

logger = get_logger("message_history_cleanup", "cyan")


def validate_cleanup_config(value: dict) -> dict:
    """Validate retention settings before saving or performing destructive work."""
    if not isinstance(value, dict):
        raise ValueError("message_history_cleanup must be an object")
    config = {**DEFAULT_CONFIG["bot_config"]["message_history_cleanup"], **value}
    if type(config["enabled"]) is not bool:
        raise ValueError("message_history_cleanup.enabled must be a boolean")
    for key, minimum, maximum in (
        ("max_age_days", 0, 36500),
        ("max_messages_per_session", 0, 1000000),
        ("cleanup_interval_seconds", 60, 604800),
    ):
        number = config[key]
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError(f"message_history_cleanup.{key} must be an integer from {minimum} to {maximum}")
    if config["enabled"] and not (config["max_age_days"] or config["max_messages_per_session"]):
        raise ValueError("Enabled message history cleanup requires at least one retention limit")
    return config


class MessageHistoryCleanup:
    def __init__(self, history, config):
        self.history = history
        self.config = config
        self._changed = asyncio.Event()
        self._stopping = False
        self._task = None
        self._run_lock = asyncio.Lock()

    def start(self):
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.create_task(self.run(), name="message_history_cleanup")

    def notify_config_changed(self):
        self._changed.set()

    async def stop(self):
        self._stopping = True
        self._changed.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def run(self):
        while not self._stopping:
            self._changed.clear()
            interval = 60
            try:
                settings = validate_cleanup_config(
                    self.config.get("bot_config", {}).get("message_history_cleanup", {})
                )
                interval = settings["cleanup_interval_seconds"]
                if settings["enabled"]:
                    result = await self.cleanup_once(settings)
                    if result["deferred"] or result["deleted_messages"] >= 5000 or result["deleted_files"] >= 1000:
                        interval = min(interval, 60)
                    if result["deleted_messages"] or result["deleted_files"]:
                        logger.info("History cleanup: messages=%d files=%d bytes=%d",
                                    result["deleted_messages"], result["deleted_files"], result["freed_bytes"])
            except Exception as exc:
                logger.warning("History cleanup failed (%s)", type(exc).__name__)
                interval = 60
            if self._stopping:
                break
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def cleanup_once(self, settings: dict) -> dict:
        # Keep the maintenance gate until any filesystem worker has finished.
        task = asyncio.create_task(self._cleanup_once(settings))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            finally:
                raise

    async def _cleanup_once(self, settings: dict) -> dict:
        settings = validate_cleanup_config(settings)
        result = {"deleted_messages": 0, "deleted_files": 0, "freed_bytes": 0, "deferred": False}
        if not settings["enabled"]:
            return result
        async with self._run_lock:
            async with self.history.maintenance() as protected:
                if protected is None:
                    result["deferred"] = True
                    return result
                result["deleted_messages"] = await self._prune(settings, protected)
                retained = set()
                async with self.history.db.get_session() as session:
                    chains = await session.stream_scalars(
                        select(MessageRecord.chain).execution_options(yield_per=500)
                    )
                    async for chain in chains:
                        # Collect references from all nested message components.
                        pending = [chain]
                        while pending:
                            item = pending.pop()
                            if isinstance(item, list):
                                pending.extend(item)
                            elif isinstance(item, dict):
                                if item.get("file_type") == "archive" and isinstance(item.get("file"), str):
                                    retained.add(item["file"])
                                pending.extend(value for value in item.values() if isinstance(value, (dict, list)))
                removed, freed = await asyncio.to_thread(self._cleanup_media, retained)
                result.update(deleted_files=removed, freed_bytes=freed)
                return result

    async def _prune(self, settings: dict, protected: set[str]) -> int:
        cutoff = time.time_ns() // 1_000_000 - settings["max_age_days"] * 86400000
        total = 0
        async with self.history.db.get_session() as session:
            sessions = (await session.scalars(select(MessageRecord.session_id).distinct())).all()
        for session_id in sessions:
            conditions = []
            if settings["max_age_days"]:
                conditions.append(MessageRecord.created_at < cutoff)
            if settings["max_messages_per_session"]:
                async with self.history.db.get_session() as session:
                    boundary = (await session.execute(select(MessageRecord.created_at, MessageRecord.id).where(
                        MessageRecord.session_id == session_id
                    ).order_by(MessageRecord.created_at.desc(), MessageRecord.id.desc()).offset(
                        settings["max_messages_per_session"]
                    ).limit(1))).first()
                if boundary:
                    conditions.append(or_(
                        MessageRecord.created_at < boundary.created_at,
                        and_(MessageRecord.created_at == boundary.created_at, MessageRecord.id <= boundary.id),
                    ))
            if not conditions:
                continue
            cursor = None
            while total < 5000:
                query = select(MessageRecord.id, MessageRecord.created_at).where(
                    MessageRecord.session_id == session_id,
                    MessageRecord.status != "pending",
                    or_(*conditions),
                )
                if cursor:
                    query = query.where(or_(
                        MessageRecord.created_at > cursor.created_at,
                        and_(MessageRecord.created_at == cursor.created_at, MessageRecord.id > cursor.id),
                    ))
                async with self.history.db.transaction() as session:
                    rows = (await session.execute(query.order_by(
                        MessageRecord.created_at, MessageRecord.id
                    ).limit(min(500, 5000 - total)))).all()
                    if not rows:
                        break
                    ids = [row.id for row in rows if row.id not in protected]
                    if ids:
                        await session.execute(delete(MessageRecord).where(MessageRecord.id.in_(ids)))
                        total += len(ids)
                    cursor = rows[-1]
            if total >= 5000:
                break
        return total

    def _cleanup_media(self, retained: set[str]) -> tuple[int, int]:
        data_root = get_data_path().resolve()
        root = data_root / MEDIA_ROOT_NAME / "archive"
        if root.is_symlink() or not root.is_dir() or not is_within_directory(data_root, root.resolve()):
            return 0, 0
        removed = freed = 0
        stale_temporary = time.time() - 86400
        manager = self.history.session_manager
        # Context editing cannot introduce a reference halfway through deletion.
        # No async lock or await is involved in this worker-thread critical section.
        with manager.memory_lock:
            for session_data in manager.chat_memory.values():
                retained.update(collect_media_reference_paths(session_data.get("memory", [])))
            retained_paths = {(data_root / path).resolve() for path in retained}
            for path in root.iterdir():
                if path.is_symlink() or not path.is_file():
                    continue
                resolved = path.resolve()
                if not is_within_directory(root.resolve(), resolved) or resolved in retained_paths:
                    continue
                is_archive = re.fullmatch(r"[0-9a-f]{64}", path.name) is not None
                is_temporary = re.fullmatch(r"[0-9a-f]{32}\.(tmp|download)", path.name) is not None
                if not (is_archive or is_temporary):
                    continue
                try:
                    stat = path.stat()
                    if is_temporary and stat.st_mtime >= stale_temporary:
                        continue
                    path.unlink()
                    removed += 1
                    freed += stat.st_size
                except OSError as exc:
                    logger.warning("Unable to remove archived media (%s)", type(exc).__name__)
                if removed >= 1000:
                    break
        return removed, freed
