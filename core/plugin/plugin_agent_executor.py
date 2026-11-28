from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from core.agent.base_agent_executor import (
    AgentStepResult,
    BaseAgentExecutionContext,
    BaseAgentExecutor,
)
from core.agent.config import AgentExecutionConfig
from core.agent.hooks import AgentExecutionHooks
from core.agent.tool import ToolSet
from core.agent.tool_executor import ToolExecutor
from core.provider import LLMModelClient, LLMRequest
from core.utils.tool_utils import BaseTool


class PluginAgentExecutor(BaseAgentExecutor[BaseAgentExecutionContext]):
    """Initialize an independent agent with optional plugin tools and history."""

    def __init__(
        self,
        model_group: list[LLMModelClient],
        *,
        tools: Sequence[BaseTool] | ToolSet | None = None,
        context: BaseAgentExecutionContext | None = None,
        request: LLMRequest | None = None,
        hooks: AgentExecutionHooks[BaseAgentExecutionContext] | None = None,
        tool_executor: ToolExecutor | None = None,
        config: AgentExecutionConfig | None = None,
        on_result: Callable[[AgentStepResult], Awaitable[None]] | None = None,
    ) -> None:
        if tools is not None:
            if request is not None:
                raise ValueError(
                    "Pass either tools or request; use request.tool_set with a custom request"
                )
            tool_instances = tools.tools if isinstance(tools, ToolSet) else tools
            request = LLMRequest(tool_set=ToolSet(list(tool_instances)))
        super().__init__(
            model_group,
            context=context if context is not None else BaseAgentExecutionContext(),
            request=request,
            hooks=hooks,
            tool_executor=tool_executor,
            config=config,
            on_result=on_result,
        )
