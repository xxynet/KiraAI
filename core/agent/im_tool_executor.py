from __future__ import annotations

from typing import TYPE_CHECKING

from core.utils.tool_utils import BaseTool

from .tool_executor import ToolExecutor

if TYPE_CHECKING:
    from core.chat import KiraMessageBatchEvent


class IMToolExecutor(ToolExecutor):
    """Execute IM tools with the event bound to this executor."""

    def __init__(self, event: KiraMessageBatchEvent):
        self.event = event

    async def invoke_tool(self, tool: BaseTool, args: dict) -> object:
        return await tool.execute(self.event, **args)
