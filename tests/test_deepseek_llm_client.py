"""Regression tests for the DeepSeek LLM client.

Covers the configured ``timeout`` reaching the request kwargs, the single
final stream chunk carrying both finish_reason and usage, and the client
being closed once the stream is exhausted.
"""

from types import SimpleNamespace

import httpx
import pytest
from openai import APIStatusError, NOT_GIVEN

from core.provider import LLMRequest, ModelInfo, ModelType
from core.provider.src.deepseek.model_clients import DeepSeekLLMClient


def build_client(model_config: dict | None = None) -> DeepSeekLLMClient:
    return DeepSeekLLMClient(
        ModelInfo(
            model_type=ModelType.LLM,
            model_id="deepseek-chat",
            provider_id="deepseek-test",
            provider_name="DeepSeek Test",
            provider_config={
                "base_url": "https://api.example.com",
                "api_key": "test-key",
            },
            model_config=model_config or {},
        )
    )


def build_request() -> LLMRequest:
    return LLMRequest(messages=[{"role": "user", "content": "ping"}])


def usage_event(prompt_tokens: int, completion_tokens: int, cache_hit: int):
    return SimpleNamespace(
        choices=[],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            prompt_cache_hit_tokens=cache_hit,
        ),
    )


def delta_event(content: str = "", finish_reason: str | None = None):
    delta = SimpleNamespace(content=content, tool_calls=None, reasoning_content="")
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)],
        usage=None,
    )


class FakeStream:
    def __init__(self, events):
        self._events = events

    async def __aiter__(self):
        for event in self._events:
            yield event


class FakeCompletions:
    def __init__(self, events: list, calls: list, reject_stream_options: bool = False):
        self._events = events
        self._calls = calls
        self._reject_stream_options = reject_stream_options

    async def create(self, **kwargs):
        self._calls.append(kwargs)
        if self._reject_stream_options and kwargs.get("stream_options"):
            raise APIStatusError(
                "stream_options is not supported",
                response=httpx.Response(
                    400, request=httpx.Request("POST", "https://api.example.com")
                ),
                body=None,
            )
        return FakeStream(self._events)


class FakeClient:
    def __init__(self, events: list, calls: list, reject_stream_options: bool = False):
        self.chat = SimpleNamespace(
            completions=FakeCompletions(events, calls, reject_stream_options)
        )
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True
        return None


def test_request_kwargs_pass_configured_timeout():
    kwargs = build_client({"timeout": 45})._build_request_kwargs(build_request())

    assert kwargs["timeout"] == 45


def test_request_kwargs_omit_unset_timeout():
    kwargs = build_client()._build_request_kwargs(build_request())

    assert kwargs["timeout"] is NOT_GIVEN


def test_request_kwargs_allow_caller_to_override_timeout():
    kwargs = build_client({"timeout": 45})._build_request_kwargs(
        build_request(), timeout=5
    )

    assert kwargs["timeout"] == 5


@pytest.mark.anyio
async def test_chat_stream_emits_a_single_final_chunk_with_usage(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient(
        [
            delta_event("Hi"),
            delta_event("", finish_reason="stop"),
            usage_event(11, 5, 3),
        ],
        calls,
    )
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    chunks = [chunk async for chunk in client.chat_stream(build_request())]

    finals = [chunk for chunk in chunks if chunk.is_final]
    assert len(finals) == 1
    assert finals[0].finish_reason == "stop"
    assert finals[0].usage == {
        "input_tokens": 11,
        "output_tokens": 5,
        "cached_tokens": 3,
    }
    assert "".join(chunk.delta_text for chunk in chunks) == "Hi"
    assert fake_client.closed is True


@pytest.mark.anyio
async def test_chat_stream_retries_without_stream_options(monkeypatch):
    calls: list[dict] = []
    fake_client = FakeClient(
        [delta_event("Hi", finish_reason="stop")], calls, reject_stream_options=True
    )
    client = build_client()
    monkeypatch.setattr(client, "_build_client", lambda: fake_client)

    chunks = [chunk async for chunk in client.chat_stream(build_request())]

    assert len(calls) == 2
    assert calls[0]["stream_options"] == {"include_usage": True}
    assert "stream_options" not in calls[1]
    assert chunks[-1].is_final is True
    assert chunks[-1].usage is None
