"""LLM-backed persona draft generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import AsyncIterator, TYPE_CHECKING

from core.agent.message import OpenAIMessage
from core.prompts.persona_generator import get_initial_persona_question, get_persona_generator_prompt
from core.utils.tool_utils import BaseTool

if TYPE_CHECKING:
    from core.provider import LLMModelClient


SUPPORTED_PERSONA_FORMATS = frozenset({"text", "markdown", "json", "yaml"})


class PersonaGenerationError(ValueError):
    """Raised when the model does not submit a valid persona proposal."""


@dataclass(frozen=True)
class PersonaProposal:
    """A persona draft proposed by the LLM."""

    name: str
    format: str
    content: str


@dataclass(frozen=True)
class PersonaQuestion:
    """A follow-up question the LLM asks before proposing a persona."""

    question: str
    options: list[str]
    allow_custom: bool


@dataclass(frozen=True)
class PersonaTextDelta:
    """A streamed natural-language status update from the LLM."""

    content: str


class ProposePersonaTool(BaseTool):
    """Collect one validated persona proposal from an LLM tool call."""

    name = "propose_persona"
    description = "Submit the completed persona draft for the user to review and edit."
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "A short name for the persona.",
            },
            "format": {
                "type": "string",
                "enum": sorted(SUPPORTED_PERSONA_FORMATS),
                "description": "The format used by content.",
            },
            "content": {
                "type": "string",
                "description": "The complete persona in the selected format.",
            },
        },
        "required": ["name", "format", "content"],
        "additionalProperties": False,
    }

    def __init__(self):
        super().__init__()
        self.proposal: PersonaProposal | None = None

    async def execute(self, name: str, format: str, content: str, **_kwargs) -> str:
        if not all(isinstance(value, str) and value.strip() for value in (name, format, content)):
            raise PersonaGenerationError("Persona proposal is incomplete")
        if format not in SUPPORTED_PERSONA_FORMATS:
            raise PersonaGenerationError("Persona proposal uses an unsupported format")
        self.proposal = PersonaProposal(name=name.strip(), format=format, content=content)
        return "Persona proposal received."


class AskPersonaQuestionTool(BaseTool):
    """Collect one follow-up question from an LLM tool call."""

    name = "ask_persona_question"
    description = "Ask the user one question that helps create a better persona."
    parameters = {
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "One concise question for the user.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": "Two to four short answer choices for the user.",
            },
            "allow_custom": {
                "type": "boolean",
                "description": "Whether the user may provide a custom answer.",
            },
        },
        "required": ["question", "options", "allow_custom"],
        "additionalProperties": False,
    }

    def __init__(self):
        super().__init__()
        self.question: PersonaQuestion | None = None

    async def execute(
        self,
        question: str,
        allow_custom: bool,
        options: list[str],
        **_kwargs,
    ) -> str:
        if not isinstance(question, str) or not question.strip():
            raise PersonaGenerationError("Persona question is incomplete")
        if not isinstance(allow_custom, bool):
            raise PersonaGenerationError("Persona question has invalid custom-answer settings")
        if (
            not isinstance(options, list)
            or not 2 <= len(options) <= 4
            or any(not isinstance(option, str) or not option.strip() for option in options)
        ):
            raise PersonaGenerationError("Persona question has invalid options")
        self.question = PersonaQuestion(
            question=question.strip(),
            options=[option.strip() for option in options],
            allow_custom=allow_custom,
        )
        return "Persona question received."


class PersonaGenerator:
    """Generate editable persona drafts with a dedicated LLM tool call."""

    def __init__(self, llm_client: LLMModelClient):
        self.llm_client = llm_client

    @staticmethod
    def get_initial_question(lang: str | None) -> PersonaQuestion:
        return PersonaQuestion(
            question=get_initial_persona_question(lang),
            options=[],
            allow_custom=True,
        )

    async def respond(
        self,
        messages: list[OpenAIMessage],
        lang: str | None,
    ) -> PersonaQuestion | PersonaProposal:
        if not messages:
            return self.get_initial_question(lang)
        request = self._build_request(messages, lang)
        response = await self.llm_client.chat(request, max_tokens=1600)
        return await self._resolve_tool_calls(response.tool_calls)

    async def stream_respond(
        self,
        messages: list[OpenAIMessage],
        lang: str | None,
    ) -> AsyncIterator[PersonaTextDelta | PersonaQuestion | PersonaProposal]:
        if not messages:
            yield self.get_initial_question(lang)
            return

        request = self._build_request(messages, lang)
        tool_call_fragments: dict[int, dict] = {}
        complete_tool_calls: list[dict] = []
        emitted_text = False
        async for chunk in self.llm_client.chat_stream(request, max_tokens=1600):
            if chunk.delta_text:
                emitted_text = True
                yield PersonaTextDelta(chunk.delta_text)
            for fragment in chunk.tool_calls_delta:
                if "index" not in fragment:
                    complete_tool_calls.append(fragment)
                    continue
                index = fragment["index"]
                tool_call = tool_call_fragments.setdefault(index, {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                })
                if fragment.get("id"):
                    tool_call["id"] = fragment["id"]
                function = fragment.get("function") or {}
                if function.get("name"):
                    tool_call["function"]["name"] += function["name"]
                if function.get("arguments"):
                    tool_call["function"]["arguments"] += function["arguments"]

        complete_tool_calls.extend(tool_call_fragments.values())
        if complete_tool_calls:
            yield await self._resolve_tool_calls(complete_tool_calls)
        elif not emitted_text:
            raise PersonaGenerationError("Persona generator returned an empty response")

    @staticmethod
    def _build_request(messages: list[OpenAIMessage], lang: str | None):
        # These imports are lazy because their dependency paths import Prompt,
        # which imports core.persona during application startup.
        from core.agent.tool import ToolSet
        from core.provider.llm_model import LLMRequest

        proposal_tool = ProposePersonaTool()
        question_tool = AskPersonaQuestionTool()
        return LLMRequest(
            messages=[
                OpenAIMessage(role="system", content=get_persona_generator_prompt(lang)),
                *messages,
            ],
            tool_set=ToolSet(tools=[question_tool, proposal_tool]),
            tool_choice="auto",
        )

    @staticmethod
    async def _resolve_tool_calls(tool_calls: list[dict]) -> PersonaQuestion | PersonaProposal:
        proposal_tool = ProposePersonaTool()
        question_tool = AskPersonaQuestionTool()
        for tool_call in tool_calls:
            function = tool_call.get("function") or {}
            tool_name = function.get("name")
            tool = (
                question_tool if tool_name == question_tool.name
                else proposal_tool if tool_name == proposal_tool.name
                else None
            )
            if tool is None:
                continue
            arguments = function.get("arguments")
            if not isinstance(arguments, str):
                continue
            try:
                await tool.execute(**json.loads(arguments))
            except (TypeError, json.JSONDecodeError, PersonaGenerationError) as exc:
                raise PersonaGenerationError("Persona generator returned an invalid tool call") from exc
            if question_tool.question:
                return question_tool.question
            if proposal_tool.proposal:
                return proposal_tool.proposal

        raise PersonaGenerationError("Persona generator did not return a question or proposal")
