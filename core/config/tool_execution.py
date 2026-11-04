from math import isfinite
from typing import TYPE_CHECKING

from core.agent.config import ToolExecutionConfig

if TYPE_CHECKING:
    from .config_loader import KiraConfig


def build_tool_execution_config(config: "KiraConfig") -> ToolExecutionConfig:
    """Translate application settings into an independent tool execution snapshot."""
    defaults = ToolExecutionConfig()
    # Keep the persisted key while naming the actual per-step limit explicitly.
    try:
        max_calls = max(0, int(config.get_config("bot_config.agent.max_tool_calls_per_turn")))
    except (TypeError, ValueError, OverflowError):
        max_calls = defaults.max_tool_calls_per_step

    raw_timeout = config.get_config("bot_config.agent.tool_call_timeout")
    try:
        timeout = float(raw_timeout)
        if not isfinite(timeout):
            timeout = defaults.tool_call_timeout
        elif timeout <= 0:
            timeout = None
    except (TypeError, ValueError, OverflowError):
        timeout = defaults.tool_call_timeout

    output_tokens = config.get_config(
        "bot_config.agent.max_tool_output_tokens", defaults.max_tool_output_tokens,
    )
    if not isinstance(output_tokens, int) or isinstance(output_tokens, bool) or output_tokens < 0:
        output_tokens = defaults.max_tool_output_tokens

    return ToolExecutionConfig(
        max_tool_calls_per_step=max_calls,
        tool_call_timeout=timeout,
        max_tool_output_tokens=output_tokens,
    )
