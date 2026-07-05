from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError, NOT_GIVEN
import base64
import time
from typing import AsyncGenerator, Optional

from core.provider import ModelInfo
from core.provider import LLMModelClient, TTSModelClient, ImageModelClient, EmbeddingModelClient
from core.provider.llm_model import LLMRequest, LLMResponse, LLMStreamChunk
from core.chat.message_elements import Record

class OpenAICompatibleLLMClient(LLMModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    def _build_client(self) -> AsyncOpenAI:
        """Create an AsyncOpenAI client from provider config."""
        section_advanced = self.model.provider_config.get("section_advanced")
        default_headers = section_advanced.get("headers", {}) if isinstance(section_advanced, dict) else {}
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        return AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=default_headers,
        )

    def _build_request_kwargs(self, request: LLMRequest, **overrides) -> dict:
        """Build the common kwargs dict for chat.completions.create().
        **overrides are merged on top, allowing callers to set/override
        parameters like temperature, timeout, stream, etc.
        """
        model_config = self.model.model_config if self.model.model_config else {}
        section_advanced = model_config.get("section_advanced") or {}
        temperature = section_advanced.get("temperature")
        timeout = model_config.get("timeout")
        extra_body = section_advanced.get("extra_body")
        if not isinstance(extra_body, dict) or not extra_body:
            extra_body = None
        kwargs = dict(
            model=self.model.model_id,
            messages=[m if isinstance(m, dict) else m.to_dict() for m in request.messages],
            tools=request.tools if request.tools else None,
            tool_choice=request.tool_choice if request.tool_choice != "none" else None,
            temperature=temperature if temperature is not None else NOT_GIVEN,
            timeout=timeout if timeout is not None else NOT_GIVEN,
        )
        if extra_body:
            kwargs["extra_body"] = extra_body
        kwargs.update(overrides)
        return kwargs

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        client = self._build_client()
        request_kwargs = self._build_request_kwargs(request, **kwargs)
        try:
            start_time = time.perf_counter()
            response = await client.chat.completions.create(**request_kwargs)
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

    async def chat_stream(self, request: LLMRequest, **kwargs) -> AsyncGenerator[LLMStreamChunk, None]:
        client = self._build_client()
        request_kwargs = self._build_request_kwargs(request, stream=True, **kwargs)
        request_kwargs["stream_options"] = {"include_usage": True}

        # Accumulated tool calls by index
        collected_tool_calls: dict[int, dict] = {}

        try:
            stream = await client.chat.completions.create(**request_kwargs)
            async for event in stream:
                # Usage-only event (sent by OpenAI API after the final choice chunk)
                if not event.choices:
                    if event.usage:
                        prompt_details = getattr(event.usage, "prompt_tokens_details", None)
                        cached = getattr(prompt_details, "cached_tokens", None) if prompt_details else None
                        yield LLMStreamChunk(
                            is_final=True,
                            usage={
                                "input_tokens": event.usage.prompt_tokens,
                                "output_tokens": event.usage.completion_tokens,
                                "cached_tokens": cached,
                            },
                        )
                    continue

                choice = event.choices[0]
                delta = choice.delta

                chunk = LLMStreamChunk()

                # Text content
                if delta.content:
                    chunk.delta_text = delta.content

                # Reasoning content (DeepSeek / extended models)
                reasoning = getattr(delta, "reasoning_content", "") or ""
                if reasoning:
                    chunk.delta_reasoning = reasoning

                # Tool calls — incremental fragments
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in collected_tool_calls:
                            collected_tool_calls[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.id:
                            collected_tool_calls[idx]["id"] = tc.id
                        if tc.function and tc.function.name:
                            collected_tool_calls[idx]["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            collected_tool_calls[idx]["arguments"] += tc.function.arguments

                # Finish reason
                finish_reason = choice.finish_reason
                if finish_reason:
                    chunk.is_final = True
                    chunk.finish_reason = finish_reason
                    # Assemble complete tool calls (only on final chunk)
                    for idx in sorted(collected_tool_calls):
                        tc = collected_tool_calls[idx]
                        chunk.tool_calls.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        })

                yield chunk

        except APIStatusError:
            raise
        except APITimeoutError:
            raise
        except APIConnectionError:
            raise
        except Exception:
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