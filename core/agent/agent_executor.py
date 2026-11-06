from __future__ import annotations

import traceback
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.chat.message_utils import KiraExceptionEvent
from core.logging_manager import get_logger
from core.plugin.handlers import EventType, event_handler_reg
from core.provider import LLMModelClient, LLMRequest, LLMResponse

from .base_agent_executor import (
    AgentStepResult,
    BaseAgentExecutionContext,
    BaseAgentExecutor,
)
from .config import AgentExecutionConfig
from .hook_context import ToolCallContext
from .hooks import AgentExecutionHooks
from .im_tool_executor import IMToolExecutor
from .tool import ToolResult
from .tool_executor import ToolExecutor

if TYPE_CHECKING:
    from core.chat.message_utils import KiraMessageBatchEvent


__all__ = ["AgentExecutionContext", "AgentExecutor", "AgentStepResult", "IMAgentExecutionHooks"]


logger = get_logger("agent_executor", "cyan")


@dataclass(kw_only=True)
class AgentExecutionContext(BaseAgentExecutionContext):
    """Conversation state with the IM event for this foreground turn."""

    event: KiraMessageBatchEvent


class IMAgentExecutionHooks(AgentExecutionHooks[AgentExecutionContext]):
    """Dispatch IM plugin events during agent execution."""

    async def on_tool_call(self, ctx: ToolCallContext) -> None:
        for handler in event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_CALL):
            await handler.exec_handler(ctx)
            if ctx.result is not None:
                return

    async def on_llm_response(self, ctx: AgentExecutionContext, response: LLMResponse) -> bool:
        for handler in event_handler_reg.get_handlers(event_type=EventType.ON_LLM_RESPONSE):
            await handler.exec_handler(ctx.event, response)
            if ctx.event.is_stopped:
                logger.info("Event stopped")
                return True
        return False

    async def on_exception(
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

    async def on_tool_result(self, ctx: AgentExecutionContext, result: ToolResult) -> bool:
        for handler in event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_RESULT):
            await handler.exec_handler(ctx.event, result)
            if ctx.event.is_stopped:
                logger.info("Event stopped while ON_TOOL_RESULT stage")
                return False
        return True


class AgentExecutor(BaseAgentExecutor[AgentExecutionContext]):
    """Integrate agent execution with IM tools and plugin event hooks."""

    def __init__(
        self,
        model_group: list[LLMModelClient],
        *,
        context: AgentExecutionContext,
        request: LLMRequest | None = None,
        hooks: AgentExecutionHooks[AgentExecutionContext] | None = None,
        tool_executor: ToolExecutor | None = None,
        config: AgentExecutionConfig | None = None,
        on_result: Callable[[AgentStepResult], Awaitable[None]] | None = None,
    ):
        super().__init__(
            model_group, context=context, request=request,
            hooks=hooks if hooks is not None else IMAgentExecutionHooks(),
            tool_executor=tool_executor if tool_executor is not None else IMToolExecutor(context.event),
            config=config, on_result=on_result,
        )
