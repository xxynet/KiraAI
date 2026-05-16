"""create_subagent 工具：让主 Agent 能够动态创建新的子 Agent。"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from core.utils.tool_utils import BaseTool
from core.logging_manager import get_logger
from core.subagent.models import SubAgentConfig

if TYPE_CHECKING:
    from core.subagent.registry import SubAgentRegistry

logger = get_logger("subagent", "magenta")


class CreateSubAgentTool(BaseTool):
    name = "create_subagent"
    description = (
        "动态创建一个新的子Agent(subagent)。"
        "你可以为子Agent指定专属的persona（角色设定）、可用工具列表、模型等。"
        "创建成功后，可以通过 call_subagent 工具调用它。"
        "适用于需要分工协作的复杂任务场景。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "subagent_id": {
                "type": "string",
                "description": "子Agent的唯一ID，只能包含字母、数字和下划线，例如 'translator'",
            },
            "name": {
                "type": "string",
                "description": "子Agent的显示名称，例如 '翻译专家'",
            },
            "description": {
                "type": "string",
                "description": "子Agent的功能描述",
            },
            "persona": {
                "type": "string",
                "description": "子Agent的角色设定/persona，定义其专业能力和行为准则",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "子Agent可以使用的工具列表，例如 ['read_file', 'write_file']。不指定则无工具。",
            },
            "model_uuid": {
                "type": "string",
                "description": "可选，指定子Agent使用的模型，格式为 'provider_id:model_id'。不指定则使用默认模型。",
            },
            "max_steps": {
                "type": "integer",
                "description": "可选，子Agent最大执行步数，默认3",
            },
            "timeout": {
                "type": "number",
                "description": "可选，子Agent执行超时时间（秒），默认60",
            },
            "lifecycle": {
                "type": "string",
                "enum": ["on_demand", "session", "app_scope"],
                "description": "可选，子Agent生命周期: 'on_demand'每次创建新实例(默认), 'session'会话内复用, 'app_scope'全局复用",
            },
        },
        "required": ["subagent_id", "name", "persona"],
    }

    def __init__(self, subagent_registry: SubAgentRegistry, available_tools: list[str] = None):
        super().__init__()
        self.subagent_registry = subagent_registry
        self._available_tools = available_tools or []

    async def execute(self, event, **kwargs) -> str:
        subagent_id = kwargs.get("subagent_id", "")
        name = kwargs.get("name", "")
        persona = kwargs.get("persona", "")
        description = kwargs.get("description", "")
        tools = kwargs.get("tools", [])
        model_uuid = kwargs.get("model_uuid")
        max_steps = kwargs.get("max_steps", 3)
        timeout = kwargs.get("timeout", 60.0)
        lifecycle = kwargs.get("lifecycle", "on_demand")

        if not subagent_id or not name or not persona:
            return "Error: 'subagent_id', 'name', and 'persona' are required parameters."

        # 验证 subagent_id 格式
        if not subagent_id.replace("_", "").isalnum():
            return "Error: 'subagent_id' can only contain letters, numbers, and underscores."

        # 检查是否已存在
        existing = self.subagent_registry.get_config(subagent_id)
        if existing:
            return (
                f"Error: SubAgent '{subagent_id}' already exists. "
                f"Use a different ID or call the existing one with call_subagent."
            )

        # 过滤无效工具
        valid_tools = []
        if tools:
            for tool_name in tools:
                if tool_name in self._available_tools:
                    valid_tools.append(tool_name)
                else:
                    logger.warning(f"Tool '{tool_name}' not available, skipping for subagent '{subagent_id}'")

        # 限制 AI 创建的子Agent的最大步数和超时，防止资源滥用
        max_steps = min(max_steps, 10)
        timeout = min(timeout, 300.0)

        # 验证 lifecycle
        if lifecycle not in ("on_demand", "session", "app_scope"):
            lifecycle = "on_demand"

        config = SubAgentConfig(
            subagent_id=subagent_id,
            name=name,
            description=description or f"AI-created subagent: {name}",
            persona=persona,
            model_uuid=model_uuid,
            tools=valid_tools,
            max_steps=max_steps,
            timeout=timeout,
            context_strategy="summary",  # AI 创建的子Agent默认使用 summary 策略
            lifecycle=lifecycle,
            max_tool_loop=min(max_steps - 1, 5) if max_steps > 1 else 1,
        )

        # AI 创建的子Agent不持久化到配置文件（persist=False），仅在运行时存在
        success = self.subagent_registry.register(config, persist=False)
        if success:
            return (
                f"SubAgent '{subagent_id}' ({name}) 创建成功！\n"
                f"描述: {description or '无'}\n"
                f"可用工具: {valid_tools if valid_tools else '无'}\n"
                f"生命周期: {lifecycle}\n"
                f"你可以通过 call_subagent(subagent_id='{subagent_id}', task='...') 来调用它。"
            )
        else:
            return f"Error: Failed to register SubAgent '{subagent_id}'."
