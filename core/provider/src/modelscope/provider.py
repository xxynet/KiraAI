from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import requests
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

                    # tool_messages = [json.loads(message.model_dump_json())]
                    tool_messages = []

                    # 先添加 assistant 调用 tool 的消息
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.content if message.content else None,
                        "tool_calls": []
                    }

                    for tool_call in message.tool_calls:
                        name = tool_call.function.name

                        raw_args = tool_call.function.arguments
                        try:
                            args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError as e:
                            logger.error(f"Failed to parse function calling arguments: {e}")
                            logger.error(f"Raw args: {raw_args}")
                            args = {}
                        tool_logger.info(f"{name} args: {args}")

                        # 保存 tool_call 信息到 assistant 消息中
                        assistant_msg["tool_calls"].append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": tool_call.function.arguments
                            }
                        })

                        # Call corresponding Python function(s)
                        if request.tool_funcs and name in request.tool_funcs:
                            try:
                                result = await request.tool_funcs[name](**args)
                                tool_logger.info(f"tool_result: {result}")
                            except Exception as e:
                                result = {"error": f"Failed to call tool '{name}': {e}"}
                                tool_logger.error(f"Failed to call tool '{name}': {e}")
                        else:
                            result = {"error": f"Tool {name} not implemented"}
                            tool_logger.error(f"Tool {name} not implemented")

                        # Save tool results
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": str(result)
                        })

                    # tool_results 列表：先 assistant，后 tool
                    llm_resp.tool_results = [assistant_msg] + tool_messages

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
        base_url = 'https://api-inference.modelscope.cn/'
        api_key = model.provider_config.get("api_key", "")  # ModelScope Token

        common_headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        response = requests.post(
            f"{base_url}v1/images/generations",
            headers={**common_headers, "X-ModelScope-Async-Mode": "true"},
            data=json.dumps({
                "model": model.model_id,  # ModelScope Model-Id, required
                # "loras": "<lora-repo-id>", # optional lora(s)
                # """
                # LoRA(s) Configuration:
                # - for Single LoRA:
                # "loras": "<lora-repo-id>"
                # - for Multiple LoRAs:
                # "loras": {"<lora-repo-id1>": 0.6, "<lora-repo-id2>": 0.4}
                # - Upto 6 LoRAs, all weight-coeffients must sum to 1.0
                # """
                "prompt": prompt
            }, ensure_ascii=False).encode('utf-8')
        )

        response.raise_for_status()
        task_id = response.json()["task_id"]

        start_time = int(time.time())

        while int(time.time()) - start_time < int(str(model.model_config.get("timeout", 10))):
            result = requests.get(
                f"{base_url}v1/tasks/{task_id}",
                headers={**common_headers, "X-ModelScope-Task-Type": "image_generation"},
            )
            result.raise_for_status()
            data = result.json()

            if data["task_status"] == "SUCCEED":
                image_content = requests.get(data["output_images"][0]).content
                image_base64 = base64.b64encode(image_content).decode('utf-8')
                return ImageResult(base64=image_base64)
            elif data["task_status"] == "FAILED":
                print("Image Generation Failed.")
                break

            time.sleep(2)

        # TODO change this statement to logging
        print("timeout while generating image using model scope")
