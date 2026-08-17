from __future__ import annotations

from asyncio import wait_for, TimeoutError as AsyncTimeoutError
from typing import Optional, Union, TYPE_CHECKING
import copy
import json
import time

from core.logging_manager import get_logger
from core.config import KiraConfig
from core.provider import LLMRequest, LLMResponse
from .tool import ToolResult, ToolSet
from core.utils.tool_utils import BaseTool

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
    def __init__(self, kira_config: KiraConfig):
        self.kira_config = kira_config

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

    async def execute_tool(self, event: KiraMessageBatchEvent, resp: LLMResponse, tool_set: Optional[ToolSet] = None):
        max_tool_calls_per_turn = self.kira_config.get_config("bot_config.agent.max_tool_calls_per_turn")
        try:
            max_tool_calls_per_turn = int(max_tool_calls_per_turn)
        except (TypeError, ValueError):
            max_tool_calls_per_turn = 5

        tool_call_timeout = self.kira_config.get_config("bot_config.agent.tool_call_timeout")
        try:
            tool_call_timeout = float(tool_call_timeout)
            if tool_call_timeout <= 0:
                tool_call_timeout = None
        except (TypeError, ValueError):
            tool_call_timeout = 60

        for idx, tool_call in enumerate(resp.tool_calls):
            tool_call_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")

            # Exceeds per-turn tool call limit
            if idx >= max_tool_calls_per_turn:
                warn_msg = f"Tool call limit exceeded: maximum {max_tool_calls_per_turn} tool calls per turn, skipping tool '{name}'."
                tool_logger.warning(warn_msg)
                resp.tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": warn_msg
                })
                continue

            # Some providers omit "arguments" entirely for no-arg tool calls
            raw_args = tool_call.get("function", {}).get("arguments")
            if isinstance(raw_args, str):
                raw_args = raw_args.strip()
            try:
                if not raw_args:
                    args = {}
                else:
                    args = json.loads(raw_args)
            except (TypeError, ValueError) as e:
                logger.error(f"Failed to parse function calling arguments: {e}")
                logger.error(f"Raw args: {raw_args}")
                args = {}
            tool_logger.info(f"{name} args: {args}")

            # Call corresponding Python function(s)
            if tool_set and name in tool_set:
                try:
                    tool_inst = tool_set.get(name)
                    coro = tool_inst.execute(event, **args)
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

            from core.plugin.plugin_handlers import event_handler_reg, EventType

            # EventType.ON_TOOL_RESULT
            llm_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_RESULT)
            for handler in llm_handlers:
                await handler.exec_handler(event, tool_result_obj)
                if event.is_stopped:
                    logger.info("Event stopped while ON_TOOL_RESULT stage")
                    return

            # Save tool results
            content = await tool_result_obj.assemble_result()
            tool_logger.info(f"tool_result: {content}")
            resp.tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content
            })
