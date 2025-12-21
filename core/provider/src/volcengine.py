from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import json
from typing import Optional

from core.logging_manager import get_logger
from ..provider import LLMProvider, ImageProvider
from .openai_provider import OpenAIProvider, OpenAIImageProvider
from ..llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType
from ..image_result import ImageResult

logger = get_logger("provider", "purple")
tool_logger = get_logger("tool_use", "orange")


class VolcLLMProvider(OpenAIProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)


class VolcImageProvider(OpenAIImageProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def image_to_image(self, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        if url:
            ref_img = url
        elif base64:
            ref_img = f"data:image/type;base64,{base64}"
        else:
            ref_img = None

        client = AsyncOpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=self.provider_config.get("api_key", ""),
        )
        images_response = await client.images.generate(
            model=self.provider_config.get("model", ""),
            prompt=prompt,
            size=self.provider_config.get("size", None),
            response_format="url",
            extra_body={
                "image": ref_img,
                "watermark": False
            }
        )
        return ImageResult(images_response.data[0].url)
