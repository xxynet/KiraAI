from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import (
    TYPE_CHECKING, Any, Generic, Literal, Protocol, TypeAlias, TypeVar, Union,
    overload,
)

from .context import AdapterContext

if TYPE_CHECKING:
    from core.chat.message_elements import Record
    from core.chat.message_utils import KiraIMSentResult, MessageChain
    from .qr_login import QRCodeLoginHandler


AdapterTargetId: TypeAlias = Union[int, str]
PermissionMode: TypeAlias = Literal["allow_list", "deny_list"]
AdapterT = TypeVar("AdapterT", bound="BaseAdapter")
CapabilityT = TypeVar("CapabilityT", bound="BaseCapability[Any]")


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
            "deny_list"
            if str(mode).strip().lower() == "deny_list"
            else "allow_list"
        )
        source = deny_list if normalized_mode == "deny_list" else allow_list
        entries = frozenset(str(entry) for entry in source or () if entry is not None)
        return cls(mode=normalized_mode, entries=entries)

    def allows(self, target_id: AdapterTargetId | None) -> bool:
        if target_id is None:
            return False
        listed = str(target_id) in self.entries
        return listed if self.mode == "allow_list" else not listed


class AccessController:
    """Resolve access policies by capability registration name and permission."""

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
    """Own named capability objects and their shared configuration and lifecycle.

    Subclasses decide which objects to register from their own configuration.
    Resources used by capabilities are started and stopped by the adapter.
    """

    def __init__(self, ctx: AdapterContext):
        self.ctx = ctx
        self.info = ctx.info
        self.config = ctx.info.config
        self._event_queue = ctx.event_queue
        self.access = AccessController()
        self._capabilities: dict[str, BaseCapability[Any]] = {}

    @property
    def capabilities(self) -> Mapping[str, BaseCapability[Any]]:
        """Expose registered objects without allowing registry mutation."""
        return MappingProxyType(self._capabilities)

    def register_capability(self, name: str, capability: CapabilityT) -> CapabilityT:
        """Register an instance owned by this adapter and return that instance."""
        name = self._capability_name(name)
        if not isinstance(capability, BaseCapability):
            raise TypeError("capability must be a BaseCapability instance")
        if capability.adapter is not self:
            raise ValueError("capability belongs to another adapter")
        if name in self._capabilities:
            raise ValueError(f"Capability '{name}' is already registered")
        if capability._name is not None:
            raise ValueError("capability instance is already registered")
        capability._name = name
        self._capabilities[name] = capability
        return capability

    @overload
    def get_capability(self, name: str) -> BaseCapability[Any]: ...

    @overload
    def get_capability(
        self, name: str, capability_type: type[CapabilityT],
    ) -> CapabilityT: ...

    def get_capability(
        self,
        name: str,
        capability_type: type[CapabilityT] | None = None,
    ) -> BaseCapability[Any]:
        """Look up a name, optionally checking and narrowing its capability type.

        Raise KeyError for an unregistered name and TypeError for a type mismatch.
        """
        capability = self._capabilities[self._capability_name(name)]
        if capability_type is not None and not isinstance(capability, capability_type):
            raise TypeError(f"Capability '{name}' is not a {capability_type.__name__}")
        return capability

    @overload
    def get_capabilities(
        self, capability_type: None = None,
    ) -> dict[str, BaseCapability[Any]]: ...

    @overload
    def get_capabilities(
        self, capability_type: type[CapabilityT],
    ) -> dict[str, CapabilityT]: ...

    def get_capabilities(
        self, capability_type: type[CapabilityT] | None = None,
    ) -> dict[str, BaseCapability[Any]] | dict[str, CapabilityT]:
        """Return a name-to-instance snapshot, optionally filtered by type.

        Include subclass instances and return an empty dict if nothing matches.
        Changing the returned dict does not modify the registry; objects are shared.
        """
        if capability_type is None:
            return self._capabilities.copy()
        return {
            name: capability
            for name, capability in self._capabilities.items()
            if isinstance(capability, capability_type)
        }

    @staticmethod
    def _capability_name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("capability name must be a non-empty string")
        return name.strip()

    @classmethod
    def create_qrcode_login_handler(
        cls, config: dict[str, Any],
    ) -> QRCodeLoginHandler | None:
        return None

    def is_allowed(
        self,
        target_id: AdapterTargetId | None,
        *,
        domain: str,
        permission: str,
    ) -> bool:
        return self.access.is_allowed(target_id, domain=domain, permission=permission)

    def publish(self, event: object) -> None:
        self._event_queue.put_nowait(event)

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def get_client(self) -> Any: ...


class BaseCapability(Generic[AdapterT], ABC):
    """An operation provider owned by one adapter and registered under one name.

    Specialize the adapter type to expose platform-specific members in editors,
    for example IMCapability[MyAdapter].
    """

    def __init__(self, adapter: AdapterT):
        self._adapter = adapter
        self._name: str | None = None

    @property
    def adapter(self) -> AdapterT:
        return self._adapter

    @property
    def name(self) -> str:
        if self._name is None:
            raise RuntimeError("capability has not been registered")
        return self._name

    def is_allowed(
        self, target_id: AdapterTargetId | None, *, permission: str,
    ) -> bool:
        """Check access using this object's registration name as the domain."""
        return self.adapter.is_allowed(
            target_id, domain=self.name, permission=permission,
        )


class IMCapability(BaseCapability[AdapterT]):
    """Instant messaging for a named part of an adapter."""

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
    "AccessController",
    "AccessPolicy",
    "AdapterTargetId",
    "BaseAdapter",
    "BaseCapability",
    "FeedCapability",
    "IMCapability",
    "ListAccessPolicy",
    "LiveEventCapability",
    "PermissionMode",
    "VoiceChannelCapability",
]
