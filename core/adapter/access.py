from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias


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
        target_id: int | str | None,
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


__all__ = ["AccessController", "AccessPolicy", "ListAccessPolicy", "PermissionMode"]
