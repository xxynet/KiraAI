from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError, NOT_GIVEN 
import base64
import time
from typing import Optional

from core.provider import ModelInfo
from core.provider import LLMModelClient, TTSModelClient, ImageModelClient, EmbeddingModelClient
from core.provider.llm_model import LLMRequest, LLMResponse
from core.chat.message_elements import Record

class OpenAICompatibleLLMClient(LLMModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        section_advanced = self.model.provider_config.get("section_advanced")
        default_headers = section_advanced.get("headers", {}) if isinstance(section_advanced, dict) else {}
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=default_headers
        )
        try:
            start_time = time.perf_counter()
            temperature = self.model.model_config.get("temperature") if self.model.model_config else None
            timeout = self.model.model_config.get("timeout") if self.model.model_config else None
            response = await client.chat.completions.create(
                model=self.model.model_id,
                messages=request.messages,
                tools=request.tools if request.tools else None,
                tool_choice=request.tool_choice if request.tool_choice != "none" else None,
                temperature=temperature if temperature is not None else NOT_GIVEN,
                timeout=timeout if timeout is not None else NOT_GIVEN
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

                if response.usage:
                    llm_resp.input_tokens = response.usage.prompt_tokens
                    llm_resp.output_tokens = response.usage.completion_tokens
                    # cached tokens (prompt_tokens_details.cached_tokens)
                    prompt_details = getattr(response.usage, "prompt_tokens_details", None)
                    if prompt_details:
                        llm_resp.cached_tokens = getattr(prompt_details, "cached_tokens", None)
            return llm_resp
        except APIStatusError as e:
            # the model does not support function calling etc.
            # 403 Authorization failed (api key error)
            raise
        except APITimeoutError as e:
            raise
        except APIConnectionError as e:
            # APIConnectionError: Connection error. (base_url error)
            raise
        except Exception as e:
            raise


class OpenAICompatibleTTSClient(TTSModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs) -> Record:
        section_advanced = self.model.provider_config.get("section_advanced")
        default_headers = section_advanced.get("headers", {}) if isinstance(section_advanced, dict) else {}
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=default_headers
        )

        async with client.audio.speech.with_streaming_response.create(
                model=self.model.model_id,
                voice=self.model.model_config.get("voice_name", ""),
                input=text,
                response_format="mp3"
        ) as response:
            audio_bytes = b""
            async for chunk in response.iter_bytes():
                audio_bytes += chunk

        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
        return Record(record=b64_str)