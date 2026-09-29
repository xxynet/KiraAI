from __future__ import annotations

from collections.abc import Iterable
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


class AccessController:
    """Resolve access policies by registered capability type and permission."""

    def __init__(self):
        self._policies: dict[tuple[type[BaseCapability[Any]], str], AccessPolicy] = {}

    def set_policy(
        self,
        *,
        capability_type: type[BaseCapability[Any]],
        permission: str,
        policy: AccessPolicy,
    ) -> None:
        self._policies[self._key(capability_type, permission)] = policy

    def is_allowed(
        self,
        target_id: int | str | None,
        *,
        capability_type: type[BaseCapability[Any]],
        permission: str,
    ) -> bool:
        policy = self._policies.get(self._key(capability_type, permission))
        return policy.allows(target_id) if policy is not None else False

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


__all__ = ["AccessController", "AccessPolicy", "ListAccessPolicy", "PermissionMode"]
