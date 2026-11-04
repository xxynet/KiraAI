from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from core.logging_manager import get_logger
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool

from .config import ToolExecutionConfig
from .tool import ToolResult, ToolSet
from .tool_executor import ToolExecutor

logger = get_logger("llm", "purple")

if TYPE_CHECKING:
    from core.chat import KiraMessageBatchEvent


class _LegacyFuncTool(BaseTool):
    """Wraps a legacy (name, description, parameters, func) quadruple as a BaseTool."""

    def __init__(self, name: str, description: str, parameters: dict, func):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._func = func

    async def execute(self, *args, **kwargs):
        return await self._func(*args, **kwargs)

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class FuncToolManager:
    def __init__(self, config: ToolExecutionConfig | None = None):
        self.config = config if config is not None else ToolExecutionConfig()

        self.tool_set = ToolSet()
        self.tool_executor = ToolExecutor()

    def register_tool(self, name, description, parameters, func):
        """Register a tool"""
        self.tool_set.add(_LegacyFuncTool(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        ))

    def unregister_tool(self, name: str):
        self.tool_set.remove(name)

    def build_tool_set(self) -> ToolSet:
        """Return a request-local copy of the registered tools."""
        return ToolSet(tools=self.tool_set.tools.copy())

    async def execute_tool(
        self,
        event: KiraMessageBatchEvent,
        resp: LLMResponse,
        tool_set: ToolSet | None = None,
        *,
        config: ToolExecutionConfig | None = None,
    ):
        """Execute IM tools and dispatch the existing event-bound result hooks."""
        from core.plugin.handlers import EventType, event_handler_reg

        async def invoke_tool(tool: BaseTool, args: dict) -> object:
            return await tool.execute(event, **args)

        async def on_tool_result(result: ToolResult) -> bool:
            for handler in event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_RESULT):
                await handler.exec_handler(event, result)
                if event.is_stopped:
                    logger.info("Event stopped while ON_TOOL_RESULT stage")
                    return False
            return True

        await self.execute_tools(
            resp, tool_set, config=config, invoke_tool=invoke_tool, on_tool_result=on_tool_result,
        )

    async def execute_tools(
        self,
        resp: LLMResponse,
        tool_set: ToolSet | None = None,
        *,
        config: ToolExecutionConfig | None = None,
        invoke_tool: Callable[[BaseTool, dict], Awaitable[object]] | None = None,
        on_tool_result: Callable[[ToolResult], Awaitable[bool]] | None = None,
    ) -> None:
        """Execute an explicit tool set without requiring events or plugin hooks.

        By default tools receive only model-supplied keyword arguments. Integrations
        may supply invocation and result callbacks; returning False from the result
        callback stops the batch before the current result is recorded.
        """
        await self.tool_executor.execute_tools(
            resp, tool_set, config=config if config is not None else self.config,
            invoke_tool=invoke_tool, on_tool_result=on_tool_result,
        )
