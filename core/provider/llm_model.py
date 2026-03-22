from __future__ import annotations

from typing import Optional, Callable, Literal
from dataclasses import dataclass, field

from core.agent.tool import ToolSet
from core.prompt_manager import Prompt


@dataclass
class LLMRequest:
    messages: list = field(default_factory=list)
    user_prompt: list[Prompt] = field(default_factory=list)
    system_prompt: list[Prompt] = field(default_factory=list)
    tools: Optional[list[dict]] = None
    tool_funcs: Optional[dict[str, Callable]] = None
    tool_set: Optional[ToolSet] = None
    tool_choice: Optional[Literal["auto", "none", "required"]] = None

    def __post_init__(self):
        if not self.tool_choice:
            self.tool_choice = "auto" if self.tools else "none"

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
    text_response: str
    reasoning_content: str = ""
    agent_step_index: Optional[int] = None
    tool_calls: list[dict] = field(default_factory=list)
    tool_results: list[dict] = field(default_factory=list)
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    time_consumed: Optional[float] = None

    def __post_init__(self):
        if self.reasoning_content is None:
            self.reasoning_content = ""
