from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from core.agent.hook_context import ToolCallContext
from core.agent.tool import ToolResult
from core.provider import LLMRequest, LLMResponse

if TYPE_CHECKING:
    from .base_agent_executor import BaseAgentExecutionContext


ContextT = TypeVar("ContextT", bound="BaseAgentExecutionContext")


class AgentExecutionHooks(Generic[ContextT]):
    """Customize agent execution without subclassing the executor."""

    async def on_llm_request(self, ctx: ContextT, request: LLMRequest) -> None:
        """Refresh request inputs before each model call, including provider failover."""

    async def on_tool_call(self, ctx: ToolCallContext) -> None:
        """Call ctx.set_result() to skip execution, or await approval before returning."""

    async def on_llm_response(self, ctx: ContextT, response: LLMResponse) -> bool:
        """Return True to stop before adding the response to message history."""
        return False

    async def on_exception(
        self, ctx: ContextT, exception: Exception, *, source: str, comp_id: str | None,
    ) -> None:
        """Report an execution failure; provider failover and propagation stay unchanged."""

    async def on_tool_result(self, ctx: ContextT, result: ToolResult) -> bool:
        """Return False to stop the batch before recording this tool result."""
        return True
