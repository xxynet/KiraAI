from __future__ import annotations

from typing import Optional, Callable, Literal
from dataclasses import dataclass, field

from core.agent.tool import ToolSet
from core.agent.message import OpenAIMessage
from core.prompt_manager import Prompt

# Names of system prompt blocks whose content changes on nearly every request.
# They sit in the middle of the system prompt, so any change to them invalidates
# the cached token prefix of everything that follows, including the whole chat
# history. They can optionally be relocated to the tail of the latest user
# message, where nothing follows them and the prefix stays cacheable.
DYNAMIC_PROMPT_NAMES = ("sessions", "chat_env", "time")
MEMORY_PROMPT_NAME = "memory"


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
        self.messages = [
            m if isinstance(m, OpenAIMessage) else OpenAIMessage(**m)
            for m in self.messages
        ]
        # Derive tools list from tool_set when present
        if self.tool_set:
            self.tools = self.tool_set.to_list()
        if not self.tool_choice:
            if self.tools:
                self.tool_choice = "auto"
            else:
                self.tool_choice = "none"

    def assemble_prompt(
        self,
        dynamic_position: str = "latest_user",
        memory_position: str = "system",
    ):
        """Assemble system/user prompts into the message list.

        ``dynamic_position`` controls where the blocks listed in
        ``DYNAMIC_PROMPT_NAMES`` end up. ``"latest_user"`` (the default) moves
        them to the front of the latest user message so the system prompt stays
        a stable, cacheable prefix. ``"system"`` keeps them inline in the system
        prompt, the behavior prior to this option. Any unknown value falls back
        to ``"system"``.

        ``memory_position`` independently controls whether the core-memory
        block remains in the system prompt or is moved to the latest user
        message. It defaults to ``"system"`` to preserve the behavior of
        callers that do not provide the new setting.
        """
        static_prompt = self.system_prompt

        if dynamic_position == "latest_user" or memory_position == "latest_user":
            static_prompt = []
            relocated: list[Prompt] = []
            for p in self.system_prompt:
                should_relocate = isinstance(p, Prompt) and (
                    (p.name in DYNAMIC_PROMPT_NAMES and dynamic_position == "latest_user")
                    or (p.name == MEMORY_PROMPT_NAME and memory_position == "latest_user")
                )
                if should_relocate:
                    # Relocated blocks are request-only and must never be
                    # written back to the chat history.
                    p.persist = False
                    relocated.append(p)
                else:
                    static_prompt.append(p)
            if relocated:
                # Keep the environment context ahead of the actual user message,
                # wrapped so the model can tell it apart from what the user said.
                # The markers are separate Prompt objects rather than one merged
                # block so each relocated block is still formatted exactly once.
                self.user_prompt[:0] = [
                    Prompt("<system_reminder>", name="dynamic_context_start",
                           source="system", persist=False),
                    *relocated,
                    Prompt("</system_reminder>", name="dynamic_context_end",
                           source="system", persist=False),
                ]

        if self.system_prompt:
            if self.messages and self.messages[0].role == "system":
                self.messages.pop(0)
            if static_prompt:
                system_prompt = "".join(p.to_string() for p in static_prompt if isinstance(p, Prompt))
                self.messages.insert(0, OpenAIMessage(role="system", content=system_prompt))

        if self.user_prompt:
            user_prompt = "".join(p.to_string() for p in self.user_prompt if isinstance(p, Prompt))
            self.messages.append(OpenAIMessage(role="user", content=user_prompt))


@dataclass
class LLMResponse:
    """Content field in chat completion response"""
    text_response: str

    """
    reasoning content for reasoning models
    Make sure it's always a string to avoid missing fields in API responses
    """
    reasoning_content: str = ""

    """agent step index"""
    agent_step_index: Optional[int] = None

    """Tool call requests in OpenAI format"""
    tool_calls: list[dict] = field(default_factory=list)

    """Tool results list in OpenAI format, including role assistant & tool"""
    tool_results: list[dict] = field(default_factory=list)

    input_tokens: Optional[int] = None

    output_tokens: Optional[int] = None

    """cached tokens hit count"""
    cached_tokens: Optional[int] = None

    """Units: seconds"""
    time_consumed: Optional[float] = None

    def __post_init__(self):
        # Make sure reasoning_content is always string
        if self.reasoning_content is None:
            self.reasoning_content = ""


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming LLM response."""

    """Incremental text content for this chunk"""
    delta_text: str = ""

    """Incremental reasoning content for reasoning models"""
    delta_reasoning: str = ""

    """Incremental tool call fragments in this chunk only"""
    tool_calls_delta: list[dict] = field(default_factory=list)

    """Whether this is the final chunk in the stream"""
    is_final: bool = False

    """Finish reason on the final chunk: stop / tool_calls / content_filter"""
    finish_reason: str = ""

    """Token usage — only populated on the final chunk"""
    usage: Optional[dict] = None


@dataclass
class RerankResult:
    index: int

    score: float

    text: str
