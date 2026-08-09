import pytest
from openai import NOT_GIVEN

from core.provider import LLMRequest, ModelInfo, ModelType
from core.provider.src.deepseek.model_clients import DeepSeekLLMClient
from core.utils.model_clients import (
    DEFAULT_USER_AGENT,
    OpenAICompatibleLLMClient,
    build_llm_default_headers,
)


def test_llm_headers_default_and_preserve_custom_user_agent():
    assert build_llm_default_headers({}) == {"User-Agent": DEFAULT_USER_AGENT}
    assert build_llm_default_headers(
        {"section_advanced": {"headers": {"X-Tenant": 42}}}
    ) == {"X-Tenant": "42", "User-Agent": DEFAULT_USER_AGENT}
    assert build_llm_default_headers(
        {"section_advanced": {"headers": {"user-agent": "custom-agent/1.0"}}}
    ) == {"user-agent": "custom-agent/1.0"}


@pytest.mark.parametrize(
    "client_type",
    [OpenAICompatibleLLMClient, DeepSeekLLMClient],
)
def test_openai_compatible_requests_omit_disabled_tool_parameters(client_type):
    client = client_type(
        ModelInfo(
            model_type=ModelType.LLM,
            model_id="test-model",
            provider_id="test-provider",
            provider_name="Test Provider",
        )
    )
    request = LLMRequest(messages=[{"role": "user", "content": "ping"}])

    kwargs = client._build_request_kwargs(request)

    assert kwargs["tools"] is NOT_GIVEN
    assert kwargs["tool_choice"] is NOT_GIVEN
