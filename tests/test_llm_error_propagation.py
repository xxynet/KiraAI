import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError

from core.provider import LLMRequest, ModelInfo, ModelType
from core.provider.openai_compatible import OpenAICompatibleLLMClient
from core.provider.src.deepseek.model_clients import DeepSeekLLMClient


@pytest.fixture(params=["status", "timeout", "connection", "runtime", "cancel"])
def upstream_error(request):
    http_request = httpx.Request("POST", "https://provider.invalid/chat/completions")
    return {
        "status": APIStatusError(
            "request failed", response=httpx.Response(503, request=http_request), body=None,
        ),
        "timeout": APITimeoutError(request=http_request),
        "connection": APIConnectionError(request=http_request),
        "runtime": RuntimeError("request failed"),
        "cancel": asyncio.CancelledError("request cancelled"),
    }[request.param]


@pytest.fixture(params=[OpenAICompatibleLLMClient, DeepSeekLLMClient])
def llm_client(request, monkeypatch):
    client = request.param(ModelInfo(
        model_type=ModelType.LLM, model_id="test", model_name="test",
        provider_id="test", provider_name="test",
    ))
    create = AsyncMock()
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(client, "_build_client", lambda: sdk)
    return client, create


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_request_failure_propagates_unchanged(llm_client, upstream_error, streaming):
    client, create = llm_client
    create.side_effect = upstream_error

    with pytest.raises(type(upstream_error)) as caught:
        if streaming:
            _ = [chunk async for chunk in client.chat_stream(LLMRequest())]
        else:
            await client.chat(LLMRequest())

    assert caught.value is upstream_error
    create.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_failure_after_partial_reply_propagates_unchanged(
    llm_client, upstream_error,
):
    client, create = llm_client

    async def events():
        yield SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="partial", reasoning_content=None, tool_calls=None),
            finish_reason=None,
        )])
        raise upstream_error

    create.return_value = events()
    stream = client.chat_stream(LLMRequest())
    assert (await anext(stream)).delta_text == "partial"
    with pytest.raises(type(upstream_error)) as caught:
        await anext(stream)

    assert caught.value is upstream_error
    create.assert_awaited_once()
