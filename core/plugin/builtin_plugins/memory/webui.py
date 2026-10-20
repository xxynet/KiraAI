"""Serialization and filter normalization for the memory maintenance page.

Kept separate from ``store.py`` so the storage layer stays about SQL and
transactions while the WebUI payload shape (JSON-safe, locale-independent
machine values, epoch seconds) lives in one place. The frontend owns every
user-facing label and translates the machine values it receives here.
"""

from __future__ import annotations

from typing import Any

from .scope import MemoryInputError, MemoryScope

# Display column kept from the raw row. ``normalized`` and the ``term_count``
# bookkeeping are internal search artefacts and never leave the server.
PUBLIC_FIELDS = (
    "id", "revision", "text", "kind", "owner_type", "owner_id", "persona_id",
    "namespace", "session_id", "source_message_id", "importance", "core", "status",
    "expires_at", "created_at", "updated_at", "origin", "legacy_line",
)

FILTERS = ("kind", "status", "owner_type", "origin")


def _owner_labels(owner_type: str, owner_id: str) -> dict:
    """Split an ownership key into readable parts.

    ``scope.identity`` stores the owning coordinates as a JSON array
    (``[adapter, user|group]``); ``self`` owners store the
    bare persona ID and legacy rows store ``"shared"``.
    """
    if owner_type in ("self", "legacy"):
        return {"owner_id": owner_id, "adapter": None,
                "subject": None}
    try:
        parts = _loads(owner_id)
    except (ValueError, TypeError):
        return {"owner_id": owner_id, "adapter": None,
                "subject": None}
    if not isinstance(parts, list) or len(parts) != 2:
        return {"owner_id": owner_id, "adapter": None,
                "subject": None}
    adapter, subject = (str(part) for part in parts)
    return {"owner_id": owner_id, "adapter": adapter,
            "subject": subject}


def _loads(value: str):
    import json

    return json.loads(value)


def serialize(row: dict) -> dict:
    """One record as sent to the page."""
    record = {key: row.get(key) for key in PUBLIC_FIELDS}
    record["core"] = bool(record["core"])
    record.update(_owner_labels(str(record["owner_type"]), str(record["owner_id"])))
    return record


def _clean(value: Any) -> str | None:
    """Empty strings from query parameters mean "no filter"."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_filters(params: dict) -> dict:
    """Normalize query parameters into store keyword arguments.

    Enum-like values are validated here so an unexpected value surfaces as a
    typed :class:`MemoryInputError` instead of reaching SQL.
    """
    filters: dict = {"query": _clean(params.get("q")) or ""}
    for name in FILTERS:
        value = _clean(params.get(name))
        if value is None:
            continue
        if value not in _allowed(name):
            raise MemoryInputError("invalid_category")
        filters[name] = value
    core = _clean(params.get("core"))
    if core is not None:
        if core not in ("0", "1"):
            raise MemoryInputError("invalid_priority")
        filters["core"] = core == "1"
    return filters


def _allowed(name: str) -> tuple:
    from .store import KINDS, STATUSES

    return {
        "kind": tuple(sorted(KINDS)),
        "status": tuple(sorted(STATUSES)),
        "owner_type": ("group", "legacy", "self", "user"),
        "origin": ("conversation", "legacy"),
    }[name]


def parse_page(value: Any, default: int, minimum: int, maximum: int) -> int:
    """Strict integer query parameter with clamping."""
    if value is None or value == "":
        return default
    try:
        number = int(str(value))
    except (TypeError, ValueError) as exc:
        raise MemoryInputError("invalid_limit") from exc
    return max(minimum, min(maximum, number))


def overview_payload(overview: dict, max_core: int, max_recall: int) -> dict:
    """Overview response with the effective runtime settings attached."""
    return {
        **overview,
        "limits": {"core": max_core, "recall": max_recall},
    }


def parse_recall(payload: dict) -> tuple[MemoryScope, list[str]]:
    """Validate an operator-supplied conversation context without enabling writes."""
    def identifier(value):
        if not isinstance(value, str) or not value.strip() or len(value) > 512:
            raise MemoryInputError("invalid_recall")
        return value.strip()

    persona_id = identifier(payload.get("persona_id"))
    namespace = identifier(payload.get("namespace"))
    session_id = identifier(payload.get("session_id"))
    try:
        coordinates = _loads(namespace)
    except (ValueError, TypeError) as exc:
        raise MemoryInputError("invalid_recall") from exc
    if not isinstance(coordinates, list) or len(coordinates) != 1:
        raise MemoryInputError("invalid_recall")
    adapter = identifier(coordinates[0])
    parts = session_id.split(":", 2)
    if len(parts) != 3 or parts[0] != adapter or parts[1] not in {"dm", "gm"} or not parts[2]:
        raise MemoryInputError("invalid_recall")
    users = payload.get("user_ids", [])
    messages = payload.get("messages", [])
    if not isinstance(users, list) or len(users) > 30:
        raise MemoryInputError("invalid_recall")
    users = tuple(sorted({identifier(user) for user in users}))
    if parts[1] == "dm":
        if users and users != (parts[2],):
            raise MemoryInputError("invalid_recall")
        users = (parts[2],)
    if not isinstance(messages, list) or len(messages) > 3 or any(
        not isinstance(message, str) or len(message) > 4000 for message in messages
    ):
        raise MemoryInputError("invalid_recall")
    return MemoryScope(
        persona_id, session_id, adapter, users,
        parts[2] if parts[1] == "gm" else None, (),
    ), messages


def parse_recall_preview(payload: dict) -> tuple[dict, list[str]]:
    """Validate optional operator filters without requiring a live conversation."""
    filters = {}
    for key in ("persona_id", "session_id"):
        value = payload.get(key)
        if value is None or value == "":
            filters[key] = None
        elif isinstance(value, str) and value.strip() and len(value) <= 512:
            filters[key] = value.strip()
        else:
            raise MemoryInputError("invalid_recall")
    session_id = filters["session_id"]
    if session_id:
        parts = session_id.split(":", 2)
        if len(parts) != 3 or not parts[0] or parts[1] not in {"dm", "gm"} or not parts[2]:
            raise MemoryInputError("invalid_recall")
    if "user_ids" in payload:
        raise MemoryInputError("invalid_recall")
    messages = payload.get("messages", [])
    if not isinstance(messages, list) or len(messages) > 3 or any(
        not isinstance(message, str) or len(message) > 4000 for message in messages
    ):
        raise MemoryInputError("invalid_recall")
    return filters, messages


def parse_update(payload: dict) -> dict:
    """Only content fields are writable; scope and source attribution stay immutable."""
    allowed = {"revision", "text", "kind", "importance", "core", "status", "expires_at"}
    if set(payload) - allowed:
        raise MemoryInputError("invalid_update")
    revision = payload.get("revision")
    if type(revision) is not int or revision < 1:
        raise MemoryInputError("invalid_revision")
    if "text" not in payload:
        raise MemoryInputError("invalid_text")
    changes = dict(payload)
    for key in ("kind", "status"):
        if key in payload and (not isinstance(payload[key], str) or payload[key] not in _allowed(key)):
            raise MemoryInputError("invalid_category")
    if "importance" in payload and (type(payload["importance"]) is not int or not 1 <= payload["importance"] <= 5):
        raise MemoryInputError("invalid_priority")
    if "core" in payload and type(payload["core"]) is not bool:
        raise MemoryInputError("invalid_priority")
    if "expires_at" in payload and payload["expires_at"] is None:
        changes["clear_expiry"] = True
    return changes
