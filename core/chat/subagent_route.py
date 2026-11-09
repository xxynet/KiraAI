from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from core.agent.message import OpenAIMessage
from core.agent.subagent_event import SubAgentEvent

from .message_elements import Image, Text
from .message_utils import (
    KiraIMSentResult,
    KiraMessageBatchEvent,
    KiraMessageEvent,
    MessageChain,
)
from .session import Session, User

if TYPE_CHECKING:
    from core.agent.subagent_manager import SubAgentManager


class SubAgentRoute:
    """Deliver child-session input without adapters or platform reply formatting."""

    def __init__(self, manager: SubAgentManager):
        self.manager = manager

    def matches(self, session: Session) -> bool:
        return session.kind == "subagent"

    @staticmethod
    async def _message(chain: MessageChain) -> OpenAIMessage:
        parts = []
        for element in chain:
            if isinstance(element, Image):
                url = element.file if element.check_file_type() == "url" else await element.to_data_url()
                parts.append({"type": "image_url", "image_url": {"url": url}})
            else:
                text = element.text if isinstance(element, Text) else element.repr
                parts.append({"type": "text", "text": text})
        if all(part["type"] == "text" for part in parts):
            content = "\n".join(part["text"] for part in parts)
        else:
            content = parts
        return OpenAIMessage(
            role="user",
            content=content,
        )

    async def receive_message(self, session: Session, message: object) -> None:
        if isinstance(message, SubAgentEvent):
            content = message.content
            caller_id = message.source_session.internal_id if message.source_session else None
        elif isinstance(message, (KiraMessageEvent, KiraMessageBatchEvent)):
            messages = message.messages if isinstance(message, KiraMessageBatchEvent) else [message.message]
            content = await self._message(MessageChain([
                element for incoming in messages for element in incoming.chain
            ]))
            caller_id = None
        elif isinstance(message, (str, OpenAIMessage)):
            content = message
            caller_id = None
        else:
            raise TypeError(f"Unsupported subagent input: {type(message).__name__}")
        await self.manager.followup(
            session,
            content,
            caller_id=caller_id,
        )

    async def send_message_chain(
        self,
        session: Session,
        chain: MessageChain,
        *,
        memory_message: OpenAIMessage | None = None,
        bot: User | None = None,
    ) -> KiraIMSentResult:
        await self.manager.followup(
            session,
            await self._message(chain),
        )
        return KiraIMSentResult(message_id=f"input_{uuid4().hex}")

    async def get_receive_permission_error(self, session: Session) -> str | None:
        """Check availability; caller ownership is checked by manager operations."""
        if self.manager._closing:
            return "Subagent manager is shutting down"
        return None
