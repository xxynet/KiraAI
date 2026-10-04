from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from .base import AdapterT, AdapterTargetId, BaseCapability
from .message_format_metadata import MessageFormatMetadata
from .feed import FeedItem, FeedPage, FeedPost, FeedQuery, FeedRef, FeedSearchQuery

if TYPE_CHECKING:
    from core.chat.message_elements import Record
    from core.chat.message_utils import KiraIMSentResult, MessageChain


class IMCapability(BaseCapability[AdapterT]):
    """Instant messaging operations for an adapter."""

    def __init__(self, adapter: AdapterT):
        super().__init__(adapter)
        self._supported_elements: list[str] = (
            adapter._legacy_message_types
            if adapter._legacy_message_types is not None
            else list(getattr(self, "_SUPPORTED_ELEMENTS", []))
        )

    @abstractmethod
    async def get_message_metadata(self) -> MessageFormatMetadata:
        """Return the initialized output-format metadata."""
        ...

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
    async def get_comment_metadata(self) -> MessageFormatMetadata: ...

    @abstractmethod
    async def get_post_metadata(self) -> MessageFormatMetadata: ...

    @abstractmethod
    async def get_feed(self, query: FeedQuery) -> FeedPage: ...

    @abstractmethod
    async def search_feed(self, query: FeedSearchQuery) -> FeedPage: ...

    @abstractmethod
    async def send_post(self, post: FeedPost) -> Any: ...

    @abstractmethod
    async def send_comment(
        self,
        message: MessageChain,
        target: FeedItem | FeedRef,
        *,
        root: AdapterTargetId | None = None,
        parent: AdapterTargetId | None = None,
    ) -> Any:
        """Comment on a feed item or an adapter-issued resource reference.

        For received comments, pass the event's target, root_comment_id as root,
        and comment_id as parent. Adapters interpret these IDs for their platform.
        """
        ...


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
