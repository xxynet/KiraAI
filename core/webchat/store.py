"""Independent, durable storage for the administrator's built-in conversation."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
import uuid
from pathlib import Path

import aiosqlite

from core.chat.message_history import serialize_message_chain


class WebChatStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "webchat.db"
        self.media_dir = root / "media"
        self.lock = asyncio.Lock()

    async def initialize(self):
        await asyncio.to_thread(self.root.mkdir, parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS messages (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS requests (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                    text TEXT NOT NULL, status TEXT NOT NULL);
            """)
            await db.commit()

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

    async def latest_request(self):
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT id, status FROM requests ORDER BY seq DESC LIMIT 1") as cursor:
                row = await cursor.fetchone()
        return {"id": row[0], "status": row[1]} if row else None

    async def get_request(self, request_id: str, text: str, chain: list[dict] | None = None):
        chain = chain if chain is not None else [{"type": "text", "text": text}]
        async with aiosqlite.connect(self.path) as db:
            async with db.execute(
                "SELECT requests.text, requests.status, messages.body FROM requests "
                "LEFT JOIN messages ON messages.id = requests.id WHERE requests.id = ?", (request_id,)
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:
            return None
        if row[2] is None or row[0] != text or json.loads(row[2])["chain"] != chain:
            raise ValueError("request_conflict")
        return {"id": request_id, "status": row[1]}

    async def accept(self, request_id: str, text: str, nickname: str, chain: list[dict] | None = None):
        """Persist each message once without waiting for a reply to previous input."""
        chain = chain if chain is not None else [{"type": "text", "text": text}]
        async with self.lock, aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute(
                "SELECT requests.text, requests.status, messages.body FROM requests "
                "LEFT JOIN messages ON messages.id = requests.id WHERE requests.id = ?", (request_id,)
            ) as cursor:
                existing = await cursor.fetchone()
            if existing:
                if existing[2] is None or existing[0] != text or json.loads(existing[2])["chain"] != chain:
                    raise ValueError("request_conflict")
                return {"id": request_id, "status": existing[1]}, False
            await db.execute("INSERT INTO requests (id, text, status) VALUES (?, ?, 'sent')", (request_id, text))
            record = self.message(request_id, "incoming", nickname, chain)
            await db.execute("INSERT INTO messages (id, body) VALUES (?, ?)",
                             (request_id, json.dumps(record, ensure_ascii=False)))
            await db.commit()
        return {"id": request_id, "status": "sent"}, True

    async def finish(self, request_id: str, status: str):
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE requests SET status = ? WHERE id = ?", (status, request_id))
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
        def remove_unused_media(body: str, remaining: list):
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
            targets = [(media / file).resolve() for file in unused]
            if any(target.parent != media for target in targets):
                raise ValueError("Invalid WebChat media path")
            for target in targets:
                target.unlink(missing_ok=True)

        async with self.lock, aiosqlite.connect(self.path) as db:
            await db.execute("BEGIN IMMEDIATE")
            async with db.execute("SELECT body FROM messages WHERE id = ?", (message_id,)) as cursor:
                row = await cursor.fetchone()
            if row is None:
                return
            async with db.execute("SELECT body FROM messages WHERE id != ?", (message_id,)) as cursor:
                remaining = await cursor.fetchall()
            await asyncio.to_thread(remove_unused_media, row[0], remaining)
            await db.execute("DELETE FROM messages WHERE id = ?", (message_id,))
            await db.commit()

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
            await db.execute("DELETE FROM requests")
            await asyncio.to_thread(remove_media)
            await db.commit()

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
