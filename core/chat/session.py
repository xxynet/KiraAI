import asyncio
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

    @property
    def sid(self):
        """unique session identifier"""
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"

    def __str__(self):
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"
