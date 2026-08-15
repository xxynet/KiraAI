from openai import (
    AsyncOpenAI,
    APIStatusError,
    APITimeoutError,
    APIConnectionError,
    NOT_GIVEN,
)
import time
from typing import AsyncGenerator

from core.provider import ModelInfo, LLMModelClient
from core.provider.llm_model import LLMRequest, LLMResponse, LLMStreamChunk
from core.logging_manager import get_logger
from core.utils.model_clients import build_llm_default_headers
from core.utils.media_refs import resolve_media_references

logger = get_logger("provider", "purple")


class DeepSeekLLMClient(LLMModelClient):
    """
    DeepSeek LLM client with thinking mode (reasoning) support.

    Inherits from OpenAICompatibleLLMClient and overrides the `chat` method
    to inject DeepSeek-specific parameters:
      - thinking mode toggle via extra_body["thinking"]
      - reasoning_effort level (high / max)
      - Disables temperature when thinking mode is enabled (DeepSeek ignores it)
    """

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    def _build_client(self) -> AsyncOpenAI:
        """Create an AsyncOpenAI client from provider config."""
        return AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=build_llm_default_headers(self.model.provider_config),
        )

    def _build_request_kwargs(self, request: LLMRequest, **overrides) -> dict:
        """Build DeepSeek-specific kwargs with thinking mode support.
        **overrides are merged on top, allowing callers to set/override
        parameters like temperature, timeout, stream, etc.
        """
        model_config = self.model.model_config or {}
        thinking_enabled = model_config.get("thinking_enabled", True)
        reasoning_effort = model_config.get("reasoning_effort", "high")
        section_advanced = model_config.get("section_advanced") or {}
        user_extra_body = section_advanced.get("extra_body")

        # Build extra_body for DeepSeek thinking mode
        extra_body = {}
        if thinking_enabled:
            extra_body["thinking"] = {"type": "enabled"}
        else:
            extra_body["thinking"] = {"type": "disabled"}

        if isinstance(user_extra_body, dict) and user_extra_body:
            extra_body.update(user_extra_body)

        kwargs = dict(
            model=self.model.model_id,
            messages=[m if isinstance(m, dict) else m.to_dict() for m in request.messages],
            tools=request.tools if request.tools else NOT_GIVEN,
            tool_choice=request.tool_choice if request.tool_choice != "none" else NOT_GIVEN,
        )

        if thinking_enabled:
            kwargs["reasoning_effort"] = reasoning_effort
        else:
            temperature = section_advanced.get("temperature")
            kwargs["temperature"] = temperature if temperature is not None else 1

        if extra_body:
            kwargs["extra_body"] = extra_body

        kwargs.update(overrides)
        return kwargs

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        client = self._build_client()
        messages = await resolve_media_references(request.messages)
        request_kwargs = self._build_request_kwargs(request, messages=messages, **kwargs)

        try:
            start_time = time.perf_counter()
            response = await client.chat.completions.create(**request_kwargs)
            end_time = time.perf_counter()

            llm_resp = LLMResponse("")
            llm_resp.time_consumed = round(end_time - start_time, 2)

            if response.choices:
                message = response.choices[0].message

                # Tool calls
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
                # DeepSeek returns reasoning_content alongside content
                reasoning_content = getattr(message, "reasoning_content", "") or ""
                llm_resp.text_response = content
                llm_resp.reasoning_content = reasoning_content

                if response.usage:
                    llm_resp.input_tokens = response.usage.prompt_tokens
                    llm_resp.output_tokens = response.usage.completion_tokens
                    # DeepSeek cache hit tokens
                    llm_resp.cached_tokens = getattr(response.usage, "prompt_cache_hit_tokens", None)

            return llm_resp

        except APIStatusError:
            raise
        except APITimeoutError:
            raise
        except APIConnectionError:
            raise
        except Exception:
            raise

    async def chat_stream(self, request: LLMRequest, **kwargs) -> AsyncGenerator[LLMStreamChunk, None]:
        client = self._build_client()
        messages = await resolve_media_references(request.messages)
        request_kwargs = self._build_request_kwargs(
            request, messages=messages, stream=True, **kwargs
        )
        request_kwargs["stream_options"] = {"include_usage": True}

        try:
            stream = await client.chat.completions.create(**request_kwargs)
            async for event in stream:
                # Usage-only event (sent by OpenAI API after the final choice chunk)
                if not event.choices:
                    if event.usage:
                        yield LLMStreamChunk(
                            is_final=True,
                            usage={
                                "input_tokens": event.usage.prompt_tokens,
                                "output_tokens": event.usage.completion_tokens,
                                "cached_tokens": getattr(event.usage, "prompt_cache_hit_tokens", None),
                            },
                        )
                    continue

                choice = event.choices[0]
                delta = choice.delta

                chunk = LLMStreamChunk()

                # Text content
                if delta.content:
                    chunk.delta_text = delta.content

                # DeepSeek reasoning_content
                reasoning = getattr(delta, "reasoning_content", "") or ""
                if reasoning:
                    chunk.delta_reasoning = reasoning

                # Tool calls — pass through raw incremental deltas from SDK
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        fragment = {
                            "index": tc.index,
                            "id": tc.id or "",
                            "type": "function",
                            "function": {
                                "name": tc.function.name if tc.function and tc.function.name else "",
                                "arguments": tc.function.arguments if tc.function and tc.function.arguments else "",
                            },
                        }
                        chunk.tool_calls_delta.append(fragment)

                # Finish reason
                finish_reason = choice.finish_reason
                if finish_reason:
                    chunk.is_final = True
                    chunk.finish_reason = finish_reason

                yield chunk

        except APIStatusError:
            raise
        except APITimeoutError:
            raise
        except APIConnectionError:
            raise
        except Exception:
            raise
