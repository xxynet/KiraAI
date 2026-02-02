from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import json
import time
from typing import Optional

from core.provider import NewBaseProvider, ProviderInfo, ModelInfo
from core.logging_manager import get_logger
from core.provider.llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType
from core.provider.image_result import ImageResult


logger = get_logger("provider", "purple")
tool_logger = get_logger("tool_use", "orange")


class OpenAIProvider(NewBaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def chat(self, model: ModelInfo,  request: LLMRequest) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=model.provider_config.get("api_key", ""),
            base_url=model.provider_config.get("base_url", "")
        )
        try:
            start_time = time.perf_counter()
            response = await client.chat.completions.create(
                model=model.model_id,
                messages=request.messages,
                tools=request.tools if request.tools else None,
                tool_choice=request.tool_choice if request.tool_choice != "none" else None
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
            # the model does not support function calling etc.
            # 403 Authorization failed (api key error)
            logger.error(f"APIStatusError: {e}")
        except APITimeoutError as e:
            logger.error(f"APITimeoutError: {e}")
        except APIConnectionError as e:
            # APIConnectionError: Connection error.(base_url error)
            logger.error(f"APIConnectionError: {e}")

    async def text_to_image(self, model: ModelInfo, prompt) -> ImageResult:
        client = AsyncOpenAI(
            base_url=model.provider_config.get("base_url", ""),
            api_key=model.provider_config.get("api_key", ""),
        )
        image_size = model.model_config.get("size", None)
        images_response = await client.images.generate(
            model=model.model_id,
            prompt=prompt,
            size=image_size if image_size else None,
            response_format="url",
            extra_body={
                "watermark": False,
            },
        )

        return ImageResult(images_response.data[0].url)

    async def image_to_image(self, model: ModelInfo, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        pass
