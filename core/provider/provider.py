from abc import abstractmethod, ABC
from enum import Enum, auto
from dataclasses import dataclass, field
from typing import List, Optional
import asyncio

from .llm_model import LLMRequest, LLMResponse
from .image_result import ImageResult


class ModelType(Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    IMAGE = "image"
    VIDEO = "video"


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
    model_type: ModelType

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


class BaseModelClient:
    type: ModelType

    def __init__(self, model: ModelInfo):
        self.model = model


class LLMModelClient(BaseModelClient):
    type = ModelType.LLM

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        pass


class TTSModelClient(BaseModelClient):
    type = ModelType.TTS

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs):
        pass


class STTModelClient(BaseModelClient):
    type = ModelType.STT

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def speech_to_text(self, audio_base64: str, **kwargs):
        pass


class ImageModelClient(BaseModelClient):
    type = ModelType.IMAGE

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> ImageResult:
        pass

    async def image_to_image(self, prompt: str, url: Optional[str] = None,
                             base64: Optional[str] = None) -> ImageResult:
        pass


class BaseProvider(ABC):
    models: dict[ModelType, type(BaseModelClient)]

    def __init__(self, provider_id, provider_name, provider_config):
        self.provider_id: str = provider_id
        self.provider_name: str = provider_name
        self.provider_config: dict = provider_config

    def get_model_client(self, model_type: ModelType) -> BaseModelClient:
        if model_type not in self.models:
            raise ValueError(f"Model type {model_type.value} not implemented")
        return self.models[model_type]

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
