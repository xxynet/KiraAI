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
        event_bus.subscribe("session_memory_updated", self._on_memory_updated)
        event_bus.subscribe("session_memory_written", self._on_memory_written)
        event_bus.subscribe("session_deleted", self._on_session_deleted)

    async def _on_memory_updated(self, event: SystemEvent) -> None:
        session = event.payload["session"]
        memory = self.session_manager.get_existing_memory_snapshot(session)
        if memory is not None:
            await asyncio.to_thread(cleanup_session_media, session, memory)

    async def _on_memory_written(self, event: SystemEvent) -> None:
        await asyncio.to_thread(
            cleanup_session_media,
            event.payload["session"],
            event.payload["new_memory"],
        )

    async def _on_session_deleted(self, event: SystemEvent) -> None:
        await asyncio.to_thread(cleanup_session_media, event.payload["session"], [])
