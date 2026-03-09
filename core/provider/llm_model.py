from __future__ import annotations

from typing import Optional, Callable, Literal
from dataclasses import dataclass, field

from core.agent.tool import ToolSet
from core.prompt_manager import Prompt


@dataclass
class LLMRequest:
    """LLMRequest object"""

    """message list provided to llm provider"""
    messages: list = field(default_factory=list)

    """Latest user prompt"""
    user_prompt: list[Prompt] = field(default_factory=list)

    """System prompt"""
    system_prompt: list[Prompt] = field(default_factory=list)

    """optional: tool definitions for llm to call"""
    tools: Optional[list[dict]] = None

    """optional: tool functions"""
    tool_funcs: Optional[dict[str, Callable]] = None

    """tool set object"""
    tool_set: Optional[ToolSet] = None

    """controls llm behavior of tool calling"""
    tool_choice: Optional[Literal["auto", "none", "required"]] = None

    def __post_init__(self):
        if not self.tool_choice:
            if self.tools:
                self.tool_choice = "auto"
            else:
                self.tool_choice = "none"

    def assemble_prompt(self):
        if self.system_prompt:
            if self.messages and self.messages[0].get("role") == "system":
                self.messages.pop(0)
            system_prompt = "".join(p.to_string() for p in self.system_prompt if isinstance(p, Prompt))
            self.messages.insert(0, {"role": "system", "content": system_prompt})

        if self.user_prompt:
            user_prompt = "".join(p.to_string() for p in self.user_prompt if isinstance(p, Prompt))
            self.messages.append({"role": "user", "content": user_prompt})


@dataclass
class LLMResponse:
    """Content field in chat completion response"""
    text_response: str

    """reasoning content for reasoning models"""
    reasoning_content: Optional[str] = None

    """agent step index"""
    agent_step_index: Optional[int] = None

    """Tool call requests in OpenAI format"""
    tool_calls: list[dict] = field(default_factory=list)

    """Tool results list in OpenAI format, including role assistant & tool"""
    tool_results: list[dict] = field(default_factory=list)

    input_tokens: Optional[int] = None

    output_tokens: Optional[int] = None

    """Units: seconds"""
    time_consumed: Optional[float] = None
