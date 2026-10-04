from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MessageFormatMetadata:
    """Output-format hints with caller-owned supported elements and emoji data.

    Emoji IDs remain opaque to callers. None means emoji is unsupported; an
    empty mapping means no enumerable catalog.
    This describes formats, not permissions or account readiness.
    """

    supported_elements: list[str] = field(default_factory=list)
    emojis: dict[str, str] | None = None

    def __post_init__(self) -> None:
        supported_elements = list(self.supported_elements)
        if not all(isinstance(value, str) for value in supported_elements):
            raise TypeError("Supported elements must be strings")
        self.supported_elements = supported_elements
        if self.emojis is not None:
            emojis = dict(self.emojis)
            if not all(isinstance(key, str) and isinstance(value, str) for key, value in emojis.items()):
                raise TypeError("Emoji metadata must map string IDs to string values")
            self.emojis = emojis


def load_emoji_mapping(path: Path) -> dict[str, str]:
    """Read and validate a small local catalog directly.

    Errors propagate so callers can distinguish unavailable data from an
    unsupported format. Each call reads a fresh dictionary.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Emoji metadata must be a JSON object")
    metadata = MessageFormatMetadata(emojis=data)
    assert metadata.emojis is not None
    return metadata.emojis
