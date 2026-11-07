from dataclasses import dataclass, field
from math import isfinite
from typing import Any


@dataclass(frozen=True)
class ToolExecutionConfig:
    """Validated limits for one batch of model-requested tool calls."""

    max_tool_calls_per_step: int = 5
    tool_call_timeout: float | None = 60
    max_tool_output_tokens: int = 10000

    def __post_init__(self):
        for name in ("max_tool_calls_per_step", "max_tool_output_tokens"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")
        timeout = self.tool_call_timeout
        if timeout is not None and (
            not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not isfinite(timeout)
            or timeout <= 0
        ):
            raise ValueError("tool_call_timeout must be a finite positive number or None")


@dataclass(frozen=True)
class AgentExecutionConfig:
    """Settings captured for one complete agent loop."""

    max_steps: int = 5
    tool_config: ToolExecutionConfig = field(default_factory=ToolExecutionConfig)
    # None or an empty string disables the final-step prompt.
    final_step_hint: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not isinstance(self.max_steps, int) or isinstance(self.max_steps, bool) or self.max_steps < 0:
            raise ValueError("max_steps must be a non-negative integer")
        if not isinstance(self.tool_config, ToolExecutionConfig):
            raise TypeError("tool_config must be a ToolExecutionConfig")
        if self.final_step_hint is not None and not isinstance(self.final_step_hint, str):
            raise TypeError("final_step_hint must be a string or None")
