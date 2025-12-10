from abc import abstractmethod, ABC
from typing import List
from .llm_model import LLMModel
import asyncio


class BaseProvider(ABC):
    def __init__(self, provider_id, provider_name, provider_config):
        self.provider_id: str = provider_id
        self.provider_name: str = provider_name
        self.provider_config: dict = provider_config


class LLMProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    @abstractmethod
    def get_keys(self) -> List[str]:
        return self.provider_config.get("keys", [])

    def get_models(self) -> List[LLMModel]:
        pass


class TTSProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    @abstractmethod
    async def get_text(self):
        pass


class STTProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def get_audio(self):
        pass


class EmbeddingProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)


class RerankProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)


class ImageProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)


class VideoProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
