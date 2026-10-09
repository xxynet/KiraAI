from core.workflow.base_stage import BaseStage
from core.utils.image_compression import compress_image_element
from ..context import IMBatchContext
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg

logger = get_logger("message", "cyan")


class PrepareBatchStage(BaseStage[IMBatchContext]):
    """Archive and normalize incoming messages before batch plugins run."""

    async def run(self, ctx: IMBatchContext) -> bool:
        # Start processing
        services, event, sid = ctx.services, ctx.event, ctx.sid
        compression_config = services.config.get_config(
            "bot_config.image_compression", {}
        )
        global_capabilities = services.config.get_config("bot_config.capabilities", {})
        if not isinstance(global_capabilities, dict):
            global_capabilities = {}
        capabilities = services.session_manager.get_effective_capabilities(
            sid, global_capabilities
        ) if services.session_manager is not None else global_capabilities
        if not isinstance(capabilities, dict):
            capabilities = global_capabilities
        image_recognition = capabilities.get("image_recognition", {})
        image_mode = image_recognition.get(
            "mode", services.config.get_config("bot_config.capabilities.image_recognition.mode", "vlm_description")
        ) if isinstance(image_recognition, dict) else "vlm_description"

        incoming_record_ids = ctx.incoming_record_ids
        for message in event.messages:
            incoming_record_ids[id(message)] = (
                await services.message_history.record_incoming_safely(message, sid, event.adapter.platform)
                if services.message_history is not None else None
            )
            for image in services.message_media.iter_images(message.chain):
                await compress_image_element(image, compression_config)
            message_str = await services.message_formatter.format_to_text(message.chain, sid, capabilities)
            message.message_str = message_str

        # EventType.ON_IM_BATCH_MESSAGE
        im_batch_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_IM_BATCH_MESSAGE)
        for handler in im_batch_handlers:
            await handler.exec_handler(event)
            if event.is_stopped:
                logger.info(f"[ON_IM_BATCH_MESSAGE] Event {event.event_id} stopped")
                return False
        ctx.image_mode = image_mode
        return True
