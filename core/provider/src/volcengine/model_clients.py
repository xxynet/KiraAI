from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import time
from typing import Optional

from core.provider import ModelInfo, LLMModelClient, ImageModelClient, EmbeddingModelClient
from core.logging_manager import get_logger
from core.provider.llm_model import LLMRequest, LLMResponse
from core.provider.image_result import ImageResult

logger = get_logger("provider", "purple")


class VolcengineLLMClient(LLMModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", "")
        )
        try:
            start_time = time.perf_counter()
            temperature = self.model.model_config.get("temperature") if self.model.model_config else None
            response = await client.chat.completions.create(
                model=self.model.model_id,
                messages=request.messages,
                tools=request.tools if request.tools else None,
                tool_choice=request.tool_choice if request.tool_choice != "none" else None,
                temperature=temperature if temperature is not None else 1
            )
            end_time = time.perf_counter()
            llm_resp = LLMResponse("")
            llm_resp.time_consumed = round(end_time - start_time, 2)
            if response.choices:
                message = response.choices[0].message

                if message.tool_calls:

                    for tool_call in message.tool_calls:
                        name = tool_call.function.name

                        llm_resp.tool_calls.append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": tool_call.function.arguments
                            }
                        })

                content = message.content if message.content else ""
                reasoning_content = getattr(message, "reasoning_content", "")
                llm_resp.text_response = content
                llm_resp.reasoning_content = reasoning_content
                llm_resp.input_tokens = response.usage.prompt_tokens
                llm_resp.output_tokens = response.usage.completion_tokens
            return llm_resp
        except APIStatusError as e:
            logger.error(f"APIStatusError: {e}")
            return LLMResponse(text_response=f"[Error] APIStatusError: {e}")
        except APITimeoutError as e:
            logger.error(f"APITimeoutError: {e}")
            return LLMResponse(text_response=f"[Error] APITimeoutError: {e}")
        except APIConnectionError as e:
            logger.error(f"APIConnectionError: {e}")
            return LLMResponse(text_response=f"[Error] APIConnectionError: {e}")
        except Exception as e:
            logger.error(f"Error: {e}")
            return LLMResponse(text_response=f"[Error] {e}")


class VolcengineImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> ImageResult:
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

        return ImageResult(images_response.data[0].url)

    async def image_to_image(self, prompt: str, url: Optional[str] = None,
                             base64: Optional[str] = None) -> ImageResult:
        if url:
            ref_img = url
        elif base64:
            ref_img = base64
        else:
            ref_img = None

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
                "image": ref_img,
                "watermark": False
            }
        )
        return ImageResult(images_response.data[0].url)


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
