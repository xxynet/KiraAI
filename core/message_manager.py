from asyncio import Lock
from typing import Callable, Optional

from deprecated import deprecated

from core.agent.message import OpenAIMessage
from core.chat.session_buffer import SessionBufferManager
from core.chat.message_utils import (
    KiraIMSentResult, KiraMessageEvent,
    KiraCommentEvent, MessageChain,
)
from core.logging_manager import get_logger
from core.plugin.handlers import event_handler_reg, EventType
from core.workflow import IMWorkflow
from core.workflow.src.im.batching import publish_buffered_messages
from core.workflow.src.im.message_delivery import MessageDeliveryService

logger = get_logger("message", "cyan")


class MessageProcessor:
    """Dispatch messages to an injected workflow and preserve plugin entry points."""

    def __init__(self, im_workflow: IMWorkflow):
        self.im_workflow = im_workflow
        self.message_processing_semaphore = im_workflow.message_processing_semaphore
        logger.info("MessageProcessor initialized")

    @property
    def message_delivery(self) -> MessageDeliveryService:
        return self.im_workflow.ctx.message_delivery

    @property
    def session_buffer(self) -> SessionBufferManager:
        return self.im_workflow.ctx.message_buffer

    def get_session_lock(self, sid: str) -> Lock:
        return self.message_delivery.get_session_lock(sid)

    def get_session_buffer_length(self, sid: str) -> int:
        return self.session_buffer.get_buffer(sid).get_length()

    async def pop_session_messages(self, sid: str, count: int = 1):
        self.session_buffer.get_buffer(sid).pop(count)

    async def flush_session_messages(
        self,
        sid: str,
        extra_event: KiraMessageEvent | None = None,
        filter_fn: Optional[Callable[[KiraMessageEvent], bool]] = None,
    ) -> bool:
        """Publish buffered events using the workflow's shared buffer and event bus."""
        return await publish_buffered_messages(
            self.session_buffer, self.im_workflow.ctx.event_bus, sid,
            extra_event=extra_event, filter_fn=filter_fn,
        )

    @deprecated("Use PluginContext.send_message_chain instead")
    async def send_message_chain(self, session: str, chain: MessageChain, *, memory_message: OpenAIMessage | None = None, self_id: str | None = None) -> KiraIMSentResult:
        return await self.message_delivery.send_message_chain(
            session, chain, memory_message=memory_message, self_id=self_id)

    @deprecated("Publish the event with await PluginContext.event_bus.publish(event) instead")
    async def handle_im_message(self, event: KiraMessageEvent):
        await self.im_workflow.handle_event(event)

    async def handle_cmt_event(self, event: KiraCommentEvent):
        """Deliver comments to plugins under the shared message concurrency limit."""
        async with self.message_processing_semaphore:
            for handler in tuple(event_handler_reg.get_handlers(EventType.ON_COMMENT)):
                if event.is_stopped:
                    break
                await handler.exec_handler(event)
