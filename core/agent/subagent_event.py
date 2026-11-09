from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import ClassVar
from uuid import uuid4

from core.chat.session import Session

from .message import OpenAIMessage


@dataclass
class SubAgentEvent:
    """Separate tool permission identity from the routed agent conversation."""

    event_type: ClassVar[str] = "subagent_message"
    session: Session
    agent_session: Session
    content: str | OpenAIMessage
    source_session: Session | None = None
    event_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: int = field(default_factory=lambda: int(time.time()))
    extra: dict = field(default_factory=dict)
    _stopped: bool = field(
        default=False,
        init=False,
        repr=False,
    )
    _on_stop: Callable[[], object] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    @property
    def sid(self) -> str:
        return self.session.sid

    @property
    def target_session(self) -> Session:
        return self.agent_session

    @target_session.setter
    def target_session(self, session: Session) -> None:
        self.agent_session = session

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    def is_group_message(self) -> bool:
        return self.session.session_type == "gm"

    def stop(self) -> None:
        self._stopped = True
        if self._on_stop is not None:
            self._on_stop()
