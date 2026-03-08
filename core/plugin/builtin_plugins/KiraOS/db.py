"""
SQLite-based user memory storage for KiraAI.

Tables:
  - user_profiles: Long-term key-value user profile entries
  - event_logs:    Recent event logs per user
"""

import sqlite3
import os
from datetime import datetime
from typing import List, Tuple, Optional
from threading import Lock

from core.logging_manager import get_logger

logger = get_logger("kiraos_db", "green")


class UserMemoryDB:
    """Thread-safe SQLite wrapper for user memory persistence."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = Lock()
        self._ensure_dir()
        self._conn: sqlite3.Connection | None = None
        self._init_db()

    def _ensure_dir(self):
        dir_path = os.path.dirname(self.db_path)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

    def _get_conn(self) -> sqlite3.Connection:
        """Return (and lazily create) the shared connection.

        **Caller must hold ``self._lock``** before invoking this method.
        """
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        return self._conn

    def close(self):
        """Close the persistent connection."""
        with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None

    def _init_db(self):
        """Create tables if they don't exist."""
        with self._lock:
            conn = self._get_conn()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS user_profiles (
                    user_id   TEXT NOT NULL,
                    memory_key   TEXT NOT NULL,
                    memory_value TEXT NOT NULL,
                    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user_id, memory_key)
                );

                CREATE TABLE IF NOT EXISTS event_logs (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id       TEXT NOT NULL,
                    event_summary TEXT NOT NULL,
                    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_event_logs_user
                    ON event_logs (user_id, created_at DESC);
            """)
            conn.commit()
            logger.info(f"User memory database initialized at {self.db_path}")

    # ── Profile Operations ──────────────────────────────────────────

    def save_profile(self, user_id: str, key: str, value: str) -> None:
        """Insert or update a user profile entry."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO user_profiles (user_id, memory_key, memory_value, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(user_id, memory_key)
                   DO UPDATE SET memory_value = excluded.memory_value,
                                 updated_at   = excluded.updated_at""",
                (user_id, key, value, datetime.now().isoformat())
            )
            conn.commit()

    def get_profiles(self, user_id: str) -> List[Tuple[str, str, str]]:
        """Return all profile entries for a user as (key, value, updated_at) tuples."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT memory_key, memory_value, updated_at FROM user_profiles WHERE user_id = ? ORDER BY updated_at DESC",
                (user_id,)
            )
            return cursor.fetchall()

    def remove_profile(self, user_id: str, key: str) -> bool:
        """Remove a specific profile entry. Returns True if a row was deleted."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "DELETE FROM user_profiles WHERE user_id = ? AND memory_key = ?",
                (user_id, key)
            )
            conn.commit()
            return cursor.rowcount > 0

    def profile_exists(self, user_id: str, key: str) -> bool:
        """Return True if a profile entry exists for the given user and key."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT 1 FROM user_profiles WHERE user_id = ? AND memory_key = ? LIMIT 1",
                (user_id, key)
            )
            return cursor.fetchone() is not None

    def get_profile_count(self, user_id: str) -> int:
        """Return the number of profile entries for a user."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM user_profiles WHERE user_id = ?",
                (user_id,)
            )
            return cursor.fetchone()[0]

    # ── Event Log Operations ────────────────────────────────────────

    def save_event(self, user_id: str, event_summary: str) -> None:
        """Append an event log entry."""
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO event_logs (user_id, event_summary, created_at) VALUES (?, ?, ?)",
                (user_id, event_summary, datetime.now().isoformat())
            )
            conn.commit()

    def get_recent_events(self, user_id: str, limit: int = 5) -> List[Tuple[str, str]]:
        """Return the most recent events for a user as (event_summary, created_at) tuples."""
        limit = max(limit, 0)
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT event_summary, created_at FROM event_logs WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit)
            )
            return cursor.fetchall()

    def get_event_count(self, user_id: str) -> int:
        """Return the number of event logs for a user."""
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM event_logs WHERE user_id = ?",
                (user_id,)
            )
            return cursor.fetchone()[0]

    def cleanup_old_events(self, user_id: str, keep: int = 50) -> int:
        """Delete oldest events beyond the *keep* threshold. Returns rows deleted."""
        keep = max(keep, 0)
        with self._lock:
            conn = self._get_conn()
            cursor = conn.execute(
                """DELETE FROM event_logs
                   WHERE user_id = ? AND id NOT IN (
                       SELECT id FROM event_logs
                       WHERE user_id = ?
                       ORDER BY created_at DESC
                       LIMIT ?
                   )""",
                (user_id, user_id, keep)
            )
            conn.commit()
            return cursor.rowcount

    # ── Context Assembly ────────────────────────────────────────────

    def build_user_context(self, user_id: str, max_events: int = 5) -> str:
        """
        Assemble a compact memory context for a given user.
        Returns an empty string if no memory exists.
        """
        profiles = self.get_profiles(user_id)
        events = self.get_recent_events(user_id, limit=max_events)

        if not profiles and not events:
            return ""

        parts = []
        if profiles:
            kvs = " | ".join(f"{k}={v}" for k, v, _ in profiles)
            parts.append(f"[{user_id}] {kvs}")

        if events:
            evts = " | ".join(f"{ts[:10]} {s}" for s, ts in events)
            parts.append(f"[{user_id}:events] {evts}")

        return "\n".join(parts)
