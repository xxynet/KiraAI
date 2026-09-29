from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from .base import AdapterT, AdapterTargetId, BaseCapability

if TYPE_CHECKING:
    from core.chat.message_elements import Record
    from core.chat.message_utils import KiraIMSentResult, MessageChain


class IMCapability(BaseCapability[AdapterT]):
    """Instant messaging operations for an adapter."""

    @abstractmethod
    async def send_group_message(
        self, group_id: AdapterTargetId, message: MessageChain,
    ) -> KiraIMSentResult | None: ...

    @abstractmethod
    async def send_direct_message(
        self, user_id: AdapterTargetId, message: MessageChain,
    ) -> KiraIMSentResult | None: ...


class FeedCapability(BaseCapability[AdapterT]):
    """Feed, dynamic-post, and comment operations."""

    @abstractmethod
    async def get_feed(self, count: int) -> list[Any]: ...

    @abstractmethod
    async def search_feed(self, keyword: str, count: int) -> list[Any]: ...

    @abstractmethod
    async def send_comment(
        self,
        text: str,
        root: AdapterTargetId,
        sub: AdapterTargetId | None = None,
    ) -> Any: ...


class LiveEventCapability(BaseCapability[AdapterT]):
    """Live-event subscriptions."""

    @abstractmethod
    async def watch_live_events(self, room_id: AdapterTargetId) -> None: ...

    @abstractmethod
    async def unwatch_live_events(self, room_id: AdapterTargetId) -> None: ...


class VoiceChannelCapability(BaseCapability[AdapterT]):
    """Voice-channel membership and audio transmission."""

    @abstractmethod
    async def join_voice_channel(self, channel_id: AdapterTargetId) -> None: ...

    @abstractmethod
    async def leave_voice_channel(self, channel_id: AdapterTargetId) -> None: ...

    @abstractmethod
    async def send_voice(
        self, channel_id: AdapterTargetId, audio: Record | bytes,
    ) -> Any: ...


__all__ = [
    "FeedCapability",
    "IMCapability",
    "LiveEventCapability",
    "VoiceChannelCapability",
]
