from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Literal, Any, List
from enum import Enum


class ParentContextStrategy(str, Enum):
    NONE = "none"
    SUMMARY = "summary"
    FULL = "full"
    SELECTIVE = "selective"


@dataclass
class SubAgentConfig:
    subagent_id: str
    name: str
    description: str
    persona: str = ""
    model_uuid: Optional[str] = None
    tools: list[str] = field(default_factory=list)
    max_steps: int = 3
    timeout: float = 60.0
    context_strategy: ParentContextStrategy = ParentContextStrategy.NONE
    lifecycle: Literal["session", "app_scope", "on_demand"] = "on_demand"
    max_tool_loop: int = 2
    extra: dict = field(default_factory=dict)


@dataclass
class SubAgentRequest:
    correlation_id: str
    task_type: str
    content: str
    metadata: dict = field(default_factory=dict)

    @property
    def parent_context_strategy(self) -> ParentContextStrategy:
        strategy = self.metadata.get("parent_context", "none")
        try:
            return ParentContextStrategy(strategy)
        except ValueError:
            return ParentContextStrategy.NONE

    @property
    def max_tokens(self) -> Optional[int]:
        return self.metadata.get("max_tokens")

    @property
    def allowed_tools(self) -> Optional[list[str]]:
        return self.metadata.get("tools")


@dataclass
class SubAgentResponse:
    correlation_id: str
    status: Literal["success", "timeout", "tool_error", "model_error", "cancelled"]
    result: str = ""
    attachments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    err: Optional[str] = None

    @property
    def time_consumed(self) -> Optional[float]:
        return self.metadata.get("time_consumed")

    @property
    def input_tokens(self) -> Optional[int]:
        return self.metadata.get("input_tokens")

    @property
    def output_tokens(self) -> Optional[int]:
        return self.metadata.get("output_tokens")
