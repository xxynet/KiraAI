from __future__ import annotations

import json
from asyncio import TimeoutError as AsyncTimeoutError
from asyncio import wait_for
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from core.logging_manager import get_logger
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool

from .config import ToolExecutionConfig
from .tool import ToolResult, ToolSet, truncate_tool_output

logger = get_logger("llm", "purple")
tool_logger = get_logger("tool_use", "orange")

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
        effective_config = config if config is not None else self.config
        max_tool_calls = effective_config.max_tool_calls_per_step
        tool_call_timeout = effective_config.tool_call_timeout
        max_tool_output_tokens = effective_config.max_tool_output_tokens

        for idx, tool_call in enumerate(resp.tool_calls):
            tool_call_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")

            # Exceeds the tool call limit for this model response
            if idx >= max_tool_calls:
                warn_msg = f"Tool call limit exceeded: maximum {max_tool_calls} tool calls per turn, skipping tool '{name}'."
                tool_logger.warning(warn_msg)
                resp.tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": truncate_tool_output(warn_msg, max_tool_output_tokens)
                })
                continue

            raw_args = tool_call.get("function", {}).get("arguments")
            try:
                if not raw_args.strip():
                    args = {}
                else:
                    args = json.loads(raw_args)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse function calling arguments: {e}")
                logger.error(f"Raw args: {raw_args}")
                args = {}
            tool_logger.info(f"{name} args: {args}")

            # Call corresponding Python function(s)
            if tool_set and name in tool_set:
                try:
                    tool_inst = tool_set.get(name)
                    coro = invoke_tool(tool_inst, args) if invoke_tool else tool_inst.execute(**args)
                    result = await (wait_for(coro, tool_call_timeout) if tool_call_timeout else coro)
                except AsyncTimeoutError:
                    result = {"error": f"Tool '{name}' timed out after {tool_call_timeout}s"}
                    tool_logger.error(f"Tool '{name}' timed out after {tool_call_timeout}s")
                except Exception as e:
                    result = {"error": f"Failed to call tool '{name}': {e}"}
                    tool_logger.error(f"Failed to call tool '{name}': {e}")
            else:
                result = {"error": f"Tool {name} not implemented"}
                tool_logger.error(f"Tool {name} not implemented")

            if isinstance(result, ToolResult):
                tool_result_obj = result
            else:
                tool_result_obj = ToolResult(str(result))

            if on_tool_result is not None and not await on_tool_result(tool_result_obj):
                return

            # Save tool results
            content = await tool_result_obj.assemble_result()
            content = truncate_tool_output(content, max_tool_output_tokens)
            content = tool_result_obj.build_content(content)
            tool_logger.info(f"tool_result: {content}")
            resp.tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content
            })
