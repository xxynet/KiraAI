from core.provider import ModelType, BaseProvider

from .model_clients import OpenAILLMClient, OpenAIImageClient


class OpenAIProvider(BaseProvider):
    models = {
        ModelType.LLM: OpenAILLMClient,
        ModelType.IMAGE: OpenAIImageClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
