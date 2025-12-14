from abc import abstractmethod, ABC
from typing import List
from .llm_model import LLMModel, LLMRequest, LLMResponse
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

    @abstractmethod
    async def chat(self, request: LLMRequest) -> LLMResponse:
        pass


class TTSProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    @abstractmethod
    async def text_to_speech(self, text: str) -> str:
        """将文本转换为语音
        
        Args:
            text: 要转换的文本
            
        Returns:
            base64 编码的音频数据
        """
        pass


class STTProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    @abstractmethod
    async def speech_to_text(self, audio_base64: str) -> str:
        """将语音转换为文本
        
        Args:
            audio_base64: base64 编码的音频数据
            
        Returns:
            转换后的文本
        """
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

    @abstractmethod
    async def generate_image(self, prompt):
        pass


class VideoProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
