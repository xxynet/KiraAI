"""Regression tests: provider failures must raise instead of returning empty.

Embedding/TTS/STT/rerank clients used to swallow every exception and return
``[]`` / ``None`` / ``""``, which made ``health_check`` report success on a
wrong API key and let the memory pipeline consume a truncated result set.
"""

from types import SimpleNamespace

import aiohttp
import httpx
import pytest
from openai import APIConnectionError

from core.chat.message_elements import Record
from core.provider import (
    EmbeddingModelClient,
    ModelInfo,
    ModelType,
    ProviderAPIError,
    ProviderManager,
)
from core.provider.src.aliyun_bailian import model_clients as bailian_clients
from core.provider.src.gptsovits import model_clients as gptsovits_clients
from core.provider.src.modelscope import model_clients as modelscope_clients
from core.provider.src.openai import model_clients as openai_clients
from core.provider.src.siliconflow_cn import model_clients as siliconflow_clients
from core.provider.src.volcengine import model_clients as volcengine_clients


def embedding_model_info(model_type_module_name: str) -> ModelInfo:
    return ModelInfo(
        model_type=ModelType.EMBEDDING,
        model_id=f"{model_type_module_name}-embedding",
        provider_id="provider-test",
        provider_name="Provider Test",
        provider_config={"api_key": "wrong-key", "base_url": "https://api.example.com"},
        model_config={"timeout": 5},
    )


class FailingOpenAI:
    """Stands in for AsyncOpenAI and fails the way an unreachable API does."""

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.embeddings = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        raise APIConnectionError(
            request=httpx.Request("POST", "https://api.example.com/embeddings")
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.closed = True
        return None


EMBEDDING_CASES = [
    (openai_clients, "OpenAIEmbeddingClient"),
    (volcengine_clients, "VolcengineEmbeddingClient"),
    (siliconflow_clients, "SiliconflowEmbeddingClient"),
    (modelscope_clients, "ModelScopeEmbeddingClient"),
    (bailian_clients, "BailianEmbeddingClient"),
]


@pytest.mark.anyio
@pytest.mark.parametrize("module,client_name", EMBEDDING_CASES)
async def test_embedding_failures_raise_provider_api_error(
    monkeypatch, module, client_name
):
    clients: list[FailingOpenAI] = []

    def build_failing_client(*args, **kwargs):
        client = FailingOpenAI()
        clients.append(client)
        return client

    monkeypatch.setattr(module, "AsyncOpenAI", build_failing_client)
    client = getattr(module, client_name)(embedding_model_info(module.__name__))

    with pytest.raises(ProviderAPIError):
        await client.embed(["ping"])

    assert clients and clients[0].closed is True


@pytest.mark.anyio
@pytest.mark.parametrize("module,client_name", EMBEDDING_CASES)
async def test_embedding_still_short_circuits_empty_input(
    monkeypatch, module, client_name
):
    monkeypatch.setattr(module, "AsyncOpenAI", FailingOpenAI)
    client = getattr(module, client_name)(embedding_model_info(module.__name__))

    assert await client.embed([]) == []


class FailingSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def post(self, *args, **kwargs):
        raise aiohttp.ClientError("connection refused")


@pytest.mark.anyio
async def test_gptsovits_tts_network_failure_raises(monkeypatch):
    monkeypatch.setattr(gptsovits_clients.aiohttp, "ClientSession", FailingSession)
    client = gptsovits_clients.GptSovitsTTSClient(
        ModelInfo(
            model_type=ModelType.TTS,
            model_id="gpt-sovits",
            provider_id="gptsovits-test",
            provider_name="GPT-SoVITS Test",
            provider_config={"base_url": "http://127.0.0.1:9880/tts"},
            model_config={},
        )
    )

    with pytest.raises(ProviderAPIError):
        await client.text_to_speech("ping")


@pytest.mark.anyio
async def test_bailian_tts_without_api_key_raises():
    client = bailian_clients.BailianCosyVoiceTTSClient(
        ModelInfo(
            model_type=ModelType.TTS,
            model_id="cosyvoice-v2",
            provider_id="bailian-test",
            provider_name="Bailian Test",
            provider_config={},
            model_config={"voice": "longanyang"},
        )
    )

    with pytest.raises(ProviderAPIError):
        await client.text_to_speech("ping")


@pytest.mark.anyio
async def test_bailian_stt_without_api_key_raises():
    client = bailian_clients.BailianSTTClient(
        ModelInfo(
            model_type=ModelType.STT,
            model_id="paraformer-realtime-v2",
            provider_id="bailian-test",
            provider_name="Bailian Test",
            provider_config={},
            model_config={},
        )
    )

    with pytest.raises(ProviderAPIError):
        await client.speech_to_text(Record(record="aGVsbG8="))


@pytest.mark.anyio
async def test_bailian_rerank_without_api_key_raises():
    client = bailian_clients.BailianRerankClient(
        ModelInfo(
            model_type=ModelType.RERANK,
            model_id="gte-rerank-v2",
            provider_id="bailian-test",
            provider_name="Bailian Test",
            provider_config={},
            model_config={},
        )
    )

    with pytest.raises(ProviderAPIError):
        await client.rerank("ping", ["ping"])


class RaisingEmbeddingClient(EmbeddingModelClient):
    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise ProviderAPIError("Embedding request failed: unreachable")


@pytest.mark.anyio
async def test_health_check_reports_embedding_failure(monkeypatch):
    manager = object.__new__(ProviderManager)
    monkeypatch.setattr(
        ProviderManager,
        "get_model_client",
        lambda self, *args, **kwargs: RaisingEmbeddingClient(
            embedding_model_info("health")
        ),
    )

    result = await manager.health_check("provider-test", "embedding", "any-model")

    assert result["success"] is False
    assert result["latency"] is None
    assert "unreachable" in result["error"]
