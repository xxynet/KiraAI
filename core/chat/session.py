import asyncio
from dataclasses import dataclass


@dataclass()
class Session:
    adapter_name: str

    """gm for group message, dm for direct message"""
    session_type: str

    """group id or user id"""
    session_id: str

    @property
    def session_identifier(self):
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"

    def __str__(self):
        return f"{self.adapter_name}:{self.session_type}:{self.session_id}"
