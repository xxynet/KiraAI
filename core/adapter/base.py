from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias, Union

from .context import AdapterContext

if TYPE_CHECKING:
    from core.chat.message_elements import Record
    from core.chat.message_utils import KiraIMSentResult, MessageChain
    from .qr_login import QRCodeLoginHandler


AdapterTargetId: TypeAlias = Union[int, str]

PermissionMode: TypeAlias = Literal["allow_list", "deny_list"]


class AccessPolicy(Protocol):
    """Determine whether a target may perform a specific adapter operation."""

    def allows(self, target_id: AdapterTargetId | None) -> bool: ...


@dataclass(frozen=True, slots=True)
class ListAccessPolicy:
    """Allow or deny targets according to a normalized identifier set."""

    mode: PermissionMode
    entries: frozenset[str]

    @classmethod
    def from_lists(
        cls,
        mode: str,
        *,
        allow_list: Iterable[AdapterTargetId] | None = None,
        deny_list: Iterable[AdapterTargetId] | None = None,
    ) -> ListAccessPolicy:
        normalized_mode: PermissionMode = (
            "deny_list" if str(mode).strip().lower() == "deny_list"
            else "allow_list"
        )
        source = deny_list if normalized_mode == "deny_list" else allow_list
        entries = frozenset(
            str(entry)
            for entry in source or ()
            if entry is not None
        )
        return cls(mode=normalized_mode, entries=entries)

    def allows(self, target_id: AdapterTargetId | None) -> bool:
        if target_id is None:
            return False

        listed = str(target_id) in self.entries
        return listed if self.mode == "allow_list" else not listed


class AccessController:
    """Resolve access policies by adapter domain and permission name."""

    def __init__(self):
        self._policies: dict[tuple[str, str], AccessPolicy] = {}

    def set_policy(
        self,
        *,
        domain: str,
        permission: str,
        policy: AccessPolicy,
    ) -> None:
        self._policies[self._key(domain, permission)] = policy

    def is_allowed(
        self,
        target_id: AdapterTargetId | None,
        *,
        domain: str,
        permission: str,
    ) -> bool:
        policy = self._policies.get(self._key(domain, permission))
        return policy.allows(target_id) if policy is not None else False

    @staticmethod
    def _key(domain: str, permission: str) -> tuple[str, str]:
        normalized_domain = domain.strip()
        normalized_permission = permission.strip()
        if not normalized_domain:
            raise ValueError("domain must not be empty")
        if not normalized_permission:
            raise ValueError("permission must not be empty")
        return normalized_domain, normalized_permission


class BaseAdapter(ABC):
    """Common identity, configuration, event publishing, and lifecycle contract."""

    def __init__(self, ctx: AdapterContext):
        self.ctx = ctx
        self.info = ctx.info
        self.config = ctx.info.config
        self._event_queue = ctx.event_queue
        self.access = AccessController()

    @classmethod
    def create_qrcode_login_handler(
        cls,
        config: dict[str, Any],
    ) -> QRCodeLoginHandler | None:
        """Create a QR-code login handler when the adapter supports it."""
        return None

    def is_allowed(
        self,
        target_id: AdapterTargetId | None,
        *,
        domain: str,
        permission: str,
    ) -> bool:
        """Return whether a target may use a domain-specific permission."""
        return self.access.is_allowed(
            target_id,
            domain=domain,
            permission=permission,
        )

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
    "AccessController",
    "AccessPolicy",
    "AdapterTargetId",
    "BaseAdapter",
    "FeedMixin",
    "IMMixin",
    "ListAccessPolicy",
    "LiveEventMixin",
    "PermissionMode",
    "VoiceChannelMixin",
]
