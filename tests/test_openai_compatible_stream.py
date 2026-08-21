"""Regression tests for the shared OpenAI-compatible streaming client.

A consumer stopping at the first ``is_final`` chunk used to lose token usage,
and gateways rejecting ``stream_options`` used to fail streaming outright.
"""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError

from core.provider import LLMRequest, ModelInfo, ModelType
from core.utils.model_clients import (
    OpenAICompatibleLLMClient,
    apply_stream_options,
    create_chat_stream,
)


def build_client() -> OpenAICompatibleLLMClient:
    return OpenAICompatibleLLMClient(
        ModelInfo(
            model_type=ModelType.LLM,
            model_id="gpt-test",
            provider_id="openai-test",
            provider_name="OpenAI Test",
            provider_config={
                "base_url": "https://api.example.com",
                "api_key": "test-key",
            },
            model_config={},
        )
    )


def status_error() -> APIStatusError:
    return APIStatusError(
        "stream_options is not supported",
        response=httpx.Response(
            400, request=httpx.Request("POST", "https://api.example.com")
        ),
        body=None,
    )


def delta_event(content: str = "", finish_reason: str | None = None):
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content="")
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


def usage_event(prompt_tokens: int, completion_tokens: int, cached_tokens: int):
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached_tokens),
        ),
    )


class FakeStream:
    def __init__(self, events):
        self._events = events

    async def __aiter__(self):
        for event in self._events:
            yield event


class FakeCompletions:
    def __init__(self, events, calls, reject_stream_options=False):
        self._events = events
        self._calls = calls
        self._reject_stream_options = reject_stream_options

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if self._reject_stream_options and kwargs.get("stream_options"):
            raise status_error()
        return FakeStream(self._events)


class FakeClient:
    def __init__(self, events, calls, reject_stream_options=False):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(events, calls, reject_stream_options)
        )
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True
        return None


@pytest.mark.anyio
async def test_chat_stream_merges_finish_reason_and_usage_into_one_chunk(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient(
        [
            delta_event("Hel"),
            delta_event("lo"),
            delta_event("", finish_reason="stop"),
            usage_event(9, 4, 2),
        ],
        calls,
    )
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    chunks = [
        chunk
        async for chunk in client.chat_stream(
            LLMRequest(messages=[{"role": "user", "content": "ping"}])
        )
    ]

    finals = [chunk for chunk in chunks if chunk.is_final]
    assert len(finals) == 1
    assert finals[0].finish_reason == "stop"
    assert finals[0].usage == {
        "input_tokens": 9,
        "output_tokens": 4,
        "cached_tokens": 2,
    }
    assert "".join(chunk.delta_text for chunk in chunks) == "Hello"
    assert fake_client.closed is True


@pytest.mark.anyio
async def test_chat_stream_reports_usage_when_finish_reason_is_missing(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient([delta_event("Hi"), usage_event(3, 1, 0)], calls)
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    chunks = [
        chunk
        async for chunk in client.chat_stream(
            LLMRequest(messages=[{"role": "user", "content": "ping"}])
        )
    ]

    assert chunks[-1].is_final is True
    assert chunks[-1].usage["input_tokens"] == 3


@pytest.mark.anyio
async def test_chat_stream_degrades_when_gateway_rejects_stream_options(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient(
        [delta_event("Hi", finish_reason="stop")], calls, reject_stream_options=True
    )
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    chunks = [
        chunk
        async for chunk in client.chat_stream(
            LLMRequest(messages=[{"role": "user", "content": "ping"}])
        )
    ]

    assert [call.get("stream_options") for call in calls] == [
        {"include_usage": True},
        None,
    ]
    assert chunks[-1].is_final is True


def test_stream_options_default_on_and_can_be_opted_out():
    default_kwargs: dict = {}
    apply_stream_options(default_kwargs)
    assert default_kwargs["stream_options"] == {"include_usage": True}

    opted_out = {"stream_options": None}
    apply_stream_options(opted_out)
    assert "stream_options" not in opted_out


@pytest.mark.anyio
async def test_chat_stream_can_be_called_without_stream_options(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient([delta_event("Hi", finish_reason="stop")], calls)
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    _ = [
        chunk
        async for chunk in client.chat_stream(
            LLMRequest(messages=[{"role": "user", "content": "ping"}]),
            stream_options=None,
        )
    ]

    assert "stream_options" not in calls[0]


@pytest.mark.anyio
async def test_create_chat_stream_reraises_errors_unrelated_to_stream_options():
    attempts: list[dict] = []

    class AlwaysFailing:
        async def create(self, **kwargs):
            attempts.append(kwargs)
            raise status_error()

    fake_client = SimpleNamespace(chat=SimpleNamespace(completions=AlwaysFailing()))

    with pytest.raises(APIStatusError):
        await create_chat_stream(fake_client, {"model": "gpt-test"})

    assert len(attempts) == 1
