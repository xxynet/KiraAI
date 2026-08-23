"""LLM-backed persona draft generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.agent.message import OpenAIMessage
from core.prompts.persona_generator import get_persona_generator_prompt
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


class PersonaGenerator:
    """Generate editable persona drafts with a dedicated LLM tool call."""

    def __init__(self, llm_client: LLMModelClient):
        self.llm_client = llm_client

    async def generate(self, idea: str, lang: str | None) -> PersonaProposal:
        # These imports are lazy because their dependency paths import Prompt,
        # which imports core.persona during application startup.
        from core.agent.tool import ToolSet
        from core.provider.llm_model import LLMRequest

        proposal_tool = ProposePersonaTool()
        request = LLMRequest(
            messages=[
                OpenAIMessage(role="system", content=get_persona_generator_prompt(lang)),
                OpenAIMessage(role="user", content=self._resolve_idea(idea, lang)),
            ],
            tool_set=ToolSet(tools=[proposal_tool]),
            tool_choice="required",
        )
        response = await self.llm_client.chat(request, max_tokens=1600)

        for tool_call in response.tool_calls:
            function = tool_call.get("function") or {}
            if function.get("name") != proposal_tool.name:
                continue
            arguments = function.get("arguments")
            if not isinstance(arguments, str):
                continue
            try:
                await proposal_tool.execute(**json.loads(arguments))
            except (TypeError, json.JSONDecodeError, PersonaGenerationError) as exc:
                raise PersonaGenerationError("Persona generator returned an invalid proposal") from exc
            if proposal_tool.proposal:
                return proposal_tool.proposal

        raise PersonaGenerationError("Persona generator did not propose a persona")

    @staticmethod
    def _resolve_idea(idea: str, lang: str | None) -> str:
        if idea.strip():
            return idea.strip()
        if (lang or "").lower().startswith("zh"):
            return "请为我创作一个温暖、有特色、适合日常陪伴聊天的原创人设。"
        return "Create a warm, distinctive original persona for everyday companion chats."
