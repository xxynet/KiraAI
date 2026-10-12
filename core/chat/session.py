from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field


@dataclass
class User:
    """User dataclass"""

    """user unique identifier"""
    user_id: str

    """nickname"""
    nickname: str = None

    extra: dict = field(default_factory=dict)


@dataclass
class Group:
    """Group dataclass, describing all the info of the group"""

    """group unique identifier"""
    group_id: str

    """group name"""
    group_name: str = None

    extra: dict = field(default_factory=dict)


@dataclass
class Session:
    adapter_name: str

    """gm for group message, dm for direct message"""
    session_type: str

    """group id or user id"""
    session_id: str

    """session title, could be group name or user nickname"""
    session_title: str = None

    """session description"""
    session_description: str = None

    """last message timestamp"""
    timestamp: int = None

    internal_id: str = None
    created_at: int = None
    updated_at: int = None

    content: list[list[dict]] = field(default_factory=list, repr=False)
    data: dict = field(default_factory=dict, repr=False)

    def flatten_content(self) -> list[dict]:
        """Return a deep copy of the flattened content in message order."""
        return deepcopy([message for chunk in self.content for message in chunk])

    @classmethod
    def from_record(cls, record: dict) -> Session:
        """Build an independent session snapshot from a database record."""
        parts = record["session_key"].split(":", maxsplit=2)
        if len(parts) != 3:
            raise ValueError("Invalid session routing key")
        return cls(
            adapter_name=parts[0], session_type=parts[1], session_id=parts[2],
            session_title=record["title"], session_description=record["description"],
            timestamp=record["updated_at"], internal_id=record["id"],
            created_at=record["created_at"], updated_at=record["updated_at"],
            content=deepcopy(record.get("content", [])), data=deepcopy(record["data"]),
        )

    @property
    def sid(self):
        """unique session identifier"""
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"

    def __str__(self):
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"
