import asyncio
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import time
from typing import Optional

from core.provider import ModelInfo
from core.provider import LLMModelClient, ImageModelClient, EmbeddingModelClient
from core.provider.llm_model import LLMRequest, LLMResponse
from core.logging_manager import get_logger
from core.chat.message_elements import Image

logger = get_logger("provider", "purple")


class OpenAIImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)
        self._client: Optional[AsyncOpenAI] = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    default_headers = self.model.provider_config.get("headers", {})
                    if not isinstance(default_headers, dict) or not default_headers:
                        default_headers = None
                    self._client = AsyncOpenAI(
                        base_url=self.model.provider_config.get("base_url", ""),
                        api_key=self.model.provider_config.get("api_key", ""),
                        default_headers=default_headers
                    )
        return self._client

    async def close(self):
        async with self._client_lock:
            if self._client:
                await self._client.close()
                self._client = None

    async def text_to_image(self, prompt) -> Image:
        client = await self._get_client()
        image_size = self.model.model_config.get("size", None)
        images_response = await client.images.generate(
            model=self.model.model_id,
            prompt=prompt,
            size=image_size if image_size else None,
            response_format="url",
            extra_body={
                "watermark": False,
            },
        )

        return Image(image=images_response.data[0].url)

    async def image_to_image(self, prompt: str, url: Optional[str] = None,
                             base64: Optional[str] = None) -> Image:
        pass


class OpenAIEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)
        self._client: Optional[AsyncOpenAI] = None
        self._client_lock = asyncio.Lock()

    async def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            async with self._client_lock:
                if self._client is None:
                    timeout_sec = self.model.model_config.get("timeout", 60) if self.model.model_config else 60
                    default_headers = self.model.provider_config.get("headers", {})
                    if not isinstance(default_headers, dict) or not default_headers:
                        default_headers = None
                    self._client = AsyncOpenAI(
                        api_key=self.model.provider_config.get("api_key", ""),
                        base_url=self.model.provider_config.get("base_url", ""),
                        timeout=timeout_sec,
                        default_headers=default_headers
                    )
        return self._client

    async def close(self):
        async with self._client_lock:
            if self._client:
                await self._client.close()
                self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        slow_threshold = self.model.model_config.get("slow_request_threshold", 5.0) if self.model.model_config else 5.0

        client = await self._get_client()
        try:
            start_time = time.perf_counter()
            response = await client.embeddings.create(
                model=self.model.model_id,
                input=texts
            )
            elapsed = round(time.perf_counter() - start_time, 2)
            if elapsed > slow_threshold:
                logger.warning(f"Slow embedding request: {elapsed}s (threshold: {slow_threshold}s, model: {self.model.model_id})")
            return [item.embedding for item in response.data]
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Embedding API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return []

