from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import time
import asyncio
import httpx
import base64

from core.provider import ModelInfo
from core.provider import LLMModelClient, ImageModelClient, EmbeddingModelClient
from core.provider.llm_model import LLMRequest, LLMResponse
from core.logging_manager import get_logger
from core.chat.message_elements import Image
from core.utils.model_clients import OpenAICompatibleLLMClient

logger = get_logger("provider", "purple")


class ImageGenerationTimeoutError(TimeoutError):
    def __init__(self, message: str = "Image generation timed out"):
        super().__init__(message)


class ModelScopeLLMClient(OpenAICompatibleLLMClient):
    pass


class ModelScopeImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> Image:
        base_url = "https://api-inference.modelscope.cn/"
        api_key = self.model.provider_config.get("api_key", "")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        config = self.model.model_config or {}
        raw_timeout = config.get("timeout", 30)
        try:
            timeout_seconds = int(raw_timeout)
        except (TypeError, ValueError):
            timeout_seconds = 30

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            # 提交生成任务
            resp = await client.post(
                f"{base_url}v1/images/generations",
                headers={**headers, "X-ModelScope-Async-Mode": "true"},
                json={
                    "model": self.model.model_id,
                    "prompt": prompt,
                },
            )
            resp.raise_for_status()
            task_id = resp.json()["task_id"]

            start_time = time.time()

            # 轮询任务状态
            while time.time() - start_time < timeout_seconds:
                result = await client.get(
                    f"{base_url}v1/tasks/{task_id}",
                    headers={**headers, "X-ModelScope-Task-Type": "image_generation"},
                )
                result.raise_for_status()
                data = result.json()

                status = data.get("task_status")

                if status == "SUCCEED":
                    image_url = data["output_images"][0]
                    image_resp = await client.get(image_url)
                    image_resp.raise_for_status()

                    image_base64 = base64.b64encode(image_resp.content).decode("utf-8")
                    return Image(image=image_base64)

                if status == "FAILED":
                    raise RuntimeError("Image Generation Failed")

                await asyncio.sleep(2)

        raise ImageGenerationTimeoutError()


class ModelScopeEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model_cfg = self.model.model_config or {}
        embedding_cfg = model_cfg.get("embedding", {}) if isinstance(model_cfg, dict) else {}

        timeout_sec = embedding_cfg.get("timeout", model_cfg.get("timeout", 60) if isinstance(model_cfg, dict) else 60)
        slow_threshold = embedding_cfg.get(
            "slow_request_threshold",
            model_cfg.get("slow_request_threshold", None) if isinstance(model_cfg, dict) else None
        )

        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url="https://api-inference.modelscope.cn/v1",
            timeout=timeout_sec
        )
        try:
            start_time = time.perf_counter()
            response = await client.embeddings.create(
                model=self.model.model_id,
                input=texts
            )
            elapsed = round(time.perf_counter() - start_time, 2)
            if slow_threshold is not None and elapsed > slow_threshold:
                logger.warning(f"Slow embedding request: {elapsed}s (threshold: {slow_threshold}s, model: {self.model.model_id})")
            return [item.embedding for item in response.data]
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Embedding API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return []