from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, TypeAlias, Union

from .context import AdapterContext

if TYPE_CHECKING:
    from core.chat.message_elements import Record
    from core.chat.message_utils import KiraIMSentResult, MessageChain
    from .qr_login import QRCodeLoginHandler


AdapterTargetId: TypeAlias = Union[int, str]


class BaseAdapter(ABC):
    """Common identity, configuration, event publishing, and lifecycle contract."""

    def __init__(self, ctx: AdapterContext):
        self.ctx = ctx
        self.info = ctx.info
        self.config = ctx.info.config
        self._event_queue = ctx.event_queue

    @classmethod
    def create_qrcode_login_handler(
        cls,
        config: dict[str, Any],
    ) -> QRCodeLoginHandler | None:
        """Create a QR-code login handler when the adapter supports it."""
        return None

    def publish(self, event: object) -> None:
        """Publish an adapter event without coupling the base to event subtypes."""
        self._event_queue.put_nowait(event)

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def get_client(self) -> Any: ...


class IMMixin(ABC):
    """Instant-messaging capability for one or more adapter domains."""

    @abstractmethod
    async def send_group_message(
        self,
        group_id: AdapterTargetId,
        message: MessageChain,
        *,
        domain: str,
    ) -> KiraIMSentResult | None: ...

    @abstractmethod
    async def send_direct_message(
        self,
        user_id: AdapterTargetId,
        message: MessageChain,
        *,
        domain: str,
    ) -> KiraIMSentResult | None: ...


class FeedMixin(ABC):
    """Feed, dynamic-post, and comment capability for adapter domains."""

    @abstractmethod
    async def get_feed(self, count: int, *, domain: str) -> list[Any]: ...

    @abstractmethod
    async def search_feed(
        self,
        keyword: str,
        count: int,
        *,
        domain: str,
    ) -> list[Any]: ...


    @abstractmethod
    async def send_comment(
        self,
        text: str,
        root: AdapterTargetId,
        sub: AdapterTargetId | None = None,
        *,
        domain: str,
    ) -> Any: ...


class LiveEventMixin(ABC):
    """Live-event subscription capability for one or more adapter domains."""

    @abstractmethod
    async def watch_live_events(
        self,
        room_id: AdapterTargetId,
        *,
        domain: str,
    ) -> None: ...

    @abstractmethod
    async def unwatch_live_events(
        self,
        room_id: AdapterTargetId,
        *,
        domain: str,
    ) -> None: ...


class VoiceChannelMixin(ABC):
    """Voice-channel capability for one or more adapter domains."""

    @abstractmethod
    async def join_voice_channel(
        self,
        channel_id: AdapterTargetId,
        *,
        domain: str,
    ) -> None: ...

    @abstractmethod
    async def leave_voice_channel(
        self,
        channel_id: AdapterTargetId,
        *,
        domain: str,
    ) -> None: ...

    @abstractmethod
    async def send_voice(
        self,
        channel_id: AdapterTargetId,
        audio: Record | bytes,
        *,
        domain: str,
    ) -> Any: ...


__all__ = [
    "AdapterTargetId",
    "BaseAdapter",
    "FeedMixin",
    "IMMixin",
    "LiveEventMixin",
    "VoiceChannelMixin",
]