from __future__ import annotations

import asyncio
from asyncio import Lock
from typing import Callable, Optional

from core.chat.message_utils import KiraMessageEvent


class SessionBuffer:
    def __init__(self, max_count: int = None):
        self.buffer: list = []
        self.lock: asyncio.Lock = asyncio.Lock()
        self.max_count = max_count

    def add(self, message: KiraMessageEvent):
        self.buffer.append(message)

    def pop(self, count: int = 1):
        if self.get_length() < count:
            popped = self.buffer[:]
            self.buffer.clear()
            return popped
        popped = self.buffer[:count]
        del self.buffer[:count]
        return popped

    def flush(
        self,
        count: int = None,
        filter_fn: Optional[Callable[[KiraMessageEvent], bool]] = None,
    ):
        if filter_fn is None:
            if count and count <= len(self.buffer):
                pending_messages = self.buffer[:count]
                del self.buffer[:count]
            else:
                pending_messages = self.buffer[:]
                self.buffer.clear()
            return pending_messages

        matched_indices = [
            index for index, message in enumerate(self.buffer) if filter_fn(message)
        ]
        matched_index_set = set(matched_indices)
        pending_messages = [self.buffer[index] for index in matched_indices]
        self.buffer[:] = [
            message
            for index, message in enumerate(self.buffer)
            if index not in matched_index_set
        ]
        return pending_messages

    def get_length(self):
        return len(self.buffer)

    def get_buffer_lock(self) -> Lock:
        """get buffer lock"""
        return self.lock


class SessionBufferManager:
    def __init__(self, max_count: int = None):
        self.buffers: dict[str, SessionBuffer] = {}
        self.max_count = max_count

    def get_buffer(self, session: str):
        if session not in self.buffers:
            self.buffers[session] = SessionBuffer(self.max_count)
        return self.buffers[session]

    async def flush_messages(
        self,
        sid: str,
        extra_event: KiraMessageEvent | None = None,
        filter_fn: Optional[Callable[[KiraMessageEvent], bool]] = None,
    ) -> list[KiraMessageEvent]:
        """Atomically add an optional event and drain matching buffered events."""
        buffer = self.get_buffer(sid)
        async with buffer.lock:
            if extra_event is not None:
                buffer.add(extra_event)
            return buffer.flush(filter_fn=filter_fn)
