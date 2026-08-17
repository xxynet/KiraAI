from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
from io import BytesIO
from typing import Optional
import httpx
import base64
import mimetypes
import os
import time

from core.provider import ModelInfo, ProviderAPIError
from core.provider import (ImageModelClient, TTSModelClient,
                           STTModelClient, EmbeddingModelClient, RerankModelClient)
from core.logging_manager import get_logger
from core.provider.llm_model import LLMRequest, LLMResponse, RerankResult

from core.chat.message_elements import Record, Image
from core.utils.model_clients import OpenAICompatibleLLMClient, OpenAICompatibleTTSClient

logger = get_logger("provider", "purple")

_AUDIO_EXTENSIONS = {
    "wav", "mp3", "amr", "silk", "ogg", "opus", "m4a", "aac", "flac", "pcm", "webm",
}

_AUDIO_MIME_EXTENSIONS = {
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/amr": "amr",
    "audio/silk": "silk",
    "audio/ogg": "ogg",
    "audio/opus": "opus",
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/aac": "aac",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}


def _sniff_audio_extension(data: bytes) -> Optional[str]:
    """Detect the container of an audio payload from its magic bytes."""
    if len(data) < 8:
        return None
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return "wav"
    if data[:4] == b"OggS":
        return "ogg"
    if data[:4] == b"fLaC":
        return "flac"
    if data[:5] == b"#!AMR":
        return "amr"
    if b"#!SILK" in data[:10]:
        return "silk"
    if data[4:8] == b"ftyp":
        return "m4a"
    if data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return "mp3"
    return None


def resolve_audio_filename(record: Record, audio_data: bytes) -> str:
    """Derive an upload filename whose extension matches the actual audio.

    IM voice messages are commonly amr/silk/ogg/mp3; sending them as .wav
    makes the server misparse the payload or degrade transcription.
    """
    ext = _sniff_audio_extension(audio_data)
    if not ext:
        for candidate in (record.name, record.guess_name()):
            if not candidate:
                continue
            suffix = os.path.splitext(candidate)[1].lstrip(".").lower()
            if suffix in _AUDIO_EXTENSIONS:
                ext = suffix
                break
    if not ext:
        mime = (record.mime or "").split(";")[0].strip().lower()
        ext = _AUDIO_MIME_EXTENSIONS.get(mime)
        if not ext and mime.startswith("audio/"):
            guessed = (mimetypes.guess_extension(mime) or "").lstrip(".").lower()
            ext = guessed if guessed in _AUDIO_EXTENSIONS else None
    return f"audio.{ext or 'wav'}"


class SiliconflowLLMClient(OpenAICompatibleLLMClient):
    pass


class SiliconflowImageClient(ImageModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_image(self, prompt) -> Image:
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
        data = response.json()
        images = data.get("images") if isinstance(data, dict) else None
        image_url = images[0].get("url") if isinstance(images, list) and images else None
        if not image_url:
            raise ValueError(f"Siliconflow image generation returned no image url: {data}")
        return Image(image=image_url)


class SiliconflowTTSClient(OpenAICompatibleTTSClient):
    pass


class SiliconflowSTTClient(STTModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def speech_to_text(self, record: Record, **kwargs):
        url = "https://api.siliconflow.cn/v1/audio/transcriptions"

        audio_base64 = await record.to_base64()

        audio_data = base64.b64decode(audio_base64)
        audio_file = BytesIO(audio_data)
        audio_file.name = resolve_audio_filename(record, audio_data)

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

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        timeout_sec = self.model.model_config.get("timeout", 60) if self.model.model_config else 60
        slow_threshold = self.model.model_config.get("slow_request_threshold", 5.0) if self.model.model_config else 5.0

        try:
            start_time = time.perf_counter()
            async with AsyncOpenAI(
                api_key=self.model.provider_config.get("api_key", ""),
                base_url="https://api.siliconflow.cn/v1",
                timeout=timeout_sec
            ) as client:
                response = await client.embeddings.create(
                    model=self.model.model_id,
                    input=texts
                )
            elapsed = round(time.perf_counter() - start_time, 2)
            if elapsed > slow_threshold:
                logger.warning(f"Slow embedding request: {elapsed}s (threshold: {slow_threshold}s, model: {self.model.model_id})")
            return [item.embedding for item in response.data]
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Embedding API error: {e}")
            raise ProviderAPIError(f"Embedding request failed: {e}") from e
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            raise ProviderAPIError(f"Embedding request failed: {e}") from e


class SiliconflowRerankClient(RerankModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
        **kwargs
    ) -> list[RerankResult]:

        url = "https://api.siliconflow.cn/v1/rerank"

        payload = {
            "model": self.model.model_id,
            "query": query,
            "documents": documents,
        }

        if top_n:
            payload["top_n"] = top_n

        if "return_documents" in kwargs:
            payload["return_documents"] = kwargs["return_documents"]

        if "instruction" in kwargs:
            payload["instruction"] = kwargs["instruction"]

        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.model.provider_config.get('api_key', '')}",
                    "Content-Type": "application/json",
                }
            )

        resp.raise_for_status()
        data = resp.json()

        results: list[RerankResult] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            try:
                idx = int(item["index"])
            except (KeyError, TypeError, ValueError):
                continue
            if not 0 <= idx < len(documents):
                logger.warning(f"Siliconflow rerank returned out-of-range index {idx}, skipping")
                continue
            try:
                score = float(item.get("relevance_score", 0.0) or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            results.append(RerankResult(index=idx, score=score, text=documents[idx]))

        return results
