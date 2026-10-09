from core.workflow.base_stage import BaseStage
import time

from core.agent.agent_executor import AgentExecutor, AgentExecutionContext
from core.agent.message import OpenAIMessage
from core.chat.message_utils import KiraStepResult
from core.provider import LLMResponse
from ..context import IMBatchContext
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg

logger = get_logger("message", "cyan")


class ExecuteAgentStage(BaseStage[IMBatchContext]):
    """Run agent steps, deliver replies, and dispatch per-step results."""

    async def run(self, ctx: IMBatchContext) -> bool:
        services, event, sid = ctx.services, ctx.event, ctx.sid
        request, tag_set = ctx.request, ctx.tag_set
        if request is None:
            raise RuntimeError("BuildRequestStage must run before this stage")
        new_messages, model_group = ctx.new_messages, ctx.model_group
        # Get max tool loop config, defaults to 2 if not a valid integer
        # Note: This variable represents the total agent loop iterations (not just tool calls),
        # but the name is kept as-is for backward compatibility with existing config files.
        max_tool_loop = services.config.get_config("bot_config.agent.max_tool_loop", 2)
        try:
            max_tool_loop = int(max_tool_loop)
        except (TypeError, ValueError):
            max_tool_loop = 2

        max_agent_steps = max_tool_loop

        agent_executor = AgentExecutor(services.tool_manager, request.tool_set)
        agent_ctx = AgentExecutionContext(
            event=event,
            request=request,
            new_messages=new_messages,
            model_group=model_group,
        )

        # Accumulates per-step results so ON_FINAL_RESULT can report the whole turn
        turn_steps = ctx.turn_steps

        async def send_llm_text(resp: LLMResponse, memory_message: OpenAIMessage | None) -> bool:
            """Process and send LLM text response. Returns False if stopped, True to continue."""
            text = resp.text_response
            message_results = []
            raw_output = ""
            if text:
                session_lock = services.message_delivery.get_session_lock(sid)
                async with session_lock:
                    message_results = await services.message_delivery.send_xml_messages(event, text.strip(), tag_set, memory_message=memory_message)
                    if message_results is None:
                        return False
                    raw_output = services.message_delivery.add_message_ids(text, message_results)
                    logger.info(f"LLM -> {sid}: {raw_output}")
            step_result = KiraStepResult(message_results=message_results, raw_output=raw_output)
            # Record the step before dispatching, so ON_FINAL_RESULT still sees messages
            # that were already sent even if a handler stops the turn below.
            turn_steps.append(step_result)
            # EventType.ON_STEP_RESULT
            step_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_STEP_RESULT)
            for step_handler in step_handlers:
                await step_handler.exec_handler(event, step_result)
                if event.is_stopped:
                    logger.info(f"Event {event.event_id} stopped while ON_STEP_RESULT stage")
                    return False
            if raw_output:
                resp.text_response = step_result.raw_output
                for idx in range(-1, -len(new_messages), -1):
                    if new_messages[idx].role == "assistant":
                        new_messages[idx].content = step_result.raw_output
                        request.messages[idx].content = step_result.raw_output
                        break
            return True

        # Iter agent executor to get LLMResponse
        # TODO use llm_semaphore to restrict concurrent LLM requests
        async for step in agent_executor.run(agent_ctx, max_steps=max_agent_steps):
            llm_resp = step.llm_response
            if not llm_resp:
                break

            # Record LLM usage telemetry per step
            try:
                await services.db.add_telemetry_llm_usage(
                    timestamp=int(time.time()),
                    model=step.model_name,
                    input_tokens=llm_resp.input_tokens or 0,
                    output_tokens=llm_resp.output_tokens or 0,
                    cached_tokens=llm_resp.cached_tokens,
                    response_time_ms=int((llm_resp.time_consumed or 0) * 1000),
                    success=(step.state != "error"),
                )
            except Exception as e:
                logger.debug(f"Failed to record telemetry LLM usage: {e}")

            if not await send_llm_text(llm_resp, step.assistant_message):
                break

            if not step.has_tool_calls or step.is_final:
                break

            # Process tool calls if existed

        # Finalization must still run when a result handler stops the event.
        return True
