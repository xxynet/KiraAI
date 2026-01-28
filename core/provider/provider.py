from abc import abstractmethod, ABC
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional
import asyncio

from .llm_model import LLMModel, LLMRequest, LLMResponse
from .image_result import ImageResult


class ModelType(Enum):
    LLM: auto()
    TTS: auto()
    STT: auto()
    EMBEDDING: auto()
    RERANK: auto()
    IMAGE: auto()
    VIDEO: auto()


@dataclass
class ProviderInfo:
    """Dataclass describing info of a provider"""

    """Provider instance name"""
    provider_name: str

    """Unique provider ID"""
    provider_id: str

    """Provider type, e.g. OpenAI"""
    provider_type: str

    """Provider instance config"""
    provider_config: dict


@dataclass
class ModelInfo:
    """Dataclass describing info of a model"""

    """Model type, e.g. llm, tts, image"""
    model_type: str

    """Model ID defined by your provider, e.g. gpt-3.5-turbo"""
    model_id: str

    """Provider instance ID"""
    provider_id: str

    """Provider name defined by user"""
    provider_name: str

    """Provider config"""
    provider_config: dict = field(default_factory=dict)

    """Model instance config"""
    model_config: dict = field(default_factory=dict)


class NewBaseProvider(ABC):
    def __init__(self, provider_id, provider_name, provider_config):
        self.provider_id: str = provider_id
        self.provider_name: str = provider_name
        self.provider_config: dict = provider_config

    async def chat(self, model: ModelInfo,  request: LLMRequest) -> LLMResponse:
        """

        :param model: ModelInfo dataclass that describes full info of the model
        :param request: LLMRequest instance
        :return: LLMResponse instance
        """
        pass

    async def text_to_speech(self, model: ModelInfo, text: str) -> str:
        pass

    async def speech_to_text(self, model: ModelInfo, audio_base64: str) -> str:
        pass

    async def text_to_image(self, model: ModelInfo, prompt) -> ImageResult:
        pass

    async def image_to_image(self, model: ModelInfo, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        pass


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
    async def text_to_image(self, prompt) -> ImageResult:
        pass

    async def image_to_image(self, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        pass


class VideoProvider(BaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)
