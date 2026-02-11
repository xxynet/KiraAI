from core.provider import BaseProvider, ModelType

from .model_clients import ModelScopeLLMClient, ModelScopeImageClient


class ModelScopeProvider(BaseProvider):
    models = {
        ModelType.LLM: ModelScopeLLMClient,
        ModelType.IMAGE: ModelScopeImageClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
