from core.provider import ModelType, BaseProvider

from .model_clients import GptSovitsTTSClient


class GptSovitsProvider(BaseProvider):
    models = {
        ModelType.TTS: GptSovitsTTSClient,
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def get_llm_list(self) -> list[dict]:
        """
        Return available TTS models for GptSovits.
        GSV API does not expose a model listing endpoint, so we return a static list.
        """
        models = [
            {
                "id": "gptsovits",
                "name": "GPT-SoVITS",
                "description": "GPT-SoVITS TTS 模型，适用于v2及以上的版本",
            },
        ]
        return models
