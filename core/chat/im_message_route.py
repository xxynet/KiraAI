from __future__ import annotations

from typing import TYPE_CHECKING

from .message_utils import (
    KiraIMSentResult,
    KiraMessageBatchEvent,
    KiraMessageEvent,
    MessageChain,
)
from .session import Session, User

if TYPE_CHECKING:
    from core.adapter import AdapterManager
    from core.agent.message import OpenAIMessage
    from core.workflow import IMWorkflow
    from core.workflow.src.im.message_delivery import MessageDeliveryService


class IMMessageRoute:
    """Route incoming IM events to their workflow and outgoing messages to adapters."""

    def __init__(
        self,
        delivery: MessageDeliveryService,
        adapter_mgr: AdapterManager,
        workflow: IMWorkflow,
    ):
        self.delivery = delivery
        self.adapter_mgr = adapter_mgr
        self.workflow = workflow

    def matches(self, session: Session) -> bool:
        """Match only sessions belonging to a registered platform adapter."""
        return (
            session.kind == "im"
            and session.session_type in {"dm", "gm"}
            and self.adapter_mgr.get_adapter(session.adapter_name) is not None
        )

    async def receive_message(self, session: Session, message: object) -> None:
        """Dispatch single and batched IM events without republishing them."""
        if not isinstance(message, (KiraMessageEvent, KiraMessageBatchEvent)):
            raise TypeError(f"Unsupported IM message type: {type(message).__name__}")
        message.session = session
        if isinstance(message, KiraMessageEvent):
            await self.workflow.handle_event(message)
        else:
            await self.workflow.handle_batch_event(message)

    async def send_message_chain(
        self, session: Session, chain: MessageChain, *,
        memory_message: OpenAIMessage | None = None, bot: User | None = None,
    ) -> KiraIMSentResult:
        """Keep outgoing archival, bot identity, and adapter results unchanged."""
        return await self.delivery.send_message_chain(
            session.sid,
            chain,
            memory_message=memory_message,
            bot=bot,
        )
