from core.provider import BaseProvider, ModelType

from .model_clients import ModelScopeLLMClient, ModelScopeImageClient, ModelScopeEmbeddingClient


class ModelScopeProvider(BaseProvider):
    models = {
        ModelType.LLM: ModelScopeLLMClient,
        ModelType.IMAGE: ModelScopeImageClient,
        ModelType.EMBEDDING: ModelScopeEmbeddingClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
