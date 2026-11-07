from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.utils.tool_utils import BaseTool

    from .base_agent_executor import BaseAgentExecutionContext
    from .tool import ToolResult


@dataclass
class ToolCallContext:
    """One resolved tool call before execution.

    Hooks may update arguments or call set_result() to skip execution. The
    supplied result still passes through result hooks and normal output handling.
    Agent executors supply agent_context; standalone ToolExecutor calls may omit
    it. event exposes the original event from agent_context when present.
    """

    tool_call_id: str
    tool: BaseTool
    arguments: dict[str, Any]
    agent_context: BaseAgentExecutionContext | None = None
    extra: dict[str, Any] = field(default_factory=dict)
    _result: ToolResult | None = field(default=None, init=False, repr=False)

    @property
    def event(self) -> Any:
        """Return the agent's original event, or None for event-free execution."""
        return getattr(self.agent_context, "event", None)

    @property
    def result(self) -> ToolResult | None:
        """Return the supplied result, or None when the tool should execute."""
        return self._result

    def set_result(self, result: ToolResult | str) -> None:
        """Supply a tool result and skip the actual tool invocation."""
        from .tool import ToolResult

        if not isinstance(result, (ToolResult, str)):
            raise TypeError("ToolCallContext.set_result() requires a ToolResult or str")

        if isinstance(result, str):
            self._result = ToolResult(text=result)
        else:
            self._result = result
