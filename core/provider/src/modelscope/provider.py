from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import httpx
import base64
import json
import time
from typing import Optional

from core.provider import NewBaseProvider, ProviderInfo, ModelInfo
from core.logging_manager import get_logger
from core.provider.llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType
from core.provider.image_result import ImageResult


logger = get_logger("provider", "purple")
tool_logger = get_logger("tool_use", "orange")


class ModelScopeProvider(NewBaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def chat(self, model: ModelInfo,  request: LLMRequest) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=model.provider_config.get("api_key", ""),
            base_url="https://api-inference.modelscope.cn/v1"
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
        except Exception as e:
            logger.error(f"Error: {e}")

    async def text_to_image(self, model: ModelInfo, prompt) -> ImageResult:
        base_url = "https://api-inference.modelscope.cn/"
        api_key = model.provider_config.get("api_key", "")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        timeout_seconds = int(model.model_config.get("timeout", 10))

        async with httpx.AsyncClient(timeout=10) as client:
            # 提交生成任务
            resp = await client.post(
                f"{base_url}v1/images/generations",
                headers={**headers, "X-ModelScope-Async-Mode": "true"},
                json={
                    "model": model.model_id,
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
                    return ImageResult(base64=image_base64)

                if status == "FAILED":
                    raise RuntimeError("Image Generation Failed")

                await asyncio.sleep(2)

        raise TimeoutError("Image generation timed out")
