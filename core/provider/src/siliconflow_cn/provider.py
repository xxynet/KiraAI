from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
from io import BytesIO
import requests
import base64
import json
import time
from typing import Optional

from core.provider import LLMProvider, ImageProvider, NewBaseProvider, ProviderInfo, ModelInfo
from core.logging_manager import get_logger
from core.provider.llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType
from core.provider.image_result import ImageResult


logger = get_logger("provider", "purple")
tool_logger = get_logger("tool_use", "orange")


class SiliconflowCNProvider(NewBaseProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def chat(self, model: ModelInfo,  request: LLMRequest) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=model.provider_config.get("api_key", ""),
            base_url="https://api.siliconflow.cn/v1"
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
        url = "https://api.siliconflow.cn/v1/images/generations"
        payload = {
            "model": model.model_id,
            "prompt": prompt,
            "image_size": model.model_config.get("image_size", "1024x1024"),
            "batch_size": 1,
            "num_inference_steps": model.model_config.get("num_inference_steps", 20),
            "guidance_scale": 7.5
        }
        headers = {
            "Authorization": f"Bearer {model.provider_config.get('api_key', '')}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        image_url = response.json().get("images")[0].get("url")
        return ImageResult(image_url)

    async def image_to_image(self, model: ModelInfo, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        pass

    async def text_to_speech(self, model: ModelInfo, text: str) -> str:
        client = AsyncOpenAI(
            api_key=model.provider_config.get("api_key", ""),
            base_url="https://api.siliconflow.cn/v1"
        )

        async with client.audio.speech.with_streaming_response.create(
                model=model.model_id,
                voice=model.model_config.get("voice_name", ""),
                input=text,
                response_format="mp3"
        ) as response:
            # response.stream_to_file(speech_file_path)
            audio_bytes = b""
            async for chunk in response.iter_bytes():
                audio_bytes += chunk

        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
        # audio_bs64 = f"base64://{b64_str}"
        # return str(speech_file_path)
        return b64_str

    async def speech_to_text(self, model: ModelInfo, audio_base64: str) -> str:
        url = "https://api.siliconflow.cn/v1/audio/transcriptions"

        audio_data = base64.b64decode(audio_base64)
        audio_file = BytesIO(audio_data)
        audio_file.name = "audio.wav"

        files = {"file": audio_file}
        payload = {"model": model.model_id}
        headers = {"Authorization": f"Bearer {model.provider_config.get('api_key', '')}"}

        response = requests.post(url, data=payload, files=files, headers=headers)
        resp_json = response.json()
        return resp_json.get("text", "")
