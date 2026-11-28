"""Bridge the admin UI to the same event queue used by other IM adapters."""

from __future__ import annotations

import asyncio

from core.adapter.builtin.webchat.im import WebChatIMCapability
from core.chat.message_elements import BaseMediaElement, Reply, Text
from core.chat.message_history import (
    _deserialize_message_chain,
    serialize_message_chain,
)
from core.chat.message_utils import MessageChain
from core.logging_manager import get_logger

logger = get_logger("webchat", "cyan")


class WebChatService:
    def __init__(self, adapter, session_manager) -> None:
        self.adapter = adapter
        self.store = adapter.store
        self.sessions = session_manager
        self._lock = asyncio.Lock()
        self._closed = False

    async def initialize(self) -> None:
        config = await self.store.get_setting("adapter_config")
        if config is not None:
            self.adapter.config.update(config)
        profile = await self.store.get_setting("profile")
        if profile is not None:
            await self._apply_profile(profile)

    async def _apply_profile(self, profile) -> None:
        await self.sessions.update_session(
            self.adapter.SID,
            title=profile["nickname"],
            description=profile["description"],
        )

    async def save_config(self, config):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.set_setting("adapter_config", config)
            self.adapter.config.update(config)
        return dict(self.adapter.config)

    async def save_profile(self, profile):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.set_setting("profile", profile)
            await self._apply_profile(profile)
        return profile

    async def submit(
        self,
        request_id: str,
        text: str,
        attachments: list[BaseMediaElement] | None = None,
        reply_to: str | None = None,
    ):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            profile = await self.store.get_setting("profile")
            if profile is None:
                raise ValueError("setup_required")
            chain = MessageChain(([Text(text)] if text else []) + (attachments or []))
            if not list(chain):
                raise ValueError("empty_message")
            elements = await serialize_message_chain(
                chain, archive_root=self.store.media_dir
            )
            if any(item.get("file_type") == "unavailable" for item in elements):
                raise ValueError("attachment_failed")
            persisted = await self.store.get_message(request_id)
            snapshot = None
            if persisted is not None:
                saved_chain = persisted["chain"]
                if saved_chain and saved_chain[0].get("type") == "reply":
                    snapshot = saved_chain[0]
                if (
                    snapshot.get("message_id") if snapshot is not None else None
                ) != reply_to:
                    raise ValueError("request_conflict")
            retry_elements = [snapshot, *elements] if snapshot is not None else elements
            existing = await self.store.get_request(request_id, text, retry_elements)
            if existing is not None:
                return existing
            if reply_to is not None:
                original = await self.store.get_message(reply_to)
                if original is None:
                    raise ValueError("reply_not_found")
                quoted = await asyncio.to_thread(
                    _deserialize_message_chain,
                    original["chain"],
                    depth=1,
                    archive_root=self.store.media_dir,
                )
                chain = MessageChain([Reply(reply_to, chain=quoted), *chain])
                elements = await serialize_message_chain(
                    chain, archive_root=self.store.media_dir
                )
            await self._apply_profile(profile)
            request, created = await self.store.accept(
                request_id, text, profile["nickname"], elements
            )
            if created:
                try:
                    self.adapter.get_capability(WebChatIMCapability).receive_message(
                        request_id, chain, profile
                    )
                except Exception:
                    logger.exception("Failed to dispatch webchat request %s", request_id)
                    await self.store.finish(request_id, "failed")
                    raise ValueError("unavailable") from None
            return request

    async def delete_message(self, message_id: str):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.delete_message(message_id)

    async def clear_messages(self):
        async with self._lock:
            if self._closed:
                raise ValueError("unavailable")
            await self.store.clear_messages()

    async def stop(self):
        async with self._lock:
            self._closed = True
