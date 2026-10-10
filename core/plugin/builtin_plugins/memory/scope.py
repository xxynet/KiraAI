"""Context-derived ownership and visibility for conversation memories."""

from dataclasses import dataclass
import json


class MemoryInputError(ValueError):
    """A public error code, never containing memory content."""


def identity(*parts: str) -> str:
    return json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class MemoryScope:
    persona_id: str
    session_id: str
    adapter: str
    platform: str
    account: str
    users: tuple[str, ...]
    group_id: str | None
    sources: tuple[tuple[str, str], ...]

    @classmethod
    def from_event(cls, event, persona_id: str):
        session = getattr(event, "session", None)
        adapter = getattr(event, "adapter", None)
        if not session or not adapter or not persona_id:
            raise MemoryInputError("context_unavailable")
        if session.session_type not in {"dm", "gm"} or session.adapter_name != adapter.name:
            raise MemoryInputError("context_unavailable")
        messages = getattr(event, "messages", ())
        if not messages:
            raise MemoryInputError("context_unavailable")
        accounts = {str(m.self_id) for m in messages if m.self_id is not None}
        if len(accounts) != 1:
            raise MemoryInputError("context_unavailable")
        sources = []
        for message in messages:
            if getattr(message, "is_notice", False) or not message.sender:
                continue
            user_id = str(message.sender.user_id)
            if not user_id or user_id == "unknown":
                continue
            if session.session_type == "dm" and user_id != str(session.session_id):
                raise MemoryInputError("context_unavailable")
            if session.session_type == "gm" and (
                not message.group or str(message.group.group_id) != str(session.session_id)
            ):
                raise MemoryInputError("context_unavailable")
            sources.append((str(message.message_id), user_id))
        return cls(
            str(persona_id), session.sid, adapter.name, adapter.platform,
            next(iter(accounts)), tuple(sorted({user for _, user in sources})),
            str(session.session_id) if session.session_type == "gm" else None,
            tuple(sources),
        )

    @property
    def namespace(self) -> str:
        return identity(self.platform, self.adapter, self.account)

    def owner(self, owner_type: str, user_id: str | None = None) -> str:
        if owner_type == "self":
            return self.persona_id
        if owner_type == "group" and self.group_id:
            return identity(self.platform, self.adapter, self.account, self.group_id)
        if owner_type == "user":
            if user_id is None and len(self.users) == 1:
                user_id = self.users[0]
            if user_id in self.users:
                return identity(self.platform, self.adapter, self.account, user_id)
        raise MemoryInputError("invalid_owner")

    def source(self, owner_type: str, user_id: str | None, message_id: str | None) -> str:
        candidates = list(self.sources)
        if owner_type == "user":
            self.owner(owner_type, user_id)
            selected_user = user_id if user_id is not None else self.users[0]
            candidates = [(mid, uid) for mid, uid in candidates if uid == selected_user]
        if message_id is not None:
            candidates = [(mid, uid) for mid, uid in candidates if mid == message_id]
        elif len(self.users) > 1:
            raise MemoryInputError("source_required")
        if not candidates:
            raise MemoryInputError("source_required")
        return candidates[-1][0]

    def predicate(self, alias: str = "m") -> tuple[str, list]:
        owners = [("self", self.persona_id)]
        if self.group_id:
            owners.append(("group", self.owner("group")))
        owners.extend(("user", self.owner("user", uid)) for uid in self.users)
        clause = " OR ".join(f"({alias}.owner_type = ? AND {alias}.owner_id = ?)" for _ in owners)
        return (
            f"{alias}.persona_id = ? AND {alias}.namespace = ? AND {alias}.session_id = ? "
            f"AND ({clause})",
            [self.persona_id, self.namespace, self.session_id, *[value for pair in owners for value in pair]],
        )
