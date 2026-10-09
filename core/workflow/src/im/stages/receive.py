from core.workflow.base_stage import BaseStage
import time

from core.chat.message_utils import KiraMessageBatchEvent
from ..batching import publish_buffered_messages
from ..context import IMEventContext
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg

logger = get_logger("message", "cyan")


class ReceiveStage(BaseStage[IMEventContext]):
    """Archive the original message and dispatch incoming-message plugins."""

    async def run(self, ctx: IMEventContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        # decorating event info
        if services.message_history is not None:
            await services.message_history.record_incoming_safely(event.message, sid, event.adapter.platform)

        event.session.session_description = services.session_manager.get_session_info(sid).session_description

        # EventType.ON_IM_MESSAGE
        im_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_MESSAGE)
        for handler in im_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
                # Print event
                logger.info(event.get_log_info())
                return False

        # Print event
        logger.info(event.get_log_info())
        return True


class RouteStage(BaseStage[IMEventContext]):
    """Apply the plugin-selected discard, trigger, buffer, or flush strategy."""

    async def run(self, ctx: IMEventContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        # Check if message chain is valid, filter out unprocessed notice messages
        if event.message.chain.is_empty():
            return False

        if event.process_strategy == "discard":
            return False

        if event.process_strategy == "trigger":
            batch_msg = KiraMessageBatchEvent(
                supported_elements=event.supported_elements,
                timestamp=int(time.time()),
                adapter=event.adapter,
                session=event.session,
                messages=[event.message]
            )
            await services.event_bus.publish(batch_msg)
            return False

        if event.process_strategy == "buffer":
            buffer = services.message_buffer.get_buffer(sid)
            async with buffer.lock:
                buffer.add(event)

            # EventType.ON_MESSAGE_BUFFERED
            im_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_MESSAGE_BUFFERED)
            for handler in im_handlers:
                await handler.exec_handler(event.session.sid)
            return False

        if event.process_strategy == "flush":
            flushed = await publish_buffered_messages(
                services.message_buffer, services.event_bus, sid, extra_event=event)
            if not flushed:
                logger.warning(f"No pending messages to flush for session {sid}")
            return False
        return False
