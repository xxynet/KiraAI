from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import time
from typing import AsyncGenerator

from core.provider import ModelInfo, LLMModelClient
from core.provider.llm_model import LLMRequest, LLMResponse, LLMStreamChunk
from core.logging_manager import get_logger

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
        section_advanced = self.model.provider_config.get("section_advanced")
        default_headers = section_advanced.get("headers", {}) if isinstance(section_advanced, dict) else {}
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        return AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=default_headers,
        )

    def _build_request_kwargs(self, request: LLMRequest) -> dict:
        """Build DeepSeek-specific kwargs with thinking mode support."""
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
            tools=request.tools if request.tools else None,
            tool_choice=request.tool_choice if request.tool_choice != "none" else None,
        )

        if thinking_enabled:
            kwargs["reasoning_effort"] = reasoning_effort
        else:
            temperature = section_advanced.get("temperature")
            kwargs["temperature"] = temperature if temperature is not None else 1

        if extra_body:
            kwargs["extra_body"] = extra_body

        return kwargs

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        client = self._build_client()
        request_kwargs = self._build_request_kwargs(request)

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
        request_kwargs = self._build_request_kwargs(request)
        request_kwargs["stream"] = True

        # Accumulated tool calls by index
        collected_tool_calls: dict[int, dict] = {}

        try:
            stream = await client.chat.completions.create(**request_kwargs)
            async for event in stream:
                if not event.choices:
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
                    for idx in sorted(collected_tool_calls):
                        tc = collected_tool_calls[idx]
                        chunk.tool_calls_delta.append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        })
                    if event.usage:
                        chunk.usage = {
                            "input_tokens": event.usage.prompt_tokens,
                            "output_tokens": event.usage.completion_tokens,
                            "cached_tokens": getattr(event.usage, "prompt_cache_hit_tokens", None),
                        }

                yield chunk

        except APIStatusError:
            raise
        except APITimeoutError:
            raise
        except APIConnectionError:
            raise
        except Exception:
            raise
