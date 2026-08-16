"""Media lifecycle listener for persisted session history."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from core.utils.media_refs import cleanup_session_media

if TYPE_CHECKING:
    from core.event_bus import EventBus, SystemEvent
    from core.chat.session_manager import SessionManager


class SessionMediaManager:
    """Clean session media in response to persisted-memory lifecycle events."""

    def __init__(self, event_bus: EventBus, session_manager: SessionManager):
        self.session_manager = session_manager
        self._session_locks: dict[str, asyncio.Lock] = {}
        event_bus.subscribe("session_memory_updated", self._on_memory_updated)
        event_bus.subscribe("session_memory_written", self._on_memory_written)
        event_bus.subscribe("session_deleted", self._on_session_deleted)

    def _get_session_lock(self, session: str) -> asyncio.Lock:
        lock = self._session_locks.get(session)
        if lock is None:
            lock = asyncio.Lock()
            self._session_locks[session] = lock
        return lock

    async def _cleanup_current_session_media(self, session: str) -> None:
        """Serialize cleanup and use the newest persisted memory for a session."""
        async with self._get_session_lock(session):
            memory = self.session_manager.get_existing_memory_snapshot(session)
            await asyncio.to_thread(cleanup_session_media, session, memory or [])

    async def _on_memory_updated(self, event: SystemEvent) -> None:
        await self._cleanup_current_session_media(event.payload["session"])

    async def _on_memory_written(self, event: SystemEvent) -> None:
        await self._cleanup_current_session_media(event.payload["session"])

    async def _on_session_deleted(self, event: SystemEvent) -> None:
        await self._cleanup_current_session_media(event.payload["session"])
