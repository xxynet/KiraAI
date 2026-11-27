"""Independent, durable storage for the administrator's built-in conversation."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import sqlite3
import time
import uuid
from collections import OrderedDict
from pathlib import Path

import aiosqlite

from core.chat.message_history import serialize_message_chain
from core.logging_manager import get_logger

logger = get_logger("webchat", "cyan")

# Only deleted IDs need separate replay protection. Tombstones expire after
# 128 subsequent deletions or a restart; live requests use persisted messages.
MAX_DELETED_REQUESTS = 128


class WebChatStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "webchat.db"
        self.media_dir = root / "media"
        self.lock = asyncio.Lock()
        self._pending_media_cleanup: set[Path] = set()
        self._deleted_requests: OrderedDict[str, None] = OrderedDict()

    async def initialize(self):
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'requests'"
            ) as cursor:
                legacy_requests = await cursor.fetchone() is not None
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
            """)
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("PRAGMA table_info(messages)") as cursor:
                columns = {row[1] for row in await cursor.fetchall()}
            if "request_status" not in columns:
                await db.execute("ALTER TABLE messages ADD COLUMN request_status TEXT")
                async with db.execute("SELECT id, body FROM messages") as cursor:
                    async for message_id, body in cursor:
                        if json.loads(body).get("direction") == "incoming":
                            await db.execute(
                                "UPDATE messages SET request_status = 'sent' WHERE id = ?", (message_id,)
                            )
            if legacy_requests:
                await db.execute(
                    "UPDATE messages SET request_status = "
                    "(SELECT status FROM requests WHERE requests.id = messages.id) "
                    "WHERE request_status IS NOT NULL AND id IN (SELECT id FROM requests)"
                )
                await db.execute("DROP TABLE requests")
            await db.execute(
                "CREATE INDEX IF NOT EXISTS messages_request_seq ON messages (seq) "
                "WHERE request_status IS NOT NULL"
            )
            await db.commit()
            if legacy_requests:
                try:
                    # Rewrite the file so dropped request text no longer lingers in free pages.
                    await db.execute("VACUUM")
                except sqlite3.Error:
                    logger.warning("Skipped WebChat database compaction after dropping requests table", exc_info=True)

    async def get_setting(self, key: str):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cursor:
                row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def set_setting(self, key: str, value):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("INSERT OR REPLACE INTO settings VALUES (?, ?)",
                             (key, json.dumps(value, ensure_ascii=False)))
            await db.commit()

    def _remember_tombstone(self, request_id: str):
        self._deleted_requests[request_id] = None
        self._deleted_requests.move_to_end(request_id)
        while len(self._deleted_requests) > MAX_DELETED_REQUESTS:
            self._deleted_requests.popitem(last=False)

    async def latest_request(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT id, request_status FROM messages WHERE request_status IS NOT NULL "
                "ORDER BY seq DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
        return {"id": row[0], "status": row[1]} if row else None

    @staticmethod
    def _existing_request(request_id: str, row, chain: list[dict]):
        if row is None:
            return None
        if row[1] is None or json.loads(row[0])["chain"] != chain:
            raise ValueError("request_conflict")
        return {"id": request_id, "status": row[1]}

    async def get_request(self, request_id: str, text: str, chain: list[dict] | None = None):
        chain = chain if chain is not None else [{"type": "text", "text": text}]
        async with self.lock, aiosqlite.connect(self.path) as db:
            if request_id in self._deleted_requests:
                raise ValueError("request_conflict")
            async with db.execute(
                "SELECT body, request_status FROM messages WHERE id = ?", (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
            return self._existing_request(request_id, row, chain)

    async def accept(self, request_id: str, text: str, nickname: str, chain: list[dict] | None = None):
        """Persist each message once without waiting for a reply to previous input."""
        chain = chain if chain is not None else [{"type": "text", "text": text}]
        async with self.lock, aiosqlite.connect(self.path) as db:
            if request_id in self._deleted_requests:
                raise ValueError("request_conflict")
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT body, request_status FROM messages WHERE id = ?", (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
            existing = self._existing_request(request_id, row, chain)
            if existing is not None:
                return existing, False
            record = self.message(request_id, "incoming", nickname, chain)
            await db.execute("INSERT INTO messages (id, body, request_status) VALUES (?, ?, 'sent')",
                             (request_id, json.dumps(record, ensure_ascii=False)))
            await db.commit()
        return {"id": request_id, "status": "sent"}, True

    async def finish(self, request_id: str, status: str):
        async with self.lock, aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE messages SET request_status = ? WHERE id = ? AND request_status IS NOT NULL",
                (status, request_id),
            )
            await db.commit()

    @staticmethod
    def message(message_id: str, direction: str, nickname: str, chain: list):
        return {"id": message_id, "direction": direction, "sender_name": nickname,
                "timestamp": int(time.time()), "chain": chain}

    async def append_reply(self, chain, nickname: str) -> str:
        async with self.lock:
            elements = await serialize_message_chain(chain, archive_root=self.media_dir)

            def snapshot(quoted_chain: list[dict], depth: int = 1) -> list[dict]:
                result = []
                for element in quoted_chain:
                    item = {key: value for key, value in element.items() if key != "chain"}
                    if element.get("chain") and depth < 3:
                        item["chain"] = snapshot(element["chain"], depth + 1)
                    result.append(item)
                return result

            for element in elements:
                if element.get("type") == "reply" and not element.get("chain") and not element.get("message_content"):
                    original = await self.get_message(element["message_id"])
                    if original is not None:
                        element["chain"] = snapshot(original["chain"])
            message_id = uuid.uuid4().hex
            record = self.message(message_id, "outgoing", nickname, elements)
            async with aiosqlite.connect(self.path) as db:
                await db.execute("INSERT INTO messages (id, body) VALUES (?, ?)",
                                 (message_id, json.dumps(record, ensure_ascii=False)))
                await db.commit()
            return message_id

    async def delete_message(self, message_id: str):
        staged: list[tuple[Path, Path]] = []
        staging_dir: Path | None = None

        def restore_media():
            failures = []
            for original, backup in reversed(staged):
                try:
                    backup.rename(original)
                except OSError as exc:
                    logger.exception(f"Failed to restore WebChat attachment {backup} to {original}")
                    failures.append(exc)
            if failures:
                raise failures[0]
            if staging_dir is not None:
                staging_dir.rmdir()

        def cleanup_media():
            media = self.media_dir.resolve()
            for directory in tuple(self._pending_media_cleanup):
                try:
                    if (media != self.root.resolve() / "media" or self.media_dir.is_symlink()
                            or directory.is_symlink() or directory.resolve().parent != media):
                        raise ValueError("Invalid WebChat media cleanup directory")
                    if directory.exists():
                        shutil.rmtree(directory)
                    self._pending_media_cleanup.discard(directory)
                except (OSError, ValueError):
                    logger.exception(f"Failed to clean up deleted WebChat attachments in {directory}")

        def stage_unused_media(body: str, remaining: list):
            nonlocal staging_dir
            def media_refs(chain: list[dict]) -> set[str]:
                refs = set()
                for element in chain:
                    file = element.get("file")
                    if (element.get("file_type") == "archive" and isinstance(file, str)
                            and re.fullmatch(r"[0-9a-f]{64}", file)):
                        refs.add(file)
                    if isinstance(element.get("chain"), list):
                        refs.update(media_refs(element["chain"]))
                return refs

            unused = media_refs(json.loads(body)["chain"])
            for (other_body,) in remaining:
                unused.difference_update(media_refs(json.loads(other_body)["chain"]))
                if not unused:
                    return
            if not unused:
                return
            root = self.root.resolve()
            media = self.media_dir.resolve()
            if media != root / "media" or self.media_dir.is_symlink():
                raise ValueError("Invalid WebChat media directory")
            targets = [(media / file).resolve() for file in sorted(unused)]
            if any(target.parent != media for target in targets):
                raise ValueError("Invalid WebChat media path")
            for target in targets:
                if not target.exists():
                    continue
                if staging_dir is None:
                    staging_dir = media / f".delete-{uuid.uuid4().hex}"
                    staging_dir.mkdir()
                backup = staging_dir / target.name
                target.rename(backup)
                staged.append((target, backup))

        async def delete():
            await asyncio.to_thread(cleanup_media)
            async with aiosqlite.connect(self.path) as db:
                try:
                    await db.execute("BEGIN IMMEDIATE")
                    async with db.execute("SELECT body FROM messages WHERE id = ?", (message_id,)) as cursor:
                        row = await cursor.fetchone()
                    if row is None:
                        return
                    async with db.execute("SELECT body FROM messages WHERE id != ?", (message_id,)) as cursor:
                        remaining = await cursor.fetchall()
                    await asyncio.to_thread(stage_unused_media, row[0], remaining)
                    await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
                    await db.commit()
                    if json.loads(row[0]).get("direction") == "incoming":
                        self._remember_tombstone(message_id)
                except BaseException:
                    try:
                        await db.rollback()
                    finally:
                        await asyncio.to_thread(restore_media)
                    raise
                if staging_dir is not None:
                    self._pending_media_cleanup.add(staging_dir)
                await asyncio.to_thread(cleanup_media)

        async with self.lock:
            # Finish the transaction before releasing the lock, even if the caller disconnects.
            task = asyncio.create_task(delete())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def clear_messages(self):
        def remove_media():
            root = self.root.resolve()
            media = self.media_dir.resolve()
            if media != root / "media" or self.media_dir.is_symlink():
                raise ValueError("Invalid WebChat media directory")
            if media.exists():
                shutil.rmtree(media)

        async with self.lock, aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            await db.execute("DELETE FROM messages")
            await asyncio.to_thread(remove_media)
            await db.commit()
            self._deleted_requests.clear()

    async def list_messages(self, *, before: int | None = None, after: int = 0, limit: int = 50):
        async with aiosqlite.connect(self.path) as db:
            if before is not None:
                query, args = "SELECT seq, body FROM messages WHERE seq < ? ORDER BY seq DESC LIMIT ?", (before, limit + 1)
            elif after:
                query, args = "SELECT seq, body FROM messages WHERE seq > ? ORDER BY seq ASC LIMIT ?", (after, limit + 1)
            else:
                query, args = "SELECT seq, body FROM messages ORDER BY seq DESC LIMIT ?", (limit + 1,)
            async with db.execute(query, args) as cursor:
                rows = await cursor.fetchall()
        more = len(rows) > limit
        rows = rows[:limit]
        if not after or before is not None:
            rows.reverse()
        messages = [{**json.loads(body), "seq": seq} for seq, body in rows]
        return {"messages": messages, "has_more": more}

    async def get_message(self, message_id: str):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT body FROM messages WHERE id = ?", (message_id,)) as cursor:
                row = await cursor.fetchone()
        return json.loads(row[0]) if row else None
