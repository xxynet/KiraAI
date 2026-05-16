"""call_subagent 工具：让主 Agent 能够调用已注册的子 Agent 来完成子任务。"""
from __future__ import annotations

import asyncio
from typing import Optional, TYPE_CHECKING

from core.utils.tool_utils import BaseTool
from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.subagent.client import SubAgentClient
    from core.subagent.registry import SubAgentRegistry

logger = get_logger("subagent", "magenta")


class CallSubAgentTool(BaseTool):
    name = "call_subagent"
    description = (
        "调用一个已注册的子Agent(subagent)来完成特定子任务。"
        "子Agent拥有独立的persona和工具集，能够自主完成分配的任务并返回结果。"
        "适用于需要专业能力（如代码审查、数据分析、翻译等）的子任务。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "subagent_id": {
                "type": "string",
                "description": "要调用的子Agent的ID，例如 'code_expert'",
            },
            "task": {
                "type": "string",
                "description": "需要子Agent完成的具体任务描述",
            },
            "context_summary": {
                "type": "string",
                "description": "可选，传给子Agent的上下文摘要，帮助子Agent理解当前对话背景",
            },
            "timeout": {
                "type": "number",
                "description": "可选，超时时间（秒），默认使用子Agent配置的timeout",
            },
        },
        "required": ["subagent_id", "task"],
    }

    def __init__(self, subagent_client: SubAgentClient, subagent_registry: SubAgentRegistry):
        super().__init__()
        self.subagent_client = subagent_client
        self.subagent_registry = subagent_registry

    async def execute(self, event, **kwargs) -> str:
        subagent_id = kwargs.get("subagent_id", "")
        task = kwargs.get("task", "")
        context_summary = kwargs.get("context_summary", "")
        timeout = kwargs.get("timeout")

        if not subagent_id or not task:
            return "Error: 'subagent_id' and 'task' are required parameters."

        # 检查子Agent是否已注册
        config = self.subagent_registry.get_config(subagent_id)
        if not config:
            available = list(self.subagent_registry.list_configs().keys())
            return (
                f"Error: SubAgent '{subagent_id}' is not registered. "
                f"Available subagents: {available}"
            )

        metadata = {}
        if context_summary:
            metadata["context_summary"] = context_summary
            metadata["parent_context"] = "summary"

        # 获取当前会话的 session_id，传递给子Agent以支持 session 生命周期
        session_id = None
        if hasattr(event, "sid"):
            session_id = event.sid

        try:
            result = await self.subagent_client.call(
                subagent_id=subagent_id,
                content=task,
                task_type="tool_invoked",
                session_id=session_id,
                metadata=metadata if metadata else None,
                timeout=timeout,
            )

            if result.status == "success":
                time_info = ""
                if result.time_consumed:
                    time_info = f" (耗时: {result.time_consumed}s)"
                token_info = ""
                if result.input_tokens and result.output_tokens:
                    token_info = f" [tokens: {result.input_tokens}in/{result.output_tokens}out]"
                return f"SubAgent '{subagent_id}' 完成任务{time_info}{token_info}:\n{result.result}"
            elif result.status == "timeout":
                return f"Error: SubAgent '{subagent_id}' 执行超时: {result.err}"
            else:
                return f"Error: SubAgent '{subagent_id}' 执行失败 ({result.status}): {result.err}"

        except asyncio.TimeoutError:
            return f"Error: SubAgent '{subagent_id}' 调用超时"
        except Exception as e:
            logger.error(f"call_subagent error: {e}")
            return f"Error: 调用子Agent失败 - {e}"
