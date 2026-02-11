from core.provider import BaseProvider, ModelType

from .model_clients import VolcengineLLMClient, VolcengineImageClient


class VolcengineProvider(BaseProvider):
    models = {
        ModelType.LLM: VolcengineLLMClient,
        ModelType.IMAGE: VolcengineImageClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
