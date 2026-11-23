import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from core.provider import ModelInfo, ModelType, ProviderAPIError
from core.provider.openai_compatible import OpenAICompatibleSTTClient
from core.provider.src.openai.model_clients import OpenAIImageClient
from core.provider.src.volcengine.model_clients import VolcengineImageClient


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["_text_to_image_via_chat", "_image_to_image_via_chat"])
async def test_image_chat_rejects_text_response(method, monkeypatch):
    client = OpenAIImageClient(ModelInfo(
        model_type=ModelType.IMAGE, model_id="image", model_name="image",
        provider_id="test", provider_name="test",
    ))
    body = "<html>image gateway failed</html>"
    create = AsyncMock(return_value=body)
    monkeypatch.setattr(client, "_build_client", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    ))
    args = ("draw", []) if method == "_image_to_image_via_chat" else ("draw",)
    with pytest.raises(ProviderAPIError) as caught:
        await getattr(client, method)(*args)
    assert body in str(caught.value)


@pytest.mark.parametrize("body", [
    "image upstream failure", None, SimpleNamespace(data=None),
])
def test_image_generation_and_edit_reject_invalid_response(body):
    with pytest.raises(ProviderAPIError) as caught:
        OpenAIImageClient._image_from_response(body, "Image generation")
    assert repr(body) in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("editing", [False, True])
async def test_volcengine_image_rejects_text_response(editing, monkeypatch):
    module = importlib.import_module("core.provider.src.volcengine.model_clients")
    client = VolcengineImageClient(ModelInfo(
        model_type=ModelType.IMAGE, model_id="image", model_name="image",
        provider_id="test", provider_name="test", provider_config={}, model_config={},
    ))
    body = "image gateway failure"
    sdk = SimpleNamespace(images=SimpleNamespace(generate=AsyncMock(return_value=body)))
    monkeypatch.setattr(module, "AsyncOpenAI", lambda **kwargs: sdk)
    with pytest.raises(ProviderAPIError) as caught:
        if editing:
            await client.image_to_image("draw", [])
        else:
            await client.text_to_image("draw")
    assert body in str(caught.value)


@pytest.mark.asyncio
async def test_stt_rejects_text_response(monkeypatch):
    client = OpenAICompatibleSTTClient(ModelInfo(
        model_type=ModelType.STT, model_id="stt", model_name="stt",
        provider_id="test", provider_name="test",
    ))
    body = "transcription gateway failed"
    monkeypatch.setattr(client, "_build_client", lambda: SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=AsyncMock(return_value=body))),
    ))
    record = SimpleNamespace(to_path=AsyncMock(return_value="voice.wav"))
    with pytest.raises(ProviderAPIError) as caught:
        await client.speech_to_text(record)
    assert body in str(caught.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(("provider", "class_name"), [
    ("openai", "OpenAIEmbeddingClient"),
    ("volcengine", "VolcengineEmbeddingClient"),
    ("siliconflow_cn", "SiliconflowEmbeddingClient"),
    ("modelscope", "ModelScopeEmbeddingClient"),
    ("aliyun_bailian", "BailianEmbeddingClient"),
])
@pytest.mark.parametrize("valid", [False, True])
async def test_embedding_response_validation_preserves_error_and_success_paths(
    monkeypatch, provider, class_name, valid,
):
    module = importlib.import_module(f"core.provider.src.{provider}.model_clients")
    client = getattr(module, class_name)(ModelInfo(
        model_type=ModelType.EMBEDDING, model_id="embedding", model_name="embedding",
        provider_id="test", provider_name="test", provider_config={}, model_config={},
    ))
    body = SimpleNamespace(data=[SimpleNamespace(embedding=[0.1, 0.2])]) if valid else "embedding gateway failed"
    sdk = MagicMock()
    sdk.embeddings.create = AsyncMock(return_value=body)
    sdk.__aenter__ = AsyncMock(return_value=sdk)
    sdk.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(module, "AsyncOpenAI", lambda **kwargs: sdk)
    error = Mock()
    monkeypatch.setattr(module.logger, "error", error)

    result = await client.embed(["hello"])

    if valid:
        assert result == [[0.1, 0.2]]
        error.assert_not_called()
    else:
        assert result == []
        error.assert_called_once()
        message = error.call_args.args[0]
        assert "Invalid OpenAI-compatible API response" in message
        assert body in message
