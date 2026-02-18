from core.provider import BaseProvider, ModelType

from .model_clients import VolcengineLLMClient, VolcengineImageClient, VolcengineEmbeddingClient


class VolcengineProvider(BaseProvider):
    models = {
        ModelType.LLM: VolcengineLLMClient,
        ModelType.IMAGE: VolcengineImageClient,
        ModelType.EMBEDDING: VolcengineEmbeddingClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
