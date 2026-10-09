from core.workflow.base_stage import BaseStage
from core.agent.message import OpenAIMessage
from core.prompt_manager import Prompt
from core.tag import tag_registry
from ..context import IMBatchContext
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg

logger = get_logger("message", "cyan")


class AssembleRequestStage(BaseStage[IMBatchContext]):
    """Apply request plugins, render tags, and link persistent user memory."""

    async def run(self, ctx: IMBatchContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        request, tag_set = ctx.request, ctx.tag_set
        if request is None:
            raise RuntimeError("BuildRequestStage must run before this stage")
        image_mode, incoming_record_ids = ctx.image_mode, ctx.incoming_record_ids
        # EventType.ON_LLM_REQUEST
        llm_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_LLM_REQUEST)
        for handler in llm_handlers:
            await handler.exec_handler(event, request, tag_set)
            if event.is_stopped:
                logger.info(f"Event {event.event_id} stopped while llm request stage")
                return False

        # Register persistent tags registered by user plugins
        tag_set.register(*tag_registry.get_all())
        tag_set.register(*tag_registry.get_all_root())

        # Assemble messages
        root_prompt = tag_set.to_root_prompt()
        for sp in request.system_prompt:
            if sp.name == "format":
                sp.kwargs["message_types"] = tag_set.to_prompt()
                sp.kwargs["root_tags"] = (
                    f"此外，你可以在<msg>标签外使用以下控制标签（与<msg>同级）：\n{root_prompt}"
                    if root_prompt else ""
                )
                break
        request.assemble_prompt(
            dynamic_position=services.config.get_config(
                "bot_config.bot.dynamic_prompt_position", "latest_user"
            ),
            memory_position=services.config.get_config(
                "bot_config.bot.memory_prompt_position", "latest_user"
            ),
        )

        if image_mode == "native":
            for message in event.messages:
                message.native_content = await services.message_media.build_native_content(message, sid)

        native_parts = [
            part
            for message in event.messages
            for part in (message.native_content or [])[1:]
        ]
        if native_parts and request.messages and request.messages[-1].role == "user":
            request.messages[-1].content = [
                {"type": "text", "text": request.messages[-1].content or ""},
                *native_parts,
            ]

        # Re-derive tools list after plugins may have added to tool_set
        request.tools = request.tool_set.to_list()
        # Recompute tool_choice if it was auto-derived (not explicitly set by a plugin)
        if request.tool_choice in ("auto", "none"):
            request.tool_choice = "auto" if request.tools else "none"

        # Print user message info (skip persist=False prompts to avoid log spam)
        user_message = "".join(p.to_string() for p in request.user_prompt if isinstance(p, Prompt) and p.persist)
        logger.info(f"processing message(s) from {sid}:\n{user_message}")

        # 把收到的消息放到新收到的消息内容中（仅持久化 persist=True 的 Prompt）
        persist_message = "".join(p.to_string() for p in request.user_prompt if isinstance(p, Prompt) and p.persist)
        persisted_native_parts = [
            part
            for message in event.messages
            for part in (message.native_content or [])[1:]
        ]
        persisted_content: str | list[dict] = persist_message
        if persisted_native_parts:
            persisted_content = [
                {"type": "text", "text": persist_message},
                *persisted_native_parts,
            ]
        new_messages = ctx.new_messages
        user_memory = OpenAIMessage(role="user", content=persisted_content)
        user_memory.to_memory_dict()
        history = services.message_history
        if history is not None:
            try:
                await history.link_incoming_messages(sid, user_memory.extra["llm_message_id"], [
                    record_id for message in event.messages
                    if (record_id := incoming_record_ids.get(id(message)))
                ])
            except Exception as exc:
                logger.error("Unable to link incoming messages (%s)", type(exc).__name__)
        new_messages.append(user_memory)
        return True
