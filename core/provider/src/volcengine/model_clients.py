from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import time
import httpx
from typing import Optional, Union

from core.provider import ModelInfo, ImageModelClient, VideoModelClient, EmbeddingModelClient
from core.logging_manager import get_logger
from core.provider.llm_model import LLMRequest, LLMResponse
from core.chat.message_elements import Image, Video
from core.utils.model_clients import OpenAICompatibleLLMClient

logger = get_logger("provider", "purple")


class VolcengineLLMClient(OpenAICompatibleLLMClient):
    pass


class VolcengineImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> Image:
        client = AsyncOpenAI(
            base_url=self.model.provider_config.get("base_url", ""),
            api_key=self.model.provider_config.get("api_key", ""),
        )
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

    async def image_to_image(self, prompt: str, image: Union[Image, list[Image]]) -> Image:
        if isinstance(image, Image):
            image = [image]
        ref_imgs = [await img.to_data_url() for img in image]

        client = AsyncOpenAI(
            base_url=self.model.provider_config.get("base_url", "https://ark.cn-beijing.volces.com/api/v3"),
            api_key=self.model.provider_config.get("api_key", ""),
        )
        image_size = self.model.model_config.get("size", None)
        images_response = await client.images.generate(
            model=self.model.model_id,
            prompt=prompt,
            size=image_size if image_size else None,
            response_format="url",
            extra_body={
                "image": ref_imgs,
                "watermark": False
            }
        )
        return Image(image=images_response.data[0].url)


class VolcengineVideoClient(VideoModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def generate_video(self, prompt: str, ref: list[Image] = None, duration: int = 5, **kwargs) -> Video:
        # Use a context-managed client so the connection is always closed.
        async with httpx.AsyncClient(timeout=30) as client:
            task_id = await self._create_task(client=client, text=prompt, ref=ref, duration=duration)

            start_ts = time.time()

            data = None

            while time.time() - start_ts < 30:
                data = await self._get_task(client=client, task_id=task_id)

                status = data.get("status")

                if status == "succeeded":
                    url = data.get("content", {}).get("video_url")
                    logger.info(f"火山方舟视频生成耗时：{time.time() - start_ts}")
                    return Video(file=url)

                # Break out early on terminal failure statuses instead of busy-spinning.
                if status in ("failed", "canceled", "expired"):
                    logger.error(f"Video generation failed with status '{status}': {data}")
                    raise RuntimeError(f"Volcengine video generation failed with status: {status}")

                # Avoid busy-spinning: wait before polling the task status again.
                await asyncio.sleep(2)

            logger.error(f"Timeout while generating video: {data}")

    async def _create_task(self, client: httpx.AsyncClient, text: str, ref: list[Image] = None, duration: int = 5) -> str:
        url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}",
        }
        json_data = {
            "model": self.model.model_id,
            "content": [
                {
                    "type": "text",
                    "text": text
                }
            ],
            "ratio": "16:9",
            "duration": duration,
            "watermark": False
        }

        resp = await client.post(url, headers=headers, json=json_data)
        resp.raise_for_status()

        data = resp.json()

        task_id = data.get("id")
        return task_id

    async def _get_task(self, client: httpx.AsyncClient, task_id: str):
        url = f"https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{task_id}"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}",
        }

        resp = await client.get(url, headers=headers)
        resp.raise_for_status()

        data = resp.json()

        return data


class VolcengineEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        model_cfg = self.model.model_config or {}
        embedding_cfg = model_cfg.get("embedding", {}) if isinstance(model_cfg, dict) else {}

        timeout_raw = embedding_cfg.get("timeout", model_cfg.get("timeout", 60) if isinstance(model_cfg, dict) else 60)
        try:
            validated_timeout = float(timeout_raw)
            if validated_timeout < 0:
                logger.warning(f"Invalid negative embedding timeout '{timeout_raw}', fallback to 60")
                validated_timeout = 60.0
        except (TypeError, ValueError):
            logger.warning(f"Invalid embedding timeout '{timeout_raw}', fallback to 60")
            validated_timeout = 60.0

        slow_threshold_raw = embedding_cfg.get(
            "slow_request_threshold",
            model_cfg.get("slow_request_threshold", 5.0) if isinstance(model_cfg, dict) else 5.0
        )
        try:
            slow_threshold = None if slow_threshold_raw is None else float(slow_threshold_raw)
        except (TypeError, ValueError):
            slow_threshold = None

        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            timeout=validated_timeout
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
