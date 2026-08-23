import pytest
from fastapi import HTTPException

from core.persona import PersonaGenerationError, PersonaGenerator
from core.prompts.persona_generator import get_persona_generator_prompt
from core.provider import LLMResponse
from webui.models import PersonaGenerateRequest
from webui.routes.personas import PersonasRoutes


def test_persona_generator_prompt_is_localized():
    assert "人设创建助手" in get_persona_generator_prompt("zh-CN")
    assert "persona creation assistant" in get_persona_generator_prompt("en-US")


class _FakeClient:
    def __init__(self, tool_calls: list[dict]):
        self.tool_calls = tool_calls
        self.request = None

    async def chat(self, request, **kwargs):
        self.request = request
        return LLMResponse("", tool_calls=self.tool_calls)


class _FakeProviderManager:
    def __init__(self, tool_calls: list[dict]):
        self.client = _FakeClient(tool_calls)

    def get_default_llm(self):
        return self.client


class _FakeConfig:
    def get_config(self, _key):
        return "en"


class _FakeLifecycle:
    def __init__(self, tool_calls: list[dict]):
        self.provider_manager = _FakeProviderManager(tool_calls)
        self.kira_config = _FakeConfig()


def _proposal_tool_call(arguments: str) -> dict:
    return {
        "id": "proposal-1",
        "type": "function",
        "function": {"name": "propose_persona", "arguments": arguments},
    }


@pytest.mark.asyncio
async def test_persona_generator_returns_tool_proposal():
    client = _FakeClient([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )])

    result = await PersonaGenerator(client).generate("A calm companion", "en")

    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"
    assert client.request.tool_choice == "required"
    assert client.request.tools[0]["function"]["name"] == "propose_persona"


@pytest.mark.asyncio
async def test_persona_generator_rejects_missing_tool_proposal():
    with pytest.raises(PersonaGenerationError, match="did not propose"):
        await PersonaGenerator(_FakeClient([])).generate("A calm companion", "en")


@pytest.mark.asyncio
async def test_generate_persona_returns_model_draft():
    route = PersonasRoutes(None, _FakeLifecycle([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )]))

    result = await route.generate_persona(PersonaGenerateRequest(idea="A calm companion"))

    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"


@pytest.mark.asyncio
async def test_generate_persona_rejects_invalid_model_response():
    route = PersonasRoutes(None, _FakeLifecycle([_proposal_tool_call("not json")]))

    with pytest.raises(HTTPException, match="invalid response") as exc_info:
        await route.generate_persona(PersonaGenerateRequest())

    assert exc_info.value.status_code == 502
