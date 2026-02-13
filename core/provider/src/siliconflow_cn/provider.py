from core.provider import BaseProvider, ModelType

from .model_clients import (SiliconflowLLMClient, SiliconflowImageClient,
                            SiliconflowTTSClient, SiliconflowSTTClient,
                            SiliconflowEmbeddingClient)


class SiliconflowCNProvider(BaseProvider):
    models = {
        ModelType.LLM: SiliconflowLLMClient,
        ModelType.IMAGE: SiliconflowImageClient,
        ModelType.TTS: SiliconflowTTSClient,
        ModelType.STT: SiliconflowSTTClient,
        ModelType.EMBEDDING: SiliconflowEmbeddingClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
