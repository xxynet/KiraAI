from abc import abstractmethod, ABC
from enum import Enum, auto
from typing import Optional, Callable, Literal
import asyncio
from dataclasses import dataclass, field


class LLMClientType(Enum):
    OPENAI = auto()
    ANTHROPIC = auto()
    GEMINI = auto()


@dataclass
class LLMModel:
    """provider id of the model"""
    provider_id: str

    """model name displayed on UI"""
    model_name: str

    """whether the model has vision capability"""
    has_vision: bool = False

    """whether the model support function calling"""
    tool_call: bool = False


@dataclass
class LLMRequest:
    """message list provided to llm provider"""
    messages: list = field(default_factory=list)

    """optional: tool definitions for llm to call"""
    tools: Optional[list[dict]] = None

    """optional: tool functions"""
    tool_funcs: Optional[dict[str, Callable]] = None

    """controls llm behavior of tool calling"""
    tool_choice: Optional[Literal["auto", "none", "required"]] = None

    def __post_init__(self):
        if not self.tool_choice:
            if self.tools:
                self.tool_choice = "auto"
            else:
                self.tool_choice = "none"


@dataclass
class LLMResponse:
    """Content field in chat completion response"""
    text_response: str

    """reasoning content for reasoning models"""
    reasoning_content: Optional[str] = None

    """Tool results list in OpenAI format, including role assistant & tool"""
    tool_results: list = field(default_factory=list)

    input_tokens: Optional[int] = None

    output_tokens: Optional[int] = None

    """Units: seconds"""
    time_consumed: Optional[float] = None
