import pytest
from fastapi import HTTPException

from core.prompts.persona_generator import get_persona_generator_prompt
from core.provider import LLMResponse
from webui.models import PersonaGenerateRequest
from webui.routes.personas import PersonasRoutes


def test_persona_generator_prompt_is_localized():
    assert "人设创建助手" in get_persona_generator_prompt("zh-CN")
    assert "persona creation assistant" in get_persona_generator_prompt("en-US")


class _FakeClient:
    def __init__(self, response: str):
        self.response = response

    async def chat(self, request, **kwargs):
        return LLMResponse(self.response)


class _FakeProviderManager:
    def __init__(self, response: str):
        self.client = _FakeClient(response)

    def get_default_llm(self):
        return self.client


class _FakeConfig:
    def get_config(self, _key):
        return "en"


class _FakeLifecycle:
    def __init__(self, response: str):
        self.provider_manager = _FakeProviderManager(response)
        self.kira_config = _FakeConfig()


@pytest.mark.asyncio
async def test_generate_persona_returns_model_draft():
    route = PersonasRoutes(None, _FakeLifecycle(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    ))

    result = await route.generate_persona(PersonaGenerateRequest(idea="A calm companion"))

    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"


@pytest.mark.asyncio
async def test_generate_persona_rejects_invalid_model_response():
    route = PersonasRoutes(None, _FakeLifecycle("not json"))

    with pytest.raises(HTTPException, match="invalid response") as exc_info:
        await route.generate_persona(PersonaGenerateRequest())

    assert exc_info.value.status_code == 502
