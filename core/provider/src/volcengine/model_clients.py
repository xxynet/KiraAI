from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import time
import httpx
from typing import Optional, Union

from core.provider import ModelInfo, ImageModelClient, VideoModelClient, EmbeddingModelClient, ProviderAPIError
from core.logging_manager import get_logger
from core.provider.llm_model import LLMRequest, LLMResponse
from core.chat.message_elements import Image, Video
from core.utils.model_clients import OpenAICompatibleLLMClient

logger = get_logger("provider", "purple")

# Volcengine video jobs (Seedance etc.) usually take 1-5 minutes
DEFAULT_VIDEO_TIMEOUT = 300
DEFAULT_VIDEO_RATIO = "16:9"
VIDEO_POLL_INTERVAL = 2


def _first_image_url(images_response, label: str) -> str:
    """Read the first image URL, surfacing empty responses instead of TypeError."""
    data = getattr(images_response, "data", None)
    url = data[0].url if data else None
    if not url:
        raise ValueError(f"{label} API returned no image url: {images_response}")
    return url


class VolcengineLLMClient(OpenAICompatibleLLMClient):
    pass


class VolcengineImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> Image:
        image_size = self.model.model_config.get("size", None)
        async with AsyncOpenAI(
            base_url=self.model.provider_config.get("base_url", ""),
            api_key=self.model.provider_config.get("api_key", ""),
        ) as client:
            images_response = await client.images.generate(
                model=self.model.model_id,
                prompt=prompt,
                size=image_size if image_size else None,
                response_format="url",
                extra_body={
                    "watermark": False,
                },
            )

        return Image(image=_first_image_url(images_response, "Image generation"))

    async def image_to_image(self, prompt: str, image: Union[Image, list[Image]]) -> Image:
        if isinstance(image, Image):
            image = [image]
        ref_imgs = [await img.to_data_url() for img in image]

        image_size = self.model.model_config.get("size", None)
        async with AsyncOpenAI(
            base_url=self.model.provider_config.get("base_url", "https://ark.cn-beijing.volces.com/api/v3"),
            api_key=self.model.provider_config.get("api_key", ""),
        ) as client:
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
        return Image(image=_first_image_url(images_response, "Image-to-image generation"))


class VolcengineVideoClient(VideoModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    def _poll_timeout(self) -> float:
        """Resolve the total polling budget (seconds) from model config."""
        model_cfg = self.model.model_config or {}
        raw = model_cfg.get("timeout", DEFAULT_VIDEO_TIMEOUT)
        try:
            timeout = float(raw)
        except (TypeError, ValueError):
            logger.warning(f"Invalid video timeout '{raw}', fallback to {DEFAULT_VIDEO_TIMEOUT}")
            return float(DEFAULT_VIDEO_TIMEOUT)
        if timeout <= 0:
            logger.warning(f"Invalid non-positive video timeout '{raw}', fallback to {DEFAULT_VIDEO_TIMEOUT}")
            return float(DEFAULT_VIDEO_TIMEOUT)
        return timeout

    async def generate_video(self, prompt: str, ref: list[Image] = None, duration: int = 5, **kwargs) -> Video:
        timeout = self._poll_timeout()

        # Use a context-managed client so the connection is always closed.
        async with httpx.AsyncClient(timeout=timeout) as client:
            task_id = await self._create_task(client=client, text=prompt, ref=ref, duration=duration)

            start_ts = time.time()

            data = None

            while time.time() - start_ts < timeout:
                data = await self._get_task(client=client, task_id=task_id)

                status = data.get("status")

                if status == "succeeded":
                    url = data.get("content", {}).get("video_url")
                    if not url:
                        logger.error(f"Video generation succeeded but returned no video_url: {data}")
                        raise RuntimeError("Volcengine video generation succeeded but returned no video_url")
                    logger.info(f"火山方舟视频生成耗时：{time.time() - start_ts}")
                    return Video(file=url)

                # Break out early on terminal failure statuses instead of busy-spinning.
                if status in ("failed", "canceled", "expired"):
                    logger.error(f"Video generation failed with status '{status}': {data}")
                    raise RuntimeError(f"Volcengine video generation failed with status: {status}")

                # Avoid busy-spinning: wait before polling the task status again.
                await asyncio.sleep(VIDEO_POLL_INTERVAL)

            logger.error(f"Timeout while generating video after {timeout}s: {data}")
            raise TimeoutError(f"Volcengine video generation timed out after {timeout}s")

    @staticmethod
    async def _image_content_parts(ref: list[Image]) -> list[dict]:
        """Serialise reference images into Volcengine ``image_url`` content parts.

        A single image is the conventional first frame and carries no role.
        Multiple images are sent as reference images, which is the only role
        that accepts more than two inputs.
        """
        images = [img for img in (ref or []) if img is not None]
        if not images:
            return []
        role = None if len(images) == 1 else "reference_image"
        parts = []
        for img in images:
            url = img.image if img.image_type == "url" else await img.to_data_url()
            part = {"type": "image_url", "image_url": {"url": url}}
            if role:
                part["role"] = role
            parts.append(part)
        return parts

    async def _create_task(self, client: httpx.AsyncClient, text: str, ref: list[Image] = None, duration: int = 5) -> str:
        url = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}",
        }
        model_cfg = self.model.model_config or {}
        ratio = model_cfg.get("ratio") or DEFAULT_VIDEO_RATIO
        content = [
            {
                "type": "text",
                "text": text
            }
        ]
        content.extend(await self._image_content_parts(ref))
        json_data = {
            "model": self.model.model_id,
            "content": content,
            "ratio": ratio,
            "duration": duration,
            "watermark": False
        }

        resp = await client.post(url, headers=headers, json=json_data)
        resp.raise_for_status()

        data = resp.json()

        task_id = data.get("id")
        if not task_id:
            raise RuntimeError(f"Volcengine video task creation returned no id: {data}")
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

        try:
            start_time = time.perf_counter()
            async with AsyncOpenAI(
                api_key=self.model.provider_config.get("api_key", ""),
                base_url=self.model.provider_config.get("base_url", ""),
                timeout=validated_timeout
            ) as client:
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
            raise ProviderAPIError(f"Embedding request failed: {e}") from e
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise ProviderAPIError(f"Embedding request failed: {e}") from e
