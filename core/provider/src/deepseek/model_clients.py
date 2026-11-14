import asyncio
import base64
import time
import wave
from collections.abc import AsyncGenerator
from io import BytesIO

import httpx
from openai import (
    NOT_GIVEN,
    AsyncOpenAI,
)

from core.agent.message import provider_message_dict
from core.chat.message_elements import Record
from core.logging_manager import get_logger
from core.provider import (
    LLMModelClient,
    ModelInfo,
    ProviderAPIError,
    STTModelClient,
    TTSModelClient,
)
from core.provider.llm_model import LLMRequest, LLMResponse, LLMStreamChunk
from core.provider.openai_compatible import build_llm_default_headers
from core.utils.media_refs import resolve_media_references

logger = get_logger("provider", "purple")

MAX_ASR_FILE_BYTES = 8 * 1024 * 1024


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

        kwargs = {
            "model": self.model.model_name,
            "messages": [provider_message_dict(m) for m in request.messages],
            "tools": request.tools if request.tools else NOT_GIVEN,
            "tool_choice": request.tool_choice if request.tool_choice != "none" else NOT_GIVEN,
        }

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


    async def chat_stream(self, request: LLMRequest, **kwargs) -> AsyncGenerator[LLMStreamChunk, None]:
        client = self._build_client()
        messages = await resolve_media_references(request.messages)
        request_kwargs = self._build_request_kwargs(
            request, messages=messages, stream=True, **kwargs
        )
        request_kwargs["stream_options"] = {"include_usage": True}

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


async def _post_audio_tool(model: ModelInfo, tool: str, **kwargs) -> httpx.Response:
    provider_config = model.provider_config or {}
    model_config = model.model_config or {}
    base_url = httpx.URL(provider_config.get("base_url") or "https://api.deepseek.com")
    path = base_url.path.rstrip("/")
    if not path.endswith("/v1"):
        path += "/v1"
    url = base_url.copy_with(path=f"{path}/tools/{tool}")

    headers = httpx.Headers(build_llm_default_headers(provider_config))
    headers.pop("Content-Type", None)
    if "Authorization" not in headers:
        api_key = (provider_config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("DeepSeek API key is required")
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(timeout=model_config.get("timeout", 120)) as client:
        response = await client.post(url, headers=headers, **kwargs)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ProviderAPIError(
            f"DeepSeek {tool.upper()} returned HTTP {response.status_code}: {response.text}"
        ) from exc
    return response


def _is_wav(audio: bytes) -> bool:
    return audio.startswith(b"RIFF") and audio[8:12] == b"WAVE"


def _is_ogg_opus(audio: bytes) -> bool:
    if len(audio) < 27 or not audio.startswith(b"OggS"):
        return False
    # The first packet follows the fixed page header and segment table.
    return audio.startswith(b"OpusHead", 27 + audio[26])


def _read_asr_file(path: str) -> bytes:
    with open(path, "rb") as audio_file:
        return audio_file.read(MAX_ASR_FILE_BYTES + 1)


class DeepSeekSTTClient(STTModelClient):
    async def health_check(self) -> None:
        sample = BytesIO()
        with wave.open(sample, "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(bytes(32000))
        await self._transcribe(sample.getvalue())

    async def speech_to_text(self, record: Record, **kwargs) -> str:
        if record is None:
            return ""

        if record.file_type in ("base64", "data_url"):
            encoded = await record.to_base64()
            audio = await asyncio.to_thread(base64.b64decode, encoded)
        else:
            path = await record.to_path()
            audio = await asyncio.to_thread(_read_asr_file, path)
        return await self._transcribe(audio)

    async def _transcribe(self, audio: bytes) -> str:
        if len(audio) > MAX_ASR_FILE_BYTES:
            raise ValueError("DeepSeek ASR audio exceeds the 8 MiB limit")

        if _is_wav(audio):
            filename, mime = "speech.wav", "audio/wav"
        elif _is_ogg_opus(audio):
            filename, mime = "speech.ogg", "audio/ogg"
        else:
            raise ValueError("DeepSeek ASR requires 16-bit PCM WAV or Ogg Opus audio")

        response = await _post_audio_tool(self.model, "asr", files={"file": (filename, audio, mime)})
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("text"), str):
            raise ProviderAPIError("DeepSeek ASR response is missing transcript text")
        return result["text"]


class DeepSeekTTSClient(TTSModelClient):
    async def text_to_speech(self, text: str, **kwargs) -> Record:
        if not text.strip():
            raise ValueError("DeepSeek TTS requires non-empty text")

        config = self.model.model_config or {}
        payload = {
            "text": text,
            "voice_id": kwargs.get("voice_id", config.get("voice_id", "stella")),
            "filter_markdown": kwargs.get("filter_markdown", config.get("filter_markdown", True)),
            "format": "wav",
        }
        response = await _post_audio_tool(self.model, "tts", json=payload)
        if not _is_wav(response.content):
            raise ProviderAPIError("DeepSeek TTS response did not contain WAV audio")

        audio = await asyncio.to_thread(base64.b64encode, response.content)
        return Record(record=f"base64://{audio.decode('ascii')}", name="speech.wav", mime="audio/wav")
