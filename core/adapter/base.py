from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Generic, TypeAlias, TypeVar, Union, overload

from .access import AccessController
from .context import AdapterContext

if TYPE_CHECKING:
    from .qr_login import QRCodeLoginHandler


AdapterTargetId: TypeAlias = Union[int, str]
AdapterT = TypeVar("AdapterT", bound="BaseAdapter")
CapabilityT = TypeVar("CapabilityT", bound="BaseCapability[Any]")


class BaseAdapter(ABC):
    """Own one object per capability kind and their shared lifecycle.

    Subclasses decide which objects to register from their own configuration.
    Resources used by capabilities are started and stopped by the adapter.
    """

    def __init__(self, ctx: AdapterContext):
        self.ctx = ctx
        self.info = ctx.info
        self.config = ctx.info.config
        self.message_types: list[str] = []
        self.emoji_dict: dict | None = None
        self._event_queue = ctx.event_queue
        self.access = AccessController()
        self._capabilities: dict[type[BaseCapability[Any]], BaseCapability[Any]] = {}

    @property
    def capabilities(self) -> Mapping[type[BaseCapability[Any]], BaseCapability[Any]]:
        """Expose registered objects without allowing registry mutation."""
        return MappingProxyType(self._capabilities)

    def register_capability(
        self, capability_type: type[CapabilityT], capability: CapabilityT,
    ) -> CapabilityT:
        """Register an owned instance under its type and return that instance.

        The registered type also scopes this object's access policies.
        """
        if not isinstance(capability_type, type) or not issubclass(capability_type, BaseCapability):
            raise TypeError("capability_type must be a BaseCapability subclass")
        if not isinstance(capability, BaseCapability):
            raise TypeError("capability must be a BaseCapability instance")
        if not isinstance(capability, capability_type):
            raise TypeError("capability must be an instance of capability_type")
        if capability.adapter is not self:
            raise ValueError("capability belongs to another adapter")
        if capability._capability_type is not None:
            raise ValueError("capability instance is already registered")
        if capability_type in self._capabilities:
            raise ValueError("a capability of this kind is already registered")
        kinds = self._capability_kinds(capability)
        for registered in self._capabilities.values():
            if kinds & self._capability_kinds(registered):
                raise ValueError("a capability of this kind is already registered")
        capability._capability_type = capability_type
        self._capabilities[capability_type] = capability
        return capability

    def get_capability(
        self, capability_type: type[CapabilityT],
    ) -> CapabilityT:
        """Return the unique matching capability, or raise ValueError."""
        if not isinstance(capability_type, type) or not issubclass(capability_type, BaseCapability):
            raise TypeError("capability_type must be a BaseCapability subclass")
        matches = self.get_capabilities(capability_type)
        if len(matches) != 1:
            raise ValueError(
                f"Expected one {capability_type.__name__}, found {len(matches)}"
            )
        return next(iter(matches.values()))

    @overload
    def get_capabilities(
        self, capability_type: None = None,
    ) -> dict[type[BaseCapability[Any]], BaseCapability[Any]]: ...

    @overload
    def get_capabilities(
        self, capability_type: type[CapabilityT],
    ) -> dict[type[BaseCapability[Any]], CapabilityT]: ...

    def get_capabilities(
        self, capability_type: type[CapabilityT] | None = None,
    ) -> dict[type[BaseCapability[Any]], BaseCapability[Any]] | dict[type[BaseCapability[Any]], CapabilityT]:
        """Return a type-to-instance snapshot, optionally filtered by type.

        Include subclass instances and return an empty dict if nothing matches.
        Changing the returned dict does not modify the registry; objects are shared.
        """
        if capability_type is None:
            return self._capabilities.copy()
        return {
            registered_type: capability
            for registered_type, capability in self._capabilities.items()
            if isinstance(capability, capability_type)
        }

    @staticmethod
    def _capability_kinds(capability: BaseCapability[Any]) -> set[type]:
        """Direct BaseCapability subclasses define kinds, including custom kinds."""
        return {
            cls for cls in type(capability).__mro__
            if BaseCapability in cls.__bases__
        } or {BaseCapability}

    @classmethod
    def create_qrcode_login_handler(
        cls, config: dict[str, Any],
    ) -> QRCodeLoginHandler | None:
        return None

    def is_allowed(
        self,
        target_id: AdapterTargetId | None,
        *,
        capability_type: type[BaseCapability[Any]],
        permission: str,
    ) -> bool:
        return self.access.is_allowed(target_id, capability_type=capability_type, permission=permission)

    def publish(self, event: object) -> None:
        """Queue an event without interpreting capability-specific data."""
        self._event_queue.put_nowait(event)

    @abstractmethod
    async def start(self) -> None: ...

    @abstractmethod
    async def stop(self) -> None: ...

    @abstractmethod
    def get_client(self) -> Any: ...


class BaseCapability(Generic[AdapterT], ABC):
    """An operation provider owned by one adapter and registered under a capability type.

    Specialize the adapter type to expose platform-specific members in editors,
    for example IMCapability[MyAdapter].
    """

    def __init__(self, adapter: AdapterT):
        self._adapter = adapter
        self._capability_type: type[BaseCapability[Any]] | None = None

    @property
    def adapter(self) -> AdapterT:
        return self._adapter

    @property
    def capability_type(self) -> type[BaseCapability[Any]]:
        if self._capability_type is None:
            raise RuntimeError("capability has not been registered")
        return self._capability_type

    def is_allowed(
        self, target_id: AdapterTargetId | None, *, permission: str,
    ) -> bool:
        """Check access using this object's registered capability type."""
        return self.adapter.is_allowed(
            target_id, capability_type=self.capability_type, permission=permission,
        )

    def publish(self, event: object) -> None:
        """Forward an event through the owning adapter."""
        self.adapter.publish(event)


__all__ = ["AdapterTargetId", "BaseAdapter", "BaseCapability"]
