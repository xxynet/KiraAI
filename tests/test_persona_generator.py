import pytest
from fastapi import HTTPException

from core.agent.message import OpenAIMessage
from core.persona import PersonaGenerationError, PersonaGenerator, PersonaQuestion
from core.prompts.persona_generator import get_initial_persona_question, get_persona_generator_prompt
from core.provider import LLMResponse, LLMStreamChunk
from webui.models import PersonaGeneratorMessage, PersonaGeneratorTurnRequest
from webui.routes.personas import PersonasRoutes


def test_persona_generator_prompt_is_localized():
    assert "人设创建助手" in get_persona_generator_prompt("zh-CN")
    assert "persona creation assistant" in get_persona_generator_prompt("en-US")
    assert "你希望创建怎样的人设" in get_initial_persona_question("zh-CN")
    assert "What kind of persona" in get_initial_persona_question("en-US")


class _FakeClient:
    def __init__(self, tool_calls: list[dict], stream_chunks: list[LLMStreamChunk] | None = None):
        self.tool_calls = tool_calls
        self.stream_chunks = stream_chunks or []
        self.request = None

    async def chat(self, request, **kwargs):
        self.request = request
        return LLMResponse("", tool_calls=self.tool_calls)

    async def chat_stream(self, request, **kwargs):
        self.request = request
        for chunk in self.stream_chunks:
            yield chunk


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


def _question_tool_call(arguments: str) -> dict:
    return {
        "id": "question-1",
        "type": "function",
        "function": {"name": "ask_persona_question", "arguments": arguments},
    }


@pytest.mark.asyncio
async def test_persona_generator_returns_tool_question():
    client = _FakeClient([])
    result = await PersonaGenerator(client).respond([], "en")

    assert isinstance(result, PersonaQuestion)
    assert result.question.startswith("What kind of persona")
    assert result.options == []
    assert result.allow_custom is True
    assert client.request is None


@pytest.mark.asyncio
async def test_persona_generator_returns_follow_up_tool_question():
    client = _FakeClient([_question_tool_call(
        '{"question":"What tone should the persona use?","options":["Warm","Playful"],"allow_custom":true}'
    )])

    result = await PersonaGenerator(client).respond(
        [OpenAIMessage(role="user", content="A calm companion")],
        "en",
    )

    assert isinstance(result, PersonaQuestion)
    assert result.options == ["Warm", "Playful"]
    assert result.allow_custom is True
    assert client.request.tool_choice == "auto"
    assert {tool["function"]["name"] for tool in client.request.tools} == {
        "ask_persona_question", "propose_persona",
    }


@pytest.mark.asyncio
async def test_persona_generator_returns_tool_proposal():
    client = _FakeClient([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )])

    result = await PersonaGenerator(client).respond(
        [OpenAIMessage(role="user", content="A calm companion")],
        "en",
    )

    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"


@pytest.mark.asyncio
async def test_persona_generator_rejects_missing_tool_result():
    with pytest.raises(PersonaGenerationError, match="did not return"):
        await PersonaGenerator(_FakeClient([])).respond(
            [OpenAIMessage(role="user", content="A calm companion")],
            "en",
        )


@pytest.mark.asyncio
async def test_persona_generator_streams_text_and_question():
    client = _FakeClient([], stream_chunks=[
        LLMStreamChunk(delta_text="Let me narrow that down. "),
        LLMStreamChunk(tool_calls_delta=[{
            "index": 0,
            "id": "question-1",
            "type": "function",
            "function": {
                "name": "ask_persona_question",
                "arguments": '{"question":"What tone should the persona use?","options":["Warm","Playful"],"allow_custom":true}',
            },
        }], is_final=True),
    ])

    results = [
        result async for result in PersonaGenerator(client).stream_respond(
            [OpenAIMessage(role="user", content="A calm companion")], "en",
        )
    ]

    assert results[0].content == "Let me narrow that down. "
    assert isinstance(results[1], PersonaQuestion)
    assert results[1].options == ["Warm", "Playful"]


@pytest.mark.asyncio
async def test_persona_generator_turn_returns_model_draft():
    route = PersonasRoutes(None, _FakeLifecycle([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )]))

    result = await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content="A calm companion"),
    ]))

    assert result.type == "proposal"
    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"


@pytest.mark.asyncio
async def test_persona_generator_turn_rejects_invalid_model_response():
    route = PersonasRoutes(None, _FakeLifecycle([_proposal_tool_call("not json")]))

    with pytest.raises(HTTPException, match="invalid response") as exc_info:
        await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
            PersonaGeneratorMessage(role="user", content="A calm companion"),
        ]))

    assert exc_info.value.status_code == 502
