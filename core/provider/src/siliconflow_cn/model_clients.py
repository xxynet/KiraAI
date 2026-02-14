from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
from io import BytesIO
from typing import Optional
import httpx
import base64
import time

from core.provider import ModelInfo
from core.provider import (LLMModelClient, ImageModelClient, TTSModelClient,
                           STTModelClient, EmbeddingModelClient)
from core.logging_manager import get_logger
from core.provider.llm_model import LLMRequest, LLMResponse
from core.provider.image_result import ImageResult

logger = get_logger("provider", "purple")


class SiliconflowLLMClient(LLMModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url="https://api.siliconflow.cn/v1"
        )
        try:
            start_time = time.perf_counter()
            response = await client.chat.completions.create(
                model=self.model.model_id,
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


class SiliconflowImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> ImageResult:
        url = "https://api.siliconflow.cn/v1/images/generations"
        payload = {
            "model": self.model.model_id,
            "prompt": prompt,
            "image_size": self.model.model_config.get("image_size", "1024x1024"),
            "batch_size": 1,
            "num_inference_steps": self.model.model_config.get("num_inference_steps", 20),
            "guidance_scale": 7.5
        }
        headers = {
            "Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}",
            "Content-Type": "application/json"
        }

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        image_url = response.json().get("images")[0].get("url")
        return ImageResult(image_url)


class SiliconflowTTSClient(TTSModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs):
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url="https://api.siliconflow.cn/v1"
        )

        async with client.audio.speech.with_streaming_response.create(
                model=self.model.model_id,
                voice=self.model.model_config.get("voice_name", ""),
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


class SiliconflowSTTClient(STTModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def speech_to_text(self, audio_base64: str, **kwargs):
        url = "https://api.siliconflow.cn/v1/audio/transcriptions"

        audio_data = base64.b64decode(audio_base64)
        audio_file = BytesIO(audio_data)
        audio_file.name = "audio.wav"

        files = {"file": audio_file}
        payload = {"model": self.model.model_id}
        headers = {"Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}"}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url,
                data=payload,
                files=files,
                headers=headers
            )
            response.raise_for_status()
        resp_json = response.json()
        return resp_json.get("text", "")


class SiliconflowEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)
        self._client: Optional[AsyncOpenAI] = None

    async def generate(self, text: str) -> list[float]:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.model.provider_config.get("api_key", ""),
                base_url="https://api.siliconflow.cn/v1"
            )
        try:
            response = await self._client.embeddings.create(
                model=self.model.model_id,
                input=text
            )
            return response.data[0].embedding
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

    async def generate_batch(self, texts: list[str]) -> list[list[float]]:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self.model.provider_config.get("api_key", ""),
                base_url="https://api.siliconflow.cn/v1"
            )
        try:
            response = await self._client.embeddings.create(
                model=self.model.model_id,
                input=texts
            )
            sorted_data = sorted(response.data, key=lambda x: x.index)
            return [item.embedding for item in sorted_data]
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