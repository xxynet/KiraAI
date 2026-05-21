from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import time

from core.provider import ModelInfo, LLMModelClient
from core.provider.llm_model import LLMRequest, LLMResponse
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

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        default_headers = self.model.provider_config.get("section_advanced", {}).get("headers", {})
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            default_headers=default_headers
        )

        # Resolve thinking mode config
        model_config = self.model.model_config or {}
        thinking_enabled = model_config.get("thinking_enabled", True)
        reasoning_effort = model_config.get("reasoning_effort", "high")

        # Build extra_body for DeepSeek thinking mode
        extra_body = {}
        if thinking_enabled:
            extra_body["thinking"] = {"type": "enabled"}
        else:
            extra_body["thinking"] = {"type": "disabled"}

        # Build request kwargs
        request_kwargs = dict(
            model=self.model.model_id,
            messages=request.messages,
            tools=request.tools if request.tools else None,
            tool_choice=request.tool_choice if request.tool_choice != "none" else None,
        )

        if thinking_enabled:
            # DeepSeek thinking mode: temperature/top_p are ignored, use reasoning_effort instead
            request_kwargs["reasoning_effort"] = reasoning_effort
        else:
            # Non-thinking mode: use normal temperature
            temperature = model_config.get("temperature")
            request_kwargs["temperature"] = temperature if temperature is not None else 1

        if extra_body:
            request_kwargs["extra_body"] = extra_body

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
