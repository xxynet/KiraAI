import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI

from core.agent.base_agent_executor import BaseAgentExecutionContext, BaseAgentExecutor
from core.provider import LLMRequest, ModelInfo, ModelType, ProviderAPIError
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


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    "<html>upstream unavailable</html>",
    None,
    {"error": "upstream failure"},
    SimpleNamespace(choices=None, usage=None),
])
async def test_invalid_completion_is_provider_error(llm_client, body):
    client, create = llm_client
    create.return_value = body
    with pytest.raises(ProviderAPIError) as caught:
        await client.chat(LLMRequest())
    assert repr(body) in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("chunked", [False, True])
async def test_invalid_stream_or_chunk_is_provider_error(llm_client, chunked):
    client, create = llm_client
    body = "upstream stream failure"

    async def events():
        yield body

    create.return_value = events() if chunked else body
    with pytest.raises(ProviderAPIError) as caught:
        _ = [chunk async for chunk in client.chat_stream(LLMRequest())]
    assert body in str(caught.value)


@pytest.mark.asyncio
async def test_usage_only_stream_chunk_is_valid(llm_client):
    client, create = llm_client

    async def events():
        yield SimpleNamespace(choices=[], usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=2,
        ))

    create.return_value = events()
    chunks = [chunk async for chunk in client.chat_stream(LLMRequest())]
    assert len(chunks) == 1
    assert chunks[0].usage["input_tokens"] == 10
    assert chunks[0].usage["output_tokens"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback_enabled", [False, True])
async def test_actual_sdk_text_response_finishes_agent_or_falls_back(
    llm_client, monkeypatch, fallback_enabled,
):
    primary, _ = llm_client
    body = "<html>gateway upstream failure</html>" + " full error details" * 200

    def respond(request):
        return httpx.Response(200, text=body)

    async with AsyncOpenAI(
        api_key="test", base_url="https://provider.invalid/v1",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    ) as sdk:
        monkeypatch.setattr(primary, "_build_client", lambda: sdk)
        models = [primary]
        if fallback_enabled:
            fallback = OpenAICompatibleLLMClient(primary.model)
            create = AsyncMock(return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(
                    content="fallback reply", tool_calls=None,
                ))], usage=None,
            ))
            monkeypatch.setattr(fallback, "_build_client", lambda: SimpleNamespace(
                chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
            ))
            models.append(fallback)
        executor = BaseAgentExecutor(
            models, request=LLMRequest(), context=BaseAgentExecutionContext(),
        )
        steps = [step async for step in executor.run()]

    assert len(steps) == 1
    assert steps[0].is_final
    if fallback_enabled:
        assert steps[0].state == "success"
        assert steps[0].llm_response.text_response == "fallback reply"
        create.assert_awaited_once()
    else:
        assert steps[0].state == "error"
        assert body in steps[0].err
