from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator

from anthropic import AnthropicError, AsyncAnthropic

from core.provider import LLMModelClient, ModelInfo, ProviderAPIError
from core.provider.llm_model import LLMRequest, LLMResponse, LLMStreamChunk

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_API_VERSION = "2023-06-01"


def normalize_anthropic_base_url(base_url: str) -> str:
    """Normalize a compatible endpoint for the SDK, which appends /v1 paths."""
    normalized = (base_url or DEFAULT_BASE_URL).rstrip("/")
    for suffix in ("/v1/messages", "/v1/models", "/v1"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def build_anthropic_headers(provider_config: dict) -> dict[str, str]:
    """Build SDK default headers and merge user-defined overrides."""
    headers = {
        "anthropic-version": provider_config.get("anthropic_version")
        or DEFAULT_API_VERSION,
    }
    advanced = provider_config.get("section_advanced") or {}
    custom_headers = advanced.get("headers") if isinstance(advanced, dict) else None
    if isinstance(custom_headers, dict):
        headers.update(
            {
                str(key): str(value)
                for key, value in custom_headers.items()
                if value is not None
            }
        )
    return headers


def build_anthropic_client(
    provider_config: dict,
    *,
    timeout: float,
) -> AsyncAnthropic:
    """Create the official async SDK client for a compatible endpoint."""
    return AsyncAnthropic(
        api_key=provider_config.get("api_key") or "",
        base_url=normalize_anthropic_base_url(
            provider_config.get("base_url", DEFAULT_BASE_URL)
        ),
        default_headers=build_anthropic_headers(provider_config),
        timeout=timeout,
    )


class AnthropicCompatibleLLMClient(LLMModelClient):
    """LLM client for Anthropic-compatible Messages API endpoints."""

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    @staticmethod
    def _text_block(text: object) -> dict:
        return {"type": "text", "text": str(text)}

    @classmethod
    def _convert_content(cls, content: object) -> list[dict]:
        if content is None:
            return []
        if isinstance(content, str):
            return [cls._text_block(content)] if content else []
        if isinstance(content, list):
            blocks: list[dict] = []
            for part in content:
                blocks.extend(cls._convert_content(part))
            return blocks
        if not isinstance(content, dict):
            return [cls._text_block(content)]

        part_type = content.get("type")
        if part_type in ("text", "input_text"):
            text = content.get("text", "")
            return [cls._text_block(text)] if text else []

        if part_type == "image_url":
            image_url = content.get("image_url") or {}
            url = image_url.get("url") if isinstance(image_url, dict) else image_url
            if not isinstance(url, str) or not url:
                return []
            if url.startswith("data:") and ";base64," in url:
                metadata, data = url.split(",", maxsplit=1)
                media_type = metadata[5:].split(";", maxsplit=1)[0]
                return [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": data,
                        },
                    }
                ]
            return [
                {
                    "type": "image",
                    "source": {"type": "url", "url": url},
                }
            ]

        # Already-native Anthropic blocks can pass through unchanged. This is
        # useful for compatible gateways that expose additional content types.
        if part_type in {
            "text",
            "image",
            "document",
            "search_result",
            "tool_use",
            "tool_result",
            "thinking",
            "redacted_thinking",
        }:
            return [dict(content)]

        return [cls._text_block(json.dumps(content, ensure_ascii=False))]

    @staticmethod
    def _tool_input(arguments: object) -> dict:
        if isinstance(arguments, dict):
            return arguments
        if not isinstance(arguments, str) or not arguments.strip():
            return {}
        try:
            value = json.loads(arguments)
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _convert_messages(cls, request: LLMRequest) -> tuple[str, list[dict]]:
        system_parts: list[str] = []
        messages: list[dict] = []

        def append_message(role: str, blocks: list[dict]) -> None:
            if not blocks:
                return
            if messages and messages[-1]["role"] == role:
                messages[-1]["content"].extend(blocks)
            else:
                messages.append({"role": role, "content": blocks})

        for raw_message in request.messages:
            message = (
                raw_message if isinstance(raw_message, dict) else raw_message.to_dict()
            )
            role = message.get("role")

            if role == "system":
                for block in cls._convert_content(message.get("content")):
                    if block.get("type") == "text" and block.get("text"):
                        system_parts.append(block["text"])
                continue

            if role == "tool":
                tool_content = cls._convert_content(message.get("content"))
                append_message(
                    "user",
                    [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.get("tool_call_id") or "",
                            "content": tool_content,
                        }
                    ],
                )
                continue

            if role not in ("user", "assistant"):
                continue

            blocks = cls._convert_content(message.get("content"))
            if role == "assistant":
                for tool_call in message.get("tool_calls") or []:
                    function = tool_call.get("function") or {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tool_call.get("id") or "",
                            "name": function.get("name") or "",
                            "input": cls._tool_input(function.get("arguments")),
                        }
                    )
            append_message(role, blocks)

        return "\n\n".join(system_parts), messages

    @staticmethod
    def _convert_tools(tools: list[dict] | None) -> list[dict]:
        converted: list[dict] = []
        for tool in tools or []:
            function = tool.get("function") if isinstance(tool, dict) else None
            if not isinstance(function, dict) or not function.get("name"):
                continue
            anthropic_tool = {
                "name": function["name"],
                "input_schema": function.get("parameters")
                or {"type": "object", "properties": {}},
            }
            if function.get("description"):
                anthropic_tool["description"] = function["description"]
            converted.append(anthropic_tool)
        return converted

    def _build_request_body(self, request: LLMRequest, **overrides) -> dict:
        model_config = self.model.model_config or {}
        advanced = model_config.get("section_advanced") or {}
        system, messages = self._convert_messages(request)

        body = {
            "model": self.model.model_id,
            "max_tokens": model_config.get("max_tokens") or 4096,
            "messages": messages,
        }
        if system:
            body["system"] = system

        tools = self._convert_tools(request.tools)
        if tools and request.tool_choice != "none":
            body["tools"] = tools
            tool_choice = {
                "auto": "auto",
                "required": "any",
            }.get(request.tool_choice or "auto", "auto")
            body["tool_choice"] = {"type": tool_choice}

        if isinstance(advanced, dict):
            temperature = advanced.get("temperature")
            if temperature is not None:
                body["temperature"] = temperature
            extra_body = advanced.get("extra_body")
            if isinstance(extra_body, dict) and extra_body:
                body["extra_body"] = extra_body

        body.update(overrides)
        return body

    def _build_client(self) -> AsyncAnthropic:
        timeout = (self.model.model_config or {}).get("timeout") or 120
        return build_anthropic_client(
            self.model.provider_config or {},
            timeout=timeout,
        )

    @staticmethod
    def _parse_response(data: dict, time_consumed: float | None = None) -> LLMResponse:
        response = LLMResponse("", time_consumed=time_consumed)
        reasoning_parts: list[str] = []

        for block in data.get("content") or []:
            block_type = block.get("type")
            if block_type == "text":
                response.text_response += block.get("text") or ""
            elif block_type == "thinking":
                reasoning_parts.append(block.get("thinking") or "")
            elif block_type == "tool_use":
                response.tool_calls.append(
                    {
                        "id": block.get("id") or "",
                        "type": "function",
                        "function": {
                            "name": block.get("name") or "",
                            "arguments": json.dumps(
                                block.get("input") or {}, ensure_ascii=False
                            ),
                        },
                    }
                )

        response.reasoning_content = "".join(reasoning_parts)
        usage = data.get("usage") or {}
        input_counts = [
            usage.get("input_tokens"),
            usage.get("cache_creation_input_tokens"),
            usage.get("cache_read_input_tokens"),
        ]
        response.input_tokens = (
            sum(value or 0 for value in input_counts)
            if any(value is not None for value in input_counts)
            else None
        )
        response.output_tokens = usage.get("output_tokens")
        response.cached_tokens = usage.get("cache_read_input_tokens")
        return response

    async def chat(self, request: LLMRequest, **kwargs) -> LLMResponse:
        body = self._build_request_body(request, **kwargs)
        start_time = time.perf_counter()
        try:
            async with self._build_client() as client:
                response = await client.messages.create(**body)
        except AnthropicError as e:
            raise ProviderAPIError(str(e)) from e
        elapsed = round(time.perf_counter() - start_time, 2)
        return self._parse_response(response.to_dict(), elapsed)

    @staticmethod
    def _finish_reason(stop_reason: str | None) -> str:
        return {
            "tool_use": "tool_calls",
            "max_tokens": "length",
            "refusal": "content_filter",
        }.get(stop_reason or "", "stop")

    async def chat_stream(
        self, request: LLMRequest, **kwargs
    ) -> AsyncGenerator[LLMStreamChunk, None]:
        body = self._build_request_body(request, stream=True, **kwargs)
        input_tokens = None
        output_tokens = None
        cached_tokens = None
        stop_reason = None
        tool_indices: dict[int, int] = {}

        try:
            async with self._build_client() as client:
                stream = await client.messages.create(**body)
                async for sdk_event in stream:
                    event = sdk_event.to_dict()
                    event_type = event.get("type")
                    if event_type == "message_start":
                        usage = (event.get("message") or {}).get("usage") or {}
                        input_counts = [
                            usage.get("input_tokens"),
                            usage.get("cache_creation_input_tokens"),
                            usage.get("cache_read_input_tokens"),
                        ]
                        input_tokens = (
                            sum(value or 0 for value in input_counts)
                            if any(value is not None for value in input_counts)
                            else None
                        )
                        cached_tokens = usage.get("cache_read_input_tokens")
                        continue

                    if event_type == "content_block_start":
                        index = event.get("index", 0)
                        block = event.get("content_block") or {}
                        if block.get("type") == "text" and block.get("text"):
                            yield LLMStreamChunk(delta_text=block["text"])
                        elif block.get("type") == "thinking" and block.get("thinking"):
                            yield LLMStreamChunk(delta_reasoning=block["thinking"])
                        elif block.get("type") == "tool_use":
                            tool_index = len(tool_indices)
                            tool_indices[index] = tool_index
                            yield LLMStreamChunk(
                                tool_calls_delta=[
                                    {
                                        "index": tool_index,
                                        "id": block.get("id") or "",
                                        "type": "function",
                                        "function": {
                                            "name": block.get("name") or "",
                                            "arguments": "",
                                        },
                                    }
                                ]
                            )
                        continue

                    if event_type == "content_block_delta":
                        index = event.get("index", 0)
                        delta = event.get("delta") or {}
                        delta_type = delta.get("type")
                        if delta_type == "text_delta":
                            yield LLMStreamChunk(delta_text=delta.get("text") or "")
                        elif delta_type == "thinking_delta":
                            yield LLMStreamChunk(
                                delta_reasoning=delta.get("thinking") or ""
                            )
                        elif delta_type == "input_json_delta":
                            yield LLMStreamChunk(
                                tool_calls_delta=[
                                    {
                                        "index": tool_indices.get(index, index),
                                        "id": "",
                                        "type": "function",
                                        "function": {
                                            "name": "",
                                            "arguments": delta.get("partial_json")
                                            or "",
                                        },
                                    }
                                ]
                            )
                        continue

                    if event_type == "message_delta":
                        stop_reason = (event.get("delta") or {}).get(
                            "stop_reason"
                        ) or stop_reason
                        usage = event.get("usage") or {}
                        output_tokens = usage.get("output_tokens", output_tokens)
                        continue

                    if event_type == "message_stop":
                        yield LLMStreamChunk(
                            is_final=True,
                            finish_reason=self._finish_reason(stop_reason),
                            usage={
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "cached_tokens": cached_tokens,
                            },
                        )
        except AnthropicError as e:
            raise ProviderAPIError(str(e)) from e
