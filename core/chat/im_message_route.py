from __future__ import annotations

from typing import TYPE_CHECKING

from core.adapter.capabilities import IMCapability

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
            session.session_type in {"dm", "gm"}
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

    async def get_receive_permission_error(self, session: Session) -> str | None:
        """Apply the existing adapter policy to the opaque target ID."""
        adapter_name, session_type, session_id = session.adapter_name, session.session_type, session.session_id
        if session_type not in {"dm", "gm"}:
            return "Permission denied: target session type must be dm or gm"
        adapter = self.adapter_mgr.get_adapter(adapter_name)
        if adapter is None:
            return f"Permission denied: adapter not found: {adapter_name}"
        try:
            capability = adapter.get_capability(IMCapability)
        except ValueError:
            is_allowed = False
        else:
            permission = "im.direct.receive" if session_type == "dm" else "im.group.receive"
            is_allowed = capability.is_allowed(session_id, permission=permission)
        if not is_allowed:
            return f"Permission denied: target session is not allowed by adapter {adapter_name}"
        return None
