from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.agent.message import OpenAIMessage
from core.chat.message_utils import KiraExceptionEvent
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg
from core.provider import LLMModelClient, LLMRequest, LLMResponse
from core.utils.tool_utils import BaseTool

from .base_agent_executor import (
    AgentStepResult,
    BaseAgentExecutionContext,
    BaseAgentExecutor,
)
from .tool import ToolResult

if TYPE_CHECKING:
    from core.chat.message_utils import KiraMessageBatchEvent


__all__ = ["AgentExecutionContext", "AgentExecutor", "AgentStepResult"]


logger = get_logger("agent_executor", "cyan")


@dataclass(init=False)
class AgentExecutionContext(BaseAgentExecutionContext):
    """Bind an independent agent run to an IM event."""

    event: KiraMessageBatchEvent

    def __init__(
        self, event: KiraMessageBatchEvent, request: LLMRequest,
        new_messages: list[OpenAIMessage], model_group: list[LLMModelClient],
    ):
        super().__init__(request=request, new_messages=new_messages, model_group=model_group)
        self.event = event


class AgentExecutor(BaseAgentExecutor[AgentExecutionContext]):
    """Integrate the shared agent loop with IM tools and plugin event hooks."""

    def _get_log_id(self, ctx: AgentExecutionContext) -> str:
        return ctx.event.sid

    def _get_final_step_hint(self) -> str:
        return "<system_reminder>This is the final model call for this turn. Conclude this turn now; do not start further work that depends on tool results. Any tool result will not invoke you again this turn and will only be available the next time you are invoked. If you need to communicate anything to the user, provide it in this response, using the information already available. If a user-facing answer is needed but information is insufficient, clearly state what is missing and give the user a concise next step. You may end silently with <msg/> when no user-facing response is needed.</system_reminder>"

    async def _on_llm_response(self, ctx: AgentExecutionContext, response: LLMResponse) -> bool:
        for handler in event_handler_reg.get_handlers(event_type=EventType.ON_LLM_RESPONSE):
            await handler.exec_handler(ctx.event, response)
            if ctx.event.is_stopped:
                logger.info("Event stopped")
                return True
        return False

    async def _on_exception(
        self, ctx: AgentExecutionContext, exception: Exception, *, source: str, comp_id: str | None,
    ) -> None:
        exc_event = KiraExceptionEvent(
            name=type(exception).__name__,
            message=str(exception),
            traceback=traceback.format_exc(),
            stage="agent_loop",
            source=source,
            comp_id=comp_id,
            e=exception,
        )
        for handler in event_handler_reg.get_handlers(EventType.ON_EXCEPTION):
            try:
                await handler.handler(ctx.event, exc_event)
            except Exception:
                logger.error(traceback.format_exc())

    async def _invoke_tool(self, ctx: AgentExecutionContext, tool: BaseTool, args: dict) -> object:
        return await tool.execute(ctx.event, **args)

    async def _on_tool_result(self, ctx: AgentExecutionContext, result: ToolResult) -> bool:
        for handler in event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_RESULT):
            await handler.exec_handler(ctx.event, result)
            if ctx.event.is_stopped:
                logger.info("Event stopped while ON_TOOL_RESULT stage")
                return False
        return True
