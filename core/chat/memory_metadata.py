"""Metadata persisted with memory messages, never sent to model providers."""

from copy import deepcopy
from uuid import uuid4


def normalize_memory(memory: list, *, previous: list | None = None) -> list:
    """Assign stable identities; copied or role-changed messages get new IDs."""
    if not isinstance(memory, list) or any(
        not isinstance(chunk, list) or any(
            not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}
            for message in chunk
        ) for chunk in memory
    ):
        raise ValueError("Memory must be a list of message lists with valid roles")
    result = deepcopy(memory)
    existing = {}
    if previous is not None:
        for chunk in previous:
            for message in chunk:
                extra = message.get("_extra")
                if isinstance(extra, dict) and isinstance(extra.get("llm_message_id"), str):
                    existing[extra["llm_message_id"]] = message.get("role")
    seen = set()
    for chunk in result:
        for message in chunk:
            value = message.get("_extra")
            extra = dict(value) if isinstance(value, dict) else {}
            identity = extra.get("llm_message_id")
            if not isinstance(identity, str) or not identity or identity in seen:
                identity = None
            if previous is not None and existing.get(identity) != message.get("role"):
                identity = None
            if identity is None:
                identity = uuid4().hex
            seen.add(identity)
            extra["llm_message_id"] = identity
            message["_extra"] = extra
    return result
