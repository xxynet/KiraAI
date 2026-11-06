from __future__ import annotations

import json
from asyncio import TimeoutError as AsyncTimeoutError
from asyncio import wait_for
from collections.abc import Awaitable, Callable

from core.logging_manager import get_logger
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool

from .config import ToolExecutionConfig
from .tool import ToolResult, ToolSet, truncate_tool_output

logger = get_logger("llm", "purple")
tool_logger = get_logger("tool_use", "orange")


class ToolExecutor:
    """Execute supplied tools with per-call limits and result callbacks."""

    async def invoke_tool(self, tool: BaseTool, args: dict) -> object:
        """Invoke a tool using model-supplied keyword arguments."""
        return await tool.execute(**args)

    async def execute_tools(
        self,
        resp: LLMResponse,
        tool_set: ToolSet | None = None,
        *,
        config: ToolExecutionConfig,
        on_tool_result: Callable[[ToolResult], Awaitable[bool]] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """Execute an explicit tool set without a registry, events, or shared config.

        Override invoke_tool() to adapt tool arguments. A result callback may stop
        the batch by returning False.
        should_stop is checked before each tool; completed results are retained.
        """
        max_tool_calls = config.max_tool_calls_per_step
        tool_call_timeout = config.tool_call_timeout
        max_tool_output_tokens = config.max_tool_output_tokens

        for idx, tool_call in enumerate(resp.tool_calls):
            if should_stop is not None and should_stop():
                return
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
            except (json.JSONDecodeError, AttributeError) as e:
                logger.error(f"Failed to parse function calling arguments: {e}")
                logger.error(f"Raw args: {raw_args}")
                args = {}
            tool_logger.info(f"{name} args: {args}")

            # Call corresponding Python function(s)
            if tool_set and name in tool_set:
                try:
                    tool_inst = tool_set.get(name)
                    coro = self.invoke_tool(tool_inst, args)
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
