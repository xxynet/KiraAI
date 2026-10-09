from core.workflow.base_stage import BaseStage
from core.chat.message_utils import KiraFinalResult
from ..context import IMBatchContext
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg

logger = get_logger("message", "cyan")


class FinalizeStage(BaseStage[IMBatchContext]):
    """Dispatch the whole-turn result and save memory, including stopped turns."""

    async def run(self, ctx: IMBatchContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        turn_steps, new_messages = ctx.turn_steps, ctx.new_messages
        # EventType.ON_FINAL_RESULT
        # Fired once per turn, after the agent loop finished. Calling event.stop() here
        # cannot unsend already-delivered messages; it only suppresses the remaining handlers.
        final_result = KiraFinalResult(step_results=turn_steps)
        final_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_FINAL_RESULT)
        for handler in final_handlers:
            await handler.exec_handler(event, final_result)
            if event.is_stopped:
                logger.info(f"Event {event.event_id} stopped while ON_FINAL_RESULT stage")
                break

        # Save new memory
        services.session_manager.update_memory(sid, new_messages)
        return True
