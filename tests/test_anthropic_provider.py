import json
from types import SimpleNamespace

import httpx
import pytest
from anthropic import AnthropicError, AsyncAnthropic, DefaultAsyncHttpxClient

from core.agent.message import OpenAIMessage
from core.provider import LLMRequest, ModelInfo, ModelType, ProviderAPIError
from core.provider.src.anthropic.model_clients import (
    AnthropicCompatibleLLMClient,
    build_anthropic_headers,
    normalize_anthropic_base_url,
)
from core.provider.src.anthropic.provider import AnthropicProvider
from core.utils.model_clients import DEFAULT_USER_AGENT


def build_client(
    provider_config: dict | None = None,
    model_config: dict | None = None,
) -> AnthropicCompatibleLLMClient:
    return AnthropicCompatibleLLMClient(
        ModelInfo(
            model_type=ModelType.LLM,
            model_id="claude-test",
            provider_id="anthropic-test",
            provider_name="Anthropic Test",
            provider_config=provider_config
            or {
                "base_url": "https://api.example.com",
                "api_key": "test-key",
            },
            model_config=model_config or {},
        )
    )


def test_normalizes_compatible_base_urls_and_builds_headers():
    assert normalize_anthropic_base_url("https://api.anthropic.com") == (
        "https://api.anthropic.com"
    )
    assert normalize_anthropic_base_url("https://gateway.example/v1") == (
        "https://gateway.example"
    )
    assert (
        normalize_anthropic_base_url("https://gateway.example/anthropic/v1/messages")
        == "https://gateway.example/anthropic"
    )

    headers = build_anthropic_headers(
        {
            "api_key": "secret",
            "anthropic_version": "custom-version",
            "section_advanced": {"headers": {"x-api-key": "override", "x-tenant": 42}},
        }
    )

    assert headers["anthropic-version"] == "custom-version"
    assert headers["x-api-key"] == "override"
    assert headers["x-tenant"] == "42"
    assert headers["User-Agent"] == DEFAULT_USER_AGENT


def test_converts_openai_messages_images_and_tool_round_trip():
    request = LLMRequest(
        messages=[
            OpenAIMessage(role="system", content="Be concise."),
            OpenAIMessage(
                role="user",
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,aGVsbG8="},
                    },
                    {"type": "text", "text": "What is shown?"},
                ],
            ),
            OpenAIMessage(
                role="assistant",
                content="I will inspect it.",
                tool_calls=[
                    {
                        "id": "tool-1",
                        "type": "function",
                        "function": {"name": "inspect", "arguments": '{"detail":true}'},
                    }
                ],
            ),
            OpenAIMessage(
                role="tool",
                tool_call_id="tool-1",
                name="inspect",
                content="done",
            ),
        ]
    )

    system, messages = build_client()._convert_messages(request)

    assert system == "Be concise."
    assert messages[0] == {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": "aGVsbG8=",
                },
            },
            {"type": "text", "text": "What is shown?"},
        ],
    }
    assert messages[1]["content"][-1] == {
        "type": "tool_use",
        "id": "tool-1",
        "name": "inspect",
        "input": {"detail": True},
    }
    assert messages[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "tool-1",
                "content": [{"type": "text", "text": "done"}],
            }
        ],
    }


def test_builds_anthropic_tool_request_and_parses_response():
    client = build_client(
        model_config={
            "max_tokens": 2048,
            "section_advanced": {
                "temperature": 0.25,
                "extra_body": {"metadata": {"user_id": "test-user"}},
            },
        }
    )
    request = LLMRequest(
        messages=[{"role": "user", "content": "Use the tool"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "lookup",
                    "description": "Look something up",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                    },
                },
            }
        ],
        tool_choice="required",
    )

    body = client._build_request_body(request)

    assert body["max_tokens"] == 2048
    assert body["temperature"] == 0.25
    assert body["tool_choice"] == {"type": "any"}
    assert body["tools"] == [
        {
            "name": "lookup",
            "description": "Look something up",
            "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    ]
    assert body["extra_body"] == {"metadata": {"user_id": "test-user"}}

    response = client._parse_response(
        {
            "content": [
                {"type": "thinking", "thinking": "Check first."},
                {"type": "text", "text": "Calling lookup."},
                {
                    "type": "tool_use",
                    "id": "tool-2",
                    "name": "lookup",
                    "input": {"q": "Kira"},
                },
            ],
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "cache_read_input_tokens": 5,
                "cache_creation_input_tokens": 3,
            },
        },
        0.5,
    )

    assert response.text_response == "Calling lookup."
    assert response.reasoning_content == "Check first."
    assert response.tool_calls == [
        {
            "id": "tool-2",
            "type": "function",
            "function": {"name": "lookup", "arguments": '{"q": "Kira"}'},
        }
    ]
    assert (response.input_tokens, response.output_tokens, response.cached_tokens) == (
        20,
        7,
        5,
    )
    assert response.time_consumed == 0.5

    request.tool_choice = "none"
    body_without_tools = client._build_request_body(request)
    assert "tools" not in body_without_tools
    assert "tool_choice" not in body_without_tools


@pytest.mark.anyio
async def test_chat_uses_official_async_sdk(monkeypatch):
    client = build_client()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.example.com/v1/messages"
        assert request.headers["x-api-key"] == "test-key"
        body = json.loads(request.content)
        assert body["model"] == "claude-test"
        assert body["messages"] == [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Hello"}],
            }
        ]
        return httpx.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "Hi"}],
                "stop_reason": "end_turn",
                "stop_sequence": None,
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
            headers={"request-id": "req_test"},
        )

    transport = httpx.MockTransport(handler)
    sdk_client = AsyncAnthropic(
        api_key="test-key",
        base_url="https://api.example.com",
        http_client=DefaultAsyncHttpxClient(transport=transport),
    )
    monkeypatch.setattr(client, "_build_client", lambda: sdk_client)

    response = await client.chat(
        LLMRequest(
            messages=[
                {"role": "user", "content": "Hello"},
            ]
        )
    )

    assert response.text_response == "Hi"


@pytest.mark.anyio
async def test_chat_stream_converts_sdk_events_and_normalizes_tool_indices(monkeypatch):
    client = build_client()
    event_payloads = [
        {
            "type": "message_start",
            "message": {
                "id": "msg_stream_test",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {
                    "input_tokens": 2,
                    "cache_creation_input_tokens": 1,
                    "cache_read_input_tokens": 3,
                },
            },
        },
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hi"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use",
                "id": "tool-3",
                "name": "lookup",
                "input": {},
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"q":"Kira"}'},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 5},
        },
        {"type": "message_stop"},
    ]
    sse_body = "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
        for event in event_payloads
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            text=sse_body,
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    sdk_client = AsyncAnthropic(
        api_key="test-key",
        base_url="https://api.example.com",
        http_client=DefaultAsyncHttpxClient(transport=transport),
    )
    monkeypatch.setattr(client, "_build_client", lambda: sdk_client)

    chunks = [
        chunk
        async for chunk in client.chat_stream(
            LLMRequest(
                messages=[
                    {"role": "user", "content": "Hello"},
                ]
            )
        )
    ]

    assert chunks[0].delta_text == "Hi"
    assert chunks[1].tool_calls_delta[0] == {
        "index": 0,
        "id": "tool-3",
        "type": "function",
        "function": {"name": "lookup", "arguments": ""},
    }
    assert chunks[2].tool_calls_delta[0]["index"] == 0
    assert chunks[2].tool_calls_delta[0]["function"]["arguments"] == '{"q":"Kira"}'
    assert chunks[3].is_final is True
    assert chunks[3].finish_reason == "tool_calls"
    assert chunks[3].usage == {
        "input_tokens": 6,
        "output_tokens": 5,
        "cached_tokens": 3,
    }


@pytest.mark.anyio
async def test_lists_all_remote_model_pages(monkeypatch):
    requested_limits: list[int] = []

    class FakePage:
        def __init__(self, data, next_page=None):
            self.data = data
            self.next_page = next_page

        def has_next_page(self):
            return self.next_page is not None

        async def get_next_page(self):
            return self.next_page

    second_page = FakePage(
        [SimpleNamespace(id="claude-old", display_name="Claude Old")]
    )
    first_page = FakePage(
        [SimpleNamespace(id="claude-new", display_name="Claude New")],
        second_page,
    )

    class FakeModels:
        async def list(self, limit):
            requested_limits.append(limit)
            return first_page

    class FakeClient:
        models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(
        "core.provider.src.anthropic.provider.build_anthropic_client",
        lambda *args, **kwargs: FakeClient(),
    )
    provider = AnthropicProvider(
        "anthropic-test",
        "Anthropic Test",
        {"base_url": "https://api.example.com", "api_key": "test-key"},
    )

    models = await provider.get_llm_list()

    assert models == [
        {"id": "claude-new", "name": "Claude New", "description": ""},
        {"id": "claude-old", "name": "Claude Old", "description": ""},
    ]
    assert requested_limits == [100]


@pytest.mark.anyio
async def test_model_pagination_is_bounded(monkeypatch):
    next_page_calls = 0

    class RepeatingPage:
        data = [SimpleNamespace(id="repeated", display_name="Repeated")]

        @staticmethod
        def has_next_page():
            return True

        async def get_next_page(self):
            nonlocal next_page_calls
            next_page_calls += 1
            return self

    class FakeModels:
        async def list(self, limit):
            return RepeatingPage()

    class FakeClient:
        models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(
        "core.provider.src.anthropic.provider.build_anthropic_client",
        lambda *args, **kwargs: FakeClient(),
    )
    provider = AnthropicProvider("test", "Test", {})

    models = await provider.get_llm_list()

    assert len(models) == 20
    assert next_page_calls == 19


@pytest.mark.anyio
async def test_model_pagination_handles_nonstandard_missing_next_page(monkeypatch):
    """Protect compatible paginator implementations outside the SDK contract."""

    class NonstandardMissingNextPage:
        data = [SimpleNamespace(id="first", display_name="First")]

        @staticmethod
        def has_next_page():
            return True

        @staticmethod
        async def get_next_page():
            return None

    class FakeModels:
        async def list(self, limit):
            return NonstandardMissingNextPage()

    class FakeClient:
        models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(
        "core.provider.src.anthropic.provider.build_anthropic_client",
        lambda *args, **kwargs: FakeClient(),
    )
    provider = AnthropicProvider("test", "Test", {})

    models = await provider.get_llm_list()

    assert models == [{"id": "first", "name": "First", "description": ""}]


@pytest.mark.anyio
async def test_sdk_errors_are_wrapped_for_model_failover(monkeypatch):
    client = build_client()

    class FakeMessages:
        async def create(self, **kwargs):
            raise AnthropicError("SDK request failed")

    class FakeClient:
        messages = FakeMessages()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

    monkeypatch.setattr(client, "_build_client", FakeClient)

    with pytest.raises(ProviderAPIError, match="SDK request failed"):
        await client.chat(LLMRequest(messages=[{"role": "user", "content": "Hi"}]))
