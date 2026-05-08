from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import re
import time
from typing import Optional

from core.provider import ModelInfo
from core.provider import LLMModelClient, ImageModelClient, EmbeddingModelClient
from core.provider.llm_model import LLMRequest, LLMResponse
from core.logging_manager import get_logger
from core.chat.message_elements import Image

logger = get_logger("provider", "purple")


class OpenAIImageClient(ImageModelClient):
    """Image generation client with two on-the-wire shapes.

    Original ``/v1/images/generations`` is the OpenAI standard image
    endpoint. ``/v1/chat/completions`` mode handles the increasingly
    common pattern where multimodal chat models (e.g. some Tongyi /
    Doubao / 3rd-party-compatible APIs) return images embedded in
    chat content — either as Markdown ``![alt](url)``, data URIs, or
    typed ``output_image`` / ``image_url`` content parts.

    The chat path is kept defensively conservative:
      * Bare URLs in text content are NEVER promoted to images
        (would let prompt injection fabricate result URLs).
      * ``type="text"`` content parts are explicitly skipped before
        URL extraction.
      * Data URIs must literally start with ``data:image/``.
    """

    # Markdown image regex: ![alt](url). Used only inside chat mode,
    # only when the entire content is a string AND no structured part
    # was found. Greedy URL match capped at first whitespace.
    _MD_IMAGE_RE = re.compile(r'!\[.*?\]\((https?://\S+?)\)')

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    def _build_client(self) -> AsyncOpenAI:
        """Build the AsyncOpenAI client (shared by both modes)."""
        from httpx import Timeout

        default_headers = self.model.provider_config.get("headers", {})
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        timeout_val = self.model.model_config.get("timeout", 120)
        timeout = Timeout(timeout_val, connect=10)
        return AsyncOpenAI(
            base_url=self.model.provider_config.get("base_url", ""),
            api_key=self.model.provider_config.get("api_key", ""),
            default_headers=default_headers,
            timeout=timeout,
        )

    async def text_to_image(self, prompt) -> Image:
        endpoint = self.model.model_config.get("endpoint", "v1/image")
        if endpoint == "v1/chat":
            return await self._text_to_image_via_chat(prompt)
        return await self._text_to_image_via_generations(prompt)

    # ──────── Mode A: /v1/images/generations ────────

    async def _text_to_image_via_generations(self, prompt: str) -> Image:
        client = self._build_client()
        image_size = self.model.model_config.get("size", None)
        try:
            images_response = await client.images.generate(
                model=self.model.model_id,
                prompt=prompt,
                size=image_size if image_size else None,
                response_format="url",
                extra_body={"watermark": False},
            )
            return Image(image=images_response.data[0].url)
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Image generation API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Image generation error: {e}")
            raise

    # ──────── Mode B: /v1/chat/completions (non-stream) ────────

    async def _text_to_image_via_chat(self, prompt: str) -> Image:
        client = self._build_client()
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await client.chat.completions.create(
                model=self.model.model_id,
                messages=messages,
            )
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Image generation (chat) API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Image generation (chat) error: {e}")
            raise

        if not response.choices:
            raise ValueError("Chat completions returned empty choices")

        message = response.choices[0].message
        image_result = self._extract_image_from_message(message)
        if image_result is not None:
            return image_result

        raise ValueError(
            "Chat completions response carried no recognisable image."
            f" content={getattr(message, 'content', None)!r}"
        )

    # ──────── image extraction helpers ────────

    def _extract_image_from_message(self, message) -> Optional[Image]:
        """
        Walk a ChatCompletionMessage in the most-specific-first order:
          1. content as multimodal list (list[content_part])
          2. model_extra.content (some SDKs / 3rd-party APIs stash here)
          3. content as plain string —
             a) starts with data:image/  → wrap as data URI
             b) contains Markdown ![alt](url) → extract URL
             Bare URLs / plain text NEVER become images.
        """
        content = message.content

        # 1) content itself is a multimodal list
        if isinstance(content, list):
            img = self._scan_parts(content)
            if img:
                return img

        # 2) model_extra.content (SDK version / 3rd-party-compat fallback)
        if hasattr(message, "model_extra") and isinstance(
            message.model_extra, dict
        ):
            extra_content = message.model_extra.get("content")
            if isinstance(extra_content, list):
                img = self._scan_parts(extra_content)
                if img:
                    return img

        # 3) plain string fallbacks
        if isinstance(content, str):
            stripped = content.strip()

            # 3a) entire content is a data:image/ base64 URI
            if stripped.startswith("data:image/"):
                return Image(image=stripped)

            # 3b) Markdown image syntax — extract URL only from this
            # syntax, never from random URLs in text content
            md_match = self._MD_IMAGE_RE.search(stripped)
            if md_match:
                url = md_match.group(1)
                # Strip a stray closing paren that the prompt sometimes
                # appends right after the URL.
                url = url.rstrip(")")
                return Image(image=url)

        return None

    def _scan_parts(self, parts: list) -> Optional[Image]:
        """Return the first extractable image among content parts."""
        for part in parts:
            img = self._try_extract_image_part(part)
            if img:
                return img
        return None

    def _try_extract_image_part(self, part) -> Optional[Image]:
        """
        Pull an image out of one content part.
        ``part`` may be a dict (raw JSON) or a pydantic model (parsed SDK).
        Explicitly skip ``type="text"`` to avoid hoisting URLs from text.
        """
        # Normalise to dict
        if hasattr(part, "model_dump"):
            part = part.model_dump()
        elif not isinstance(part, dict) and hasattr(part, "__dict__"):
            part = vars(part)
        if not isinstance(part, dict):
            return None

        part_type = part.get("type", "")

        # type=text — never extract URLs from this
        if part_type == "text":
            return None

        # ── image_url ──
        if part_type == "image_url":
            url = self._get_nested_url(part, "image_url")
            if url and self._is_valid_image_source(url):
                return Image(image=url)

        # ── output_image ──
        if part_type == "output_image":
            # url field first
            url = part.get("url", "")
            if url and self._is_valid_image_source(url):
                return Image(image=url)
            # fall back to base64 / data field → build data URI
            b64 = part.get("base64", "") or part.get("data", "")
            if b64:
                media_type = (
                    part.get("media_type")
                    or part.get("content_type")
                    or "image/png"
                )
                return Image(image=f"data:{media_type};base64,{b64}")

        return None

    @staticmethod
    def _get_nested_url(part: dict, key: str) -> str:
        """Read url from a possibly-nested dict-or-attr structure."""
        obj = part.get(key, {})
        if isinstance(obj, dict):
            return obj.get("url", "")
        if hasattr(obj, "url"):
            return obj.url or ""
        return ""

    @staticmethod
    def _is_valid_image_source(url: str) -> bool:
        """Accept only data:image/ base64 URIs and HTTP(S) URLs."""
        return url.startswith("data:image/") or url.startswith(
            ("http://", "https://")
        )

    async def image_to_image(self, prompt: str, image: Image) -> Image:
        endpoint = self.model.model_config.get("endpoint", "v1/image")
        if endpoint == "v1/chat":
            return await self._image_to_image_via_chat(prompt, image)
        return await self._image_to_image_via_generations(prompt, image)

    # ──────── image-to-image Mode A: /v1/images/generations ────────

    async def _image_to_image_via_generations(self, prompt: str, image: Image) -> Image:
        client = self._build_client()
        image_size = self.model.model_config.get("size", None)
        # Convert the input image to a data URL that the API can consume
        image_data_url = await image.to_data_url()
        try:
            images_response = await client.images.generate(
                model=self.model.model_id,
                prompt=prompt,
                image=[image_data_url],
                size=image_size if image_size else None,
                response_format="url",
                extra_body={"watermark": False},
            )
            return Image(image=images_response.data[0].url)
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Image-to-image generation API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Image-to-image generation error: {e}")
            raise

    # ──────── image-to-image Mode B: /v1/chat/completions ────────

    async def _image_to_image_via_chat(self, prompt: str, image: Image) -> Image:
        client = self._build_client()
        image_data_url = await image.to_data_url()
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }]
        try:
            response = await client.chat.completions.create(
                model=self.model.model_id,
                messages=messages,
            )
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Image-to-image (chat) API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Image-to-image (chat) error: {e}")
            raise
        if not response.choices:
            raise ValueError("Chat completions returned empty choices")
        message = response.choices[0].message
        image_result = self._extract_image_from_message(message)
        if image_result is not None:
            return image_result
        raise ValueError(
            "Chat completions response carried no recognisable image."
            f" content={getattr(message, 'content', None)!r}"
        )


class OpenAIEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        timeout_sec = self.model.model_config.get("timeout", 60) if self.model.model_config else 60
        slow_threshold = self.model.model_config.get("slow_request_threshold", 5.0) if self.model.model_config else 5.0

        default_headers = self.model.provider_config.get("headers", {})
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None

        client = AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=self.model.provider_config.get("base_url", ""),
            timeout=timeout_sec,
            default_headers=default_headers
        )
        try:
            start_time = time.perf_counter()
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
            return []
        except Exception as e:
            logger.error(f"Embedding error: {e}")
            return []

