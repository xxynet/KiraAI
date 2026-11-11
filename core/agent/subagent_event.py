from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.chat.message_elements import Image, Text
from core.chat.message_utils import KiraIMMessage, KiraMessageBatchEvent, MessageChain
from core.chat.session import Group, Session, User

from .message import OpenAIMessage

if TYPE_CHECKING:
    from core.adapter.adapter_info import AdapterInfo


@dataclass(kw_only=True)
class SubAgentEvent(KiraMessageBatchEvent):
    """Separate tool permission identity from the routed agent conversation."""

    session: Session
    agent_session: Session
    content: str | OpenAIMessage
    source_session: Session | None = None
    supported_elements: list[str] = field(default_factory=list)
    timestamp: int = field(default_factory=lambda: int(time.time()))
    extra: dict = field(default_factory=dict)
    _source_batch_metadata: tuple[AdapterInfo | None, tuple[str, ...], User | None] | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _source_bot: User | None = field(default=None, init=False, repr=False)
    _on_stop: Callable[[], object] | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        if self.event_id is None:
            super().__post_init__()
        if self.content and not self.messages:
            self.append_input(self.content)

    def set_source_batch(self, source: KiraMessageBatchEvent | None) -> None:
        """Capture transport metadata from an input batch in the permission session."""
        if not isinstance(source, KiraMessageBatchEvent) or source.session is None or source.sid != self.sid:
            return
        self._source_batch_metadata = (
            source.adapter,
            tuple(source.supported_elements),
            deepcopy(source.bot) if source.messages else None,
        )

    def begin_turn(self) -> None:
        """Reset the batch before appending this turn's task and steering inputs."""
        super().__post_init__()
        self.timestamp = int(time.time())
        self._is_stopped = False
        self.content = ""
        self.messages = []
        self.message_str = None
        self.message_repr = None
        if self._source_batch_metadata is not None:
            self.adapter, supported_elements, self._source_bot = self._source_batch_metadata
            self.supported_elements = list(supported_elements)

    def append_input(self, message: str | OpenAIMessage) -> None:
        """Expose the task to tools as an IM message in the permission session."""
        self.content = message
        content = message.content if isinstance(message, OpenAIMessage) else message
        parts = content if isinstance(content, list) else [{"type": "text", "text": str(content or "")}]
        elements = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                elements.append(Text(part["text"]))
            elif part.get("type") == "image_url" and isinstance(part.get("image_url"), dict):
                url = part["image_url"].get("url")
                if isinstance(url, str) and url.startswith(("https://", "http://", "data:image/")):
                    elements.append(Image(image=url))
        text = "\n".join(element.text for element in elements if isinstance(element, Text))
        display = " ".join(element.repr for element in elements)
        group = None
        if self.session.session_type == "gm":
            group = Group(self.session.session_id, self.session.session_title)
        input_message = KiraIMMessage(
            message_id=f"{self.event_id}:{len(self.messages)}",
            self_id=self._source_bot.user_id if self._source_bot is not None else "",
            chain=MessageChain(elements),
            timestamp=self.timestamp,
            bot=deepcopy(self._source_bot),
            sender=User("", "system"),
            session=self.session,
            group=group,
        )
        input_message.message_str = text
        input_message.message_repr = display
        input_message.native_content = deepcopy(parts)
        self.messages.append(input_message)
        self.message_str = "\n".join(filter(None, (self.message_str, text)))
        self.message_repr = "\n".join(filter(None, (self.message_repr, display)))

    @property
    def target_session(self) -> Session:
        return self.agent_session

    @target_session.setter
    def target_session(self, session: Session) -> None:
        self.agent_session = session

    def stop(self) -> None:
        super().stop()
        if self._on_stop is not None:
            self._on_stop()
