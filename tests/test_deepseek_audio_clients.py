import base64
import json
import wave
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.chat.message_elements import Record
from core.config import config_loader
from core.config.config_loader import KiraConfig
from core.provider import ModelInfo, ModelType, ProviderAPIError, ProviderManager
from core.provider.src.deepseek import model_clients
from core.provider.src.deepseek.provider import DeepSeekProvider
from webui.routes.auth import require_auth
from webui.routes.providers import ProvidersRoutes


def wav_audio() -> bytes:
    output = BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(3200))
    return output.getvalue()


def make_client(kind, provider_config=None, model_config=None):
    model = ModelInfo(
        model_type=kind,
        model_id="internal-id",
        provider_id="deepseek",
        provider_name="DeepSeek",
        provider_config={"api_key": "test-key", **(provider_config or {})},
        model_config=model_config or {},
    )
    return DeepSeekProvider.models[kind](model)


@pytest.fixture
def mock_http(monkeypatch):
    async_client = httpx.AsyncClient

    def install(handler):
        def create_client(**kwargs):
            return async_client(transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(model_clients.httpx, "AsyncClient", create_client)

    return install


@pytest.mark.asyncio
@pytest.mark.parametrize("use_ogg", [False, True])
async def test_deepseek_asr_uploads_audio_without_model_or_language(mock_http, use_ogg):
    audio = b"OggS" + bytes(22) + b"\x01\x13OpusHead" + bytes(11) if use_ogg else wav_audio()
    extension = b"ogg" if use_ogg else b"wav"

    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == "https://api.deepseek.com/v1/tools/asr"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["Content-Type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"; filename="speech.' + extension + b'"' in request.content
        assert b"Content-Type: audio/" + extension in request.content
        assert audio in request.content
        assert b'name="model"' not in request.content
        assert b'name="language"' not in request.content
        return httpx.Response(200, json={"text": "转写结果", "duration_ms": 100})

    mock_http(handle)
    client = make_client(ModelType.STT, {"section_advanced": {"headers": {"Content-Type": "application/json"}}})
    record = Record(record=base64.b64encode(audio).decode("ascii"), name="voice.bin")
    assert await client.speech_to_text(record) == "转写结果"


@pytest.mark.asyncio
async def test_deepseek_tts_uses_configured_endpoint_and_returns_wav_record(mock_http):
    audio = wav_audio()

    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == "https://proxy.example/deepseek/v1/tools/tts"
        assert request.headers["Authorization"] == "Bearer test-key"
        assert request.headers["X-Provider-Test"] == "present"
        assert request.extensions["timeout"]["read"] == 15
        assert json.loads(request.content) == {
            "text": "**你好**",
            "voice_id": "tide",
            "filter_markdown": False,
            "format": "wav",
        }
        return httpx.Response(200, content=audio, headers={"Content-Type": "audio/wav"})

    mock_http(handle)
    client = make_client(
        ModelType.TTS,
        provider_config={
            "base_url": "https://proxy.example/deepseek/v1/",
            "section_advanced": {"headers": {"X-Provider-Test": "present"}},
        },
        model_config={"voice_id": "tide", "filter_markdown": False, "timeout": 15},
    )
    record = await client.text_to_speech("**你好**")
    assert record.mime == "audio/wav"
    assert record.guess_name() == "speech.wav"
    assert base64.b64decode(await record.to_base64()) == audio


@pytest.mark.asyncio
async def test_deepseek_asr_rejects_unsupported_and_oversized_audio(mock_http, tmp_path):
    def handle(request):
        pytest.fail("Unsupported audio reached DeepSeek")

    mock_http(handle)
    client = make_client(ModelType.STT)
    with pytest.raises(ValueError, match="16-bit PCM WAV or Ogg Opus"):
        await client.speech_to_text(Record(record="base64://SUQzAA=="))

    path = tmp_path / "large.wav"
    path.write_bytes(wav_audio())
    with path.open("ab") as output:
        output.truncate(model_clients.MAX_ASR_FILE_BYTES + 1)
    with pytest.raises(ValueError, match="8 MiB"):
        await client.speech_to_text(Record(record=str(path)))


@pytest.mark.asyncio
async def test_deepseek_tts_surfaces_api_errors_and_rejects_non_audio(mock_http):
    def handle(request):
        return next(responses)

    responses = iter([
        httpx.Response(400, json={"message": "Content Exists Risk"}),
        httpx.Response(200, json={"message": "no audio"}),
    ])
    mock_http(handle)
    client = make_client(ModelType.TTS)
    with pytest.raises(ProviderAPIError, match="HTTP 400.*Content Exists Risk"):
        await client.text_to_speech("blocked text")
    with pytest.raises(ProviderAPIError, match="did not contain WAV audio"):
        await client.text_to_speech("text")


def test_deepseek_voice_models_can_be_synced_and_selected_as_defaults(mock_http, monkeypatch, tmp_path):
    monkeypatch.setattr(config_loader, "CONFIG_PATH", tmp_path / "config.json")
    for registry in ("_registry", "_schemas", "_manifests", "_manifest_dirs"):
        monkeypatch.setattr(ProviderManager, registry, {})
    ProviderManager.scan_providers(str(Path(model_clients.__file__).resolve().parents[1]))
    manager = object.__new__(ProviderManager)
    manager._providers = {}
    manager.kira_config = KiraConfig({"providers": {}, "models": {}})
    manager.generate_provider_config("DeepSeek", "deepseek")
    config = manager.kira_config["providers"]["deepseek"]
    config["provider_config"]["api_key"] = "test-key"
    manager.set_provider("deepseek", config)

    def handle(request):
        if request.url.path == "/v1/tools/tts":
            assert json.loads(request.content)["voice_id"] == "stella"
            return httpx.Response(200, content=wav_audio())
        assert request.url.path == "/v1/tools/asr"
        wav_start = request.content.index(b"RIFF")
        assert request.content[wav_start + 8:wav_start + 12] == b"WAVE"
        return httpx.Response(200, json={"text": ""})

    mock_http(handle)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "test"
    ProvidersRoutes(app, SimpleNamespace(kira_config=manager.kira_config, provider_manager=manager)).register()

    with TestClient(app) as api:
        provider_url = "/api/providers/deepseek"
        response = api.get(provider_url)
        assert response.status_code == 200
        assert set(response.json()["supported_model_types"]) == {"llm", "tts", "stt"}

        for kind, name in (("tts", "deepseek-tts"), ("stt", "deepseek-asr")):
            catalog = api.get(f"{provider_url}/remote-models", params={"model_type": kind})
            assert catalog.json() == {"models": [{"id": name}]}
            sync = api.post(f"{provider_url}/models/sync/{kind}", json={"add_ids": [name], "delete_ids": []})
            assert sync.json() == {"added": 1, "removed": 0, "errors": []}
            models = api.get(f"{provider_url}/models").json()
            model_id, entry = next(iter(models[kind].items()))
            assert entry["model_name"] == name
            manager.kira_config["models"][f"default_{kind}"] = f"deepseek:{model_id}"
            health = api.post(f"{provider_url}/models/{kind}/{model_id}/health-check")
            assert health.json()["success"], health.json()

    assert isinstance(manager.get_default_tts(), model_clients.DeepSeekTTSClient)
    assert isinstance(manager.get_default_stt(), model_clients.DeepSeekSTTClient)
