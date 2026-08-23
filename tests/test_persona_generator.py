import json

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


def test_persona_generator_turn_request_accepts_extended_conversation():
    request = PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content=f"Message {index}")
        for index in range(21)
    ])

    assert len(request.messages) == 21


class _FakeClient:
    def __init__(
        self,
        tool_calls: list[dict],
        stream_chunks: list[LLMStreamChunk] | None = None,
        stream_error: Exception | None = None,
    ):
        self.tool_calls = tool_calls
        self.stream_chunks = stream_chunks or []
        self.stream_error = stream_error
        self.request = None

    async def chat(self, request, **kwargs):
        self.request = request
        return LLMResponse("", tool_calls=self.tool_calls)

    async def chat_stream(self, request, **kwargs):
        self.request = request
        if self.stream_error:
            raise self.stream_error
        for chunk in self.stream_chunks:
            yield chunk


class _FakeProviderManager:
    def __init__(
        self,
        tool_calls: list[dict],
        has_fast_llm: bool = True,
        fast_llm_error: Exception | None = None,
        stream_chunks: list[LLMStreamChunk] | None = None,
        stream_error: Exception | None = None,
    ):
        self.client = _FakeClient(tool_calls, stream_chunks, stream_error)
        self.fast_client = _FakeClient(tool_calls, stream_chunks, stream_error) if has_fast_llm else None
        self.fast_llm_error = fast_llm_error

    def get_default_fast_llm(self):
        if self.fast_llm_error:
            raise self.fast_llm_error
        if self.fast_client is None:
            raise ValueError("default_fast_llm not set")
        return self.fast_client

    def get_default_llm(self):
        return self.client


class _FakeConfig:
    def get_config(self, _key):
        return "en"


class _FakeLifecycle:
    def __init__(
        self,
        tool_calls: list[dict],
        has_fast_llm: bool = True,
        fast_llm_error: Exception | None = None,
        stream_chunks: list[LLMStreamChunk] | None = None,
        stream_error: Exception | None = None,
    ):
        self.provider_manager = _FakeProviderManager(
            tool_calls,
            has_fast_llm,
            fast_llm_error,
            stream_chunks,
            stream_error,
        )
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


async def _stream_events(route: PersonasRoutes):
    response = await route.persona_generator_stream(PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content="A calm companion"),
    ]))
    body = ""
    async for chunk in response.body_iterator:
        body += chunk.decode() if isinstance(chunk, bytes) else chunk
    return [json.loads(event.removeprefix("data: ")) for event in body.split("\n\n") if event]


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
async def test_persona_generator_stream_endpoint_emits_text_and_question_events():
    lifecycle = _FakeLifecycle([], stream_chunks=[
        LLMStreamChunk(delta_text="Let me narrow that down. "),
        LLMStreamChunk(tool_calls_delta=[{
            "index": 0,
            "id": "question-1",
            "type": "function",
            "function": {
                "name": "ask_persona_question",
                "arguments": '{"question":"What tone should the persona use?","options":["Warm","Playful"],"allow_custom":true}',
            },
        }]),
    ])
    route = PersonasRoutes(None, lifecycle)

    events = await _stream_events(route)

    assert events == [
        {"type": "text", "content": "Let me narrow that down. "},
        {
            "type": "question",
            "question": "What tone should the persona use?",
            "options": ["Warm", "Playful"],
            "allow_custom": True,
        },
    ]


@pytest.mark.asyncio
async def test_persona_generator_stream_endpoint_emits_proposal_event():
    lifecycle = _FakeLifecycle([], stream_chunks=[
        LLMStreamChunk(tool_calls_delta=[{
            "index": 0,
            "id": "proposal-1",
            "type": "function",
            "function": {
                "name": "propose_persona",
                "arguments": '{"name":"Luna","format":"markdown","content":"# Luna"}',
            },
        }]),
    ])
    route = PersonasRoutes(None, lifecycle)

    events = await _stream_events(route)

    assert events == [{"type": "proposal", "name": "Luna", "format": "markdown", "content": "# Luna"}]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stream_chunks", "stream_error", "message"),
    [
        ([LLMStreamChunk(tool_calls_delta=[{
            "index": 0,
            "id": "proposal-1",
            "type": "function",
            "function": {"name": "propose_persona", "arguments": "not json"},
        }])], None, "Persona generator returned an invalid response"),
        (None, RuntimeError("connection lost"), "Failed to generate persona"),
    ],
)
async def test_persona_generator_stream_endpoint_emits_error_event(stream_chunks, stream_error, message):
    lifecycle = _FakeLifecycle([], stream_chunks=stream_chunks, stream_error=stream_error)
    route = PersonasRoutes(None, lifecycle)

    events = await _stream_events(route)

    assert events == [{"type": "error", "message": message}]


@pytest.mark.asyncio
async def test_persona_generator_turn_returns_model_draft():
    lifecycle = _FakeLifecycle([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )])
    route = PersonasRoutes(None, lifecycle)

    result = await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content="A calm companion"),
    ]))

    assert result.type == "proposal"
    assert result.name == "Luna"
    assert result.format == "markdown"
    assert result.content == "# Luna"
    assert lifecycle.provider_manager.fast_client.request is not None
    assert lifecycle.provider_manager.client.request is None


@pytest.mark.asyncio
async def test_persona_generator_prefers_proposal_when_both_tools_are_called():
    client = _FakeClient([
        _question_tool_call(
            '{"question":"What tone should the persona use?","options":["Warm","Playful"],"allow_custom":true}'
        ),
        _proposal_tool_call('{"name":"Luna","format":"markdown","content":"# Luna"}'),
    ])

    result = await PersonaGenerator(client).respond(
        [OpenAIMessage(role="user", content="A calm companion")],
        "en",
    )

    assert result.name == "Luna"


@pytest.mark.asyncio
async def test_persona_generator_turn_falls_back_to_default_llm():
    lifecycle = _FakeLifecycle([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )], has_fast_llm=False)
    route = PersonasRoutes(None, lifecycle)

    result = await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content="A calm companion"),
    ]))

    assert result.type == "proposal"
    assert lifecycle.provider_manager.client.request is not None


@pytest.mark.asyncio
async def test_persona_generator_turn_falls_back_when_fast_provider_is_missing():
    lifecycle = _FakeLifecycle([_proposal_tool_call(
        '{"name":"Luna","format":"markdown","content":"# Luna"}'
    )], fast_llm_error=AttributeError("provider is not registered"))
    route = PersonasRoutes(None, lifecycle)

    result = await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
        PersonaGeneratorMessage(role="user", content="A calm companion"),
    ]))

    assert result.type == "proposal"
    assert lifecycle.provider_manager.client.request is not None


@pytest.mark.asyncio
async def test_persona_generator_turn_rejects_invalid_model_response():
    route = PersonasRoutes(None, _FakeLifecycle([_proposal_tool_call("not json")]))

    with pytest.raises(HTTPException, match="invalid response") as exc_info:
        await route.persona_generator_turn(PersonaGeneratorTurnRequest(messages=[
            PersonaGeneratorMessage(role="user", content="A calm companion"),
        ]))

    assert exc_info.value.status_code == 502
