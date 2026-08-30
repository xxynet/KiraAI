from core.provider import ModelInfo, ModelType
from core.utils.model_clients import OpenAICompatibleTTSClient


def test_openai_compatible_tts_sends_extra_body_from_advanced_settings():
    client = OpenAICompatibleTTSClient(
        ModelInfo(
            model_type=ModelType.TTS,
            model_id="tts-model",
            provider_id="test-provider",
            provider_name="Test Provider",
            model_config={
                "voice_name": "alloy",
                "section_advanced": {"extra_body": {"speed": 1.2}},
            },
        )
    )

    assert client._build_request_kwargs("Hello") == {
        "model": "tts-model",
        "voice": "alloy",
        "input": "Hello",
        "response_format": "mp3",
        "extra_body": {"speed": 1.2},
    }


def test_openai_compatible_tts_omits_empty_extra_body():
    client = OpenAICompatibleTTSClient(
        ModelInfo(
            model_type=ModelType.TTS,
            model_id="tts-model",
            provider_id="test-provider",
            provider_name="Test Provider",
            model_config={"section_advanced": {"extra_body": {}}},
        )
    )

    assert "extra_body" not in client._build_request_kwargs("Hello")
