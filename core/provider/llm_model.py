from abc import abstractmethod, ABC
from enum import Enum, auto
from typing import Optional, Callable
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
    tools: Optional[list[dict]] = field(default_factory=list)

    """optional: tool functions"""
    tool_funcs: Optional[dict[str, Callable]] = field(default_factory=list)


@dataclass
class LLMResponse:
    text_response: str

    reasoning_content: Optional[str] = None

    tool_results: list = field(default_factory=list)

    input_tokens: Optional[int] = None

    output_tokens: Optional[int] = None
