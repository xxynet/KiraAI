from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal

from core.chat.message_elements import Image, Record, Video

from .decision_model import ChoiceResponse, DecisionContent, NoulResponse, ScoreResponse
from .llm_model import LLMRequest, LLMResponse, LLMStreamChunk, RerankResult


class ProviderAPIError(Exception):
    """Provider-level API error eligible for model failover."""


class ModelType(Enum):
    LLM = "llm"
    TTS = "tts"
    STT = "stt"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    IMAGE = "image"
    VIDEO = "video"
    DECISION = "decision"


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

    """Stable internal model identity"""
    model_id: str

    """Provider instance ID"""
    provider_id: str

    """Provider name defined by user"""
    provider_name: str

    """Provider config"""
    provider_config: dict = field(default_factory=dict)

    """Model instance config"""
    model_config: dict = field(default_factory=dict)

    """Upstream model identifier sent to the provider API."""
    model_name: str = ""

    def __post_init__(self):
        # Preserve direct ModelInfo construction used by older integrations.
        if not self.model_name:
            self.model_name = self.model_id


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

    async def chat_stream(self, request: LLMRequest, **kwargs) -> AsyncGenerator[LLMStreamChunk, None]:
        """Default fallback: wraps the non-streaming chat() as a single-chunk stream."""
        resp = await self.chat(request, **kwargs)
        usage = None
        if resp.input_tokens is not None:
            usage = {
                "input_tokens": resp.input_tokens,
                "output_tokens": resp.output_tokens,
                "cached_tokens": resp.cached_tokens,
            }
        yield LLMStreamChunk(
            delta_text=resp.text_response,
            delta_reasoning=resp.reasoning_content,
            tool_calls_delta=resp.tool_calls,
            is_final=True,
            finish_reason="tool_calls" if resp.tool_calls else "stop",
            usage=usage,
        )


class TTSModelClient(BaseModelClient):
    type = ModelType.TTS

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs) -> Record:
        pass


class STTModelClient(BaseModelClient):
    type = ModelType.STT

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def speech_to_text(self, record: Record, **kwargs) -> str:
        pass


class ImageModelClient(BaseModelClient):
    type = ModelType.IMAGE

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt: str) -> Image:
        pass

    async def image_to_image(self, prompt: str, image: Image | list[Image]) -> Image:
        pass


class VideoModelClient(BaseModelClient):
    type = ModelType.VIDEO

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def generate_video(self, prompt: str, ref: list[Image] | None = None, duration: int = 5, **kwargs) -> Video:
        pass


# class EmbeddingModelClient(BaseModelClient):
#     type = ModelType.EMBEDDING

#     def __init__(self, model: ModelInfo):
#         super().__init__(model)

#     async def generate(self, text: str) -> list[float]:
#         """Generate embedding vector of the given text"""
#         pass

#     async def generate_batch(self, texts: List[str]) -> List[List[float]]:
#         """Generate embedding vector batch of the given texts"""
#         pass


class EmbeddingModelClient(BaseModelClient):
    type = ModelType.EMBEDDING

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        pass


class RerankModelClient(BaseModelClient):
    type = ModelType.RERANK

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    @abstractmethod
    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
        **kwargs
    ) -> list[RerankResult]:
        """
        Return the results sorted by relevance (High -> Low)

        query: user query
        documents: Candidate documents
        top_n: Optional, truncate result
        """


class DecisionModelClient(BaseModelClient):
    type = ModelType.DECISION

    @abstractmethod
    async def noul(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: dict[Literal["true", "false"], DecisionContent | None] | None = None,
    ) -> NoulResponse:
        """Return the probability that a yes/no question is true."""
        raise NotImplementedError

    @abstractmethod
    async def choice(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: dict[str, DecisionContent | None],
    ) -> ChoiceResponse:
        """Select one option from named criteria."""
        raise NotImplementedError

    @abstractmethod
    async def score(
        self, state: DecisionContent, instructions: DecisionContent | None = None, *,
        criteria: list[DecisionContent],
    ) -> ScoreResponse:
        """Rate the state against ordered descriptive levels."""
        raise NotImplementedError


class BaseProvider(ABC):
    models: dict[ModelType, type[BaseModelClient]]

    def __init__(self, provider_id, provider_name, provider_config):
        self.provider_id: str = provider_id
        self.provider_name: str = provider_name
        self.provider_config: dict = provider_config

    def get_model_client(self, model_type: ModelType) -> BaseModelClient:
        if model_type not in self.models:
            raise ValueError(f"Model type {model_type.value} not implemented")
        return self.models[model_type]
    
    async def get_llm_list(self) -> list[dict]:
        """
        Fetch available models from the provider's remote API.
        Override in subclasses to implement remote model listing.

        Returns a list of model info dicts with at least 'id'.
        Example:
            [{"id": "gpt-4o", "name": "GPT-4o", "description": "..."}, ...]
        """
        return []
