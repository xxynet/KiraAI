from __future__ import annotations

from collections.abc import Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, TypeAlias

if TYPE_CHECKING:
    from .base import BaseCapability


PermissionMode: TypeAlias = Literal["allow_list", "deny_list"]


class AccessPolicy(Protocol):
    """Determine whether a target may perform a specific adapter operation."""

    def allows(self, target_id: int | str | None) -> bool: ...


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
        allow_list: Iterable[int | str] | None = None,
        deny_list: Iterable[int | str] | None = None,
    ) -> ListAccessPolicy:
        normalized_mode: PermissionMode = (
            "deny_list"
            if str(mode).strip().lower() == "deny_list"
            else "allow_list"
        )
        source = deny_list if normalized_mode == "deny_list" else allow_list
        entries = frozenset(str(entry) for entry in source or () if entry is not None)
        return cls(mode=normalized_mode, entries=entries)

    def allows(self, target_id: int | str | None) -> bool:
        if target_id is None:
            return False
        listed = str(target_id) in self.entries
        return listed if self.mode == "allow_list" else not listed


_active_policy_changes: ContextVar[tuple[PolicyChanges, ...]] = ContextVar(
    "active_adapter_policy_changes", default=(),
)


class PolicyChanges:
    """Record exact scoped writes owned by one capability lifecycle."""

    def __init__(self, controller: AccessController, kind: type[BaseCapability[Any]]):
        self._controller = controller
        self._kind = kind
        self._original: dict[str, tuple[AccessPolicy | None, object | None]] = {}
        self._applied: dict[str, object] = {}
        self._closed = False

    @contextmanager
    def record(self):
        token = _active_policy_changes.set((*_active_policy_changes.get(), self))
        try:
            yield
        finally:
            _active_policy_changes.reset(token)

    def _record_write(self, permission, previous, previous_version, version):
        if permission not in self._applied or self._applied[permission] is not previous_version:
            # An intervening external write becomes the baseline for a later owned write.
            self._original[permission] = previous, previous_version
        self._applied[permission] = version

    def restore(self):
        """Restore only keys whose latest write still belongs to this lifecycle."""
        controller = self._controller
        for permission, (previous, previous_version) in self._original.items():
            key = self._kind, permission
            if controller._policy_versions.get(key) is not self._applied[permission]:
                continue
            if previous is None:
                controller._policies.pop(key, None)
                controller._policy_versions.pop(key, None)
            else:
                controller._policies[key] = previous
                controller._policy_versions[key] = previous_version
        self.close()

    def close(self):
        self._closed = True
        self._original.clear()
        self._applied.clear()


class AccessController:
    """Resolve access policies by registered capability type and permission."""

    def __init__(self):
        self._policies: dict[tuple[type[BaseCapability[Any]], str], AccessPolicy] = {}
        self._policy_versions: dict[tuple[type[BaseCapability[Any]], str], object] = {}

    def set_policy(
        self,
        *,
        capability_type: type[BaseCapability[Any]],
        permission: str,
        policy: AccessPolicy,
    ) -> None:
        key = self._key(capability_type, permission)
        version = object()
        for changes in reversed(_active_policy_changes.get()):
            if (
                not changes._closed and changes._controller is self and changes._kind is key[0]
            ):
                changes._record_write(
                    key[1], self._policies.get(key), self._policy_versions.get(key), version,
                )
                break
        self._policies[key] = policy
        self._policy_versions[key] = version

    def is_allowed(
        self,
        target_id: int | str | None,
        *,
        capability_type: type[BaseCapability[Any]],
        permission: str,
    ) -> bool:
        policy = self._policies.get(self._key(capability_type, permission))
        return policy.allows(target_id) if policy is not None else False

    def get_policies(self, capability_type: type[BaseCapability[Any]]) -> dict[str, AccessPolicy]:
        """Snapshot one capability scope without exposing the mutable registry."""
        self._key(capability_type, "snapshot")
        return {
            permission: policy for (kind, permission), policy in self._policies.items()
            if kind is capability_type
        }

    def track_policies(self, capability_type: type[BaseCapability[Any]]) -> PolicyChanges:
        """Create a reusable, task-local write journal for one capability scope."""
        self._key(capability_type, "tracking")
        return PolicyChanges(self, capability_type)

    @staticmethod
    def _key(
        capability_type: type[BaseCapability[Any]], permission: str,
    ) -> tuple[type[BaseCapability[Any]], str]:
        from .base import BaseCapability

        if not isinstance(capability_type, type) or not issubclass(capability_type, BaseCapability):
            raise TypeError("capability_type must be a BaseCapability subclass")
        normalized_permission = permission.strip()
        if not normalized_permission:
            raise ValueError("permission must not be empty")
        return capability_type, normalized_permission


__all__ = ["AccessController", "AccessPolicy", "ListAccessPolicy", "PermissionMode", "PolicyChanges"]
