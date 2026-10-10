"""Bridge the admin UI to the same event queue used by other IM adapters."""
from __future__ import annotations

import asyncio

from core.adapter.builtin.webchat.im import WebChatIMCapability
from core.chat.message_elements import BaseMediaElement, Text
from core.chat.message_history import serialize_message_chain
from core.chat.message_utils import MessageChain


class WebChatService:
    def __init__(self, adapter, session_manager):
        self.adapter = adapter
        self.store = adapter.store
        self.sessions = session_manager
        self._lock = asyncio.Lock()
        self._closed = False

    async def initialize(self):
        profile = await self.store.get_setting("profile")
        if profile is not None:
            await self._apply_profile(profile)

    async def _apply_profile(self, profile):
        await asyncio.to_thread(
            self.sessions.update_session_info,
            self.adapter.SID,
            title=profile["peer_nickname"],
            description=profile["description"],
        )

    async def save_profile(self, profile):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.set_setting("profile", profile)
            await self._apply_profile(profile)
        return profile

    async def submit(self, request_id: str, text: str, attachments: list[BaseMediaElement] | None = None):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            profile = await self.store.get_setting("profile")
            if profile is None:
                raise ValueError("setup_required")
            chain = MessageChain(([Text(text)] if text else []) + (attachments or []))
            if not list(chain):
                raise ValueError("empty_message")
            elements = await serialize_message_chain(chain, archive_root=self.store.media_dir)
            if any(item.get("file_type") == "unavailable" for item in elements):
                raise ValueError("attachment_failed")
            existing = await self.store.get_request(request_id, text, elements)
            if existing is not None:
                return existing
            await self._apply_profile(profile)
            for index, element in enumerate(chain):
                if isinstance(element, BaseMediaElement):
                    archived = await asyncio.to_thread(
                        type(element), str(self.store.media_dir / elements[index]["file"]),
                        mime=element.mime, name=element.name,
                    )
                    archived.size = element.size
                    chain[index] = archived
            request, created = await self.store.accept(request_id, text, profile["nickname"], elements)
            if created:
                try:
                    self.adapter.get_capability(WebChatIMCapability).receive_message(request_id, chain, profile)
                except Exception:
                    await self.store.finish(request_id, "failed")
                    raise ValueError("unavailable") from None
            return request

    async def clear_messages(self):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.clear_messages()

    async def stop(self):
        async with self._lock:
            self._closed = True
