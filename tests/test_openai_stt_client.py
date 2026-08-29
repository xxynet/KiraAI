from pathlib import Path
from types import SimpleNamespace

import pytest

from core.provider import ModelInfo, ModelType
from core.utils.model_clients import OpenAICompatibleSTTClient


class _FakeTranscriptions:
    def __init__(self):
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(text="transcribed text")


class _FakeRecord:
    def __init__(self, path: str):
        self.path = path

    async def to_path(self) -> str:
        return self.path


@pytest.mark.asyncio
async def test_openai_compatible_stt_sends_audio_path_and_optional_settings(tmp_path):
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"audio")
    transcriptions = _FakeTranscriptions()
    client = OpenAICompatibleSTTClient(
        ModelInfo(
            model_type=ModelType.STT,
            model_id="transcription-model",
            provider_id="test-provider",
            provider_name="Test Provider",
            model_config={"language": "zh", "prompt": "Names: KiraAI"},
        )
    )
    client._build_client = lambda: SimpleNamespace(
        audio=SimpleNamespace(transcriptions=transcriptions)
    )

    text = await client.speech_to_text(_FakeRecord(str(audio_path)))

    assert text == "transcribed text"
    assert transcriptions.kwargs == {
        "model": "transcription-model",
        "file": Path(audio_path),
        "language": "zh",
        "prompt": "Names: KiraAI",
    }


def test_openai_compatible_stt_omits_empty_optional_settings():
    client = OpenAICompatibleSTTClient(
        ModelInfo(
            model_type=ModelType.STT,
            model_id="transcription-model",
            provider_id="test-provider",
            provider_name="Test Provider",
            model_config=None,
        )
    )

    assert client._build_request_kwargs("C:/audio.wav") == {
        "model": "transcription-model",
        "file": Path("C:/audio.wav"),
    }
