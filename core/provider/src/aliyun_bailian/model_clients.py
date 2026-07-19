import asyncio
import base64
import inspect
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from io import BytesIO
from math import gcd, sqrt
from typing import Optional, Union

import httpx
from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError

from core.provider import (
    ModelInfo,
    TTSModelClient,
    STTModelClient,
    ImageModelClient,
    EmbeddingModelClient,
    RerankModelClient,
)
from core.provider.llm_model import RerankResult
from core.chat.message_elements import Record, Image
from core.logging_manager import get_logger
from core.utils.model_clients import OpenAICompatibleLLMClient

logger = get_logger("provider", "purple")

# CosyVoice non-streaming call limit (characters)
_MAX_TEXT_CHARS = 20000

# Protect dashscope global api_key / websocket url mutation across concurrent calls
_DASHSCOPE_LOCK = threading.Lock()

# region -> OpenAI compatible base_url (default public endpoints)
_REGION_COMPAT_URL = {
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
}

# region -> workspace-scoped OpenAI compatible base_url
_REGION_COMPAT_URL_WORKSPACE = {
    "beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    "singapore": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
}

# region -> DashScope native HTTP API base
_REGION_HTTP_URL = {
    "beijing": "https://dashscope.aliyuncs.com/api/v1",
    "singapore": "https://dashscope-intl.aliyuncs.com/api/v1",
}

_REGION_HTTP_URL_WORKSPACE = {
    "beijing": "https://{workspace_id}.cn-beijing.maas.aliyuncs.com/api/v1",
    "singapore": "https://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api/v1",
}

# region -> default DashScope WebSocket endpoint (TTS / realtime STT)
_REGION_WS_URL = {
    "beijing": "wss://dashscope.aliyuncs.com/api-ws/v1/inference",
    "singapore": "wss://dashscope-intl.aliyuncs.com/api-ws/v1/inference",
}

_REGION_WS_URL_WORKSPACE = {
    "beijing": "wss://{workspace_id}.cn-beijing.maas.aliyuncs.com/api-ws/v1/inference",
    "singapore": "wss://{workspace_id}.ap-southeast-1.maas.aliyuncs.com/api-ws/v1/inference",
}


def _region(mp: dict) -> str:
    return (mp.get("region") or "beijing").lower().strip()


def _workspace_id(mp: dict) -> str:
    return (mp.get("workspace_id") or "").strip()


def resolve_compatible_base_url(provider_config: dict) -> str:
    """Resolve OpenAI-compatible base_url from provider config."""
    mp = provider_config or {}
    # Explicit override wins
    custom = (mp.get("base_url") or "").strip()
    if custom:
        return custom.rstrip("/")

    region = _region(mp)
    workspace_id = _workspace_id(mp)
    if workspace_id:
        template = _REGION_COMPAT_URL_WORKSPACE.get(region, _REGION_COMPAT_URL_WORKSPACE["beijing"])
        return template.format(workspace_id=workspace_id)
    return _REGION_COMPAT_URL.get(region, _REGION_COMPAT_URL["beijing"])


def resolve_http_base_url(provider_config: dict) -> str:
    """Resolve DashScope native HTTP API base_url."""
    mp = provider_config or {}
    region = _region(mp)
    workspace_id = _workspace_id(mp)
    if workspace_id:
        template = _REGION_HTTP_URL_WORKSPACE.get(region, _REGION_HTTP_URL_WORKSPACE["beijing"])
        return template.format(workspace_id=workspace_id)
    return _REGION_HTTP_URL.get(region, _REGION_HTTP_URL["beijing"])


def _resolve_ws_url(region: str, workspace_id: str) -> str:
    if workspace_id:
        template = _REGION_WS_URL_WORKSPACE.get(region, _REGION_WS_URL_WORKSPACE["beijing"])
        return template.format(workspace_id=workspace_id)
    return _REGION_WS_URL.get(region, _REGION_WS_URL["beijing"])


# ───────────────────────────── LLM ─────────────────────────────


class BailianLLMClient(OpenAICompatibleLLMClient):
    """LLM via DashScope OpenAI-compatible chat completions."""

    def _build_client(self) -> AsyncOpenAI:
        section_advanced = self.model.provider_config.get("section_advanced")
        default_headers = section_advanced.get("headers", {}) if isinstance(section_advanced, dict) else {}
        if not isinstance(default_headers, dict) or not default_headers:
            default_headers = None
        return AsyncOpenAI(
            api_key=self.model.provider_config.get("api_key", ""),
            base_url=resolve_compatible_base_url(self.model.provider_config),
            default_headers=default_headers,
        )


# ───────────────────────────── Embedding ─────────────────────────────


class BailianEmbeddingClient(EmbeddingModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        mc = self.model.model_config or {}
        timeout_sec = mc.get("timeout", 60)
        slow_threshold = mc.get("slow_request_threshold", 5.0)
        dimensions = mc.get("dimensions")

        try:
            async with AsyncOpenAI(
                api_key=self.model.provider_config.get("api_key", ""),
                base_url=resolve_compatible_base_url(self.model.provider_config),
                timeout=timeout_sec,
            ) as client:
                start_time = time.perf_counter()
                kwargs = {
                    "model": self.model.model_id,
                    "input": texts,
                }
                # dimensions only for built-in text-embedding-v3 / v4
                # (v2 rejects it; avoid matching custom ids like company-v3-embedding)
                mid = (self.model.model_id or "").lower().strip()
                if dimensions and mid in {"text-embedding-v3", "text-embedding-v4"}:
                    kwargs["dimensions"] = int(dimensions)
                    kwargs["encoding_format"] = "float"

                response = await client.embeddings.create(**kwargs)
            elapsed = round(time.perf_counter() - start_time, 2)
            if elapsed > float(slow_threshold or 0):
                logger.warning(
                    f"Slow embedding request: {elapsed}s "
                    f"(threshold: {slow_threshold}s, model: {self.model.model_id})"
                )
            return [item.embedding for item in response.data]
        except (APIStatusError, APITimeoutError, APIConnectionError) as e:
            logger.error(f"Bailian Embedding API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Bailian Embedding error: {e}")
            return []


# ───────────────────────────── Rerank ─────────────────────────────


class BailianRerankClient(RerankModelClient):
    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: Optional[int] = None,
        **kwargs,
    ) -> list[RerankResult]:
        if not documents:
            return []

        mp = self.model.provider_config or {}
        mc = self.model.model_config or {}
        api_key = (mp.get("api_key") or "").strip()
        if not api_key:
            logger.error("Bailian Rerank: api_key is not configured")
            return []

        model_id = self.model.model_id
        timeout = int(mc.get("timeout", 30) or 30)
        instruct = (mc.get("instruct") or kwargs.get("instruct") or "").strip()
        return_documents = mc.get("return_documents", True)
        if "return_documents" in kwargs:
            return_documents = kwargs["return_documents"]

        http_base = resolve_http_base_url(mp).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        # qwen3-rerank uses compatible-api style endpoint
        if model_id.startswith("qwen3-rerank") and "vl" not in model_id:
            # compatible-api/v1/reranks — derive from http base
            # http: .../api/v1  ->  .../compatible-api/v1/reranks
            if http_base.endswith("/api/v1"):
                url = http_base[: -len("/api/v1")] + "/compatible-api/v1/reranks"
            else:
                # public fallback
                region = _region(mp)
                if region == "singapore":
                    url = "https://dashscope-intl.aliyuncs.com/compatible-api/v1/reranks"
                else:
                    url = "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"

            payload = {
                "model": model_id,
                "query": query,
                "documents": documents,
            }
            if top_n is not None:
                payload["top_n"] = top_n
            if instruct:
                payload["instruct"] = instruct
        else:
            # gte-rerank-v2 / qwen3-vl-rerank nested style
            url = f"{http_base}/services/rerank/text-rerank/text-rerank"
            payload = {
                "model": model_id,
                "input": {
                    "query": query,
                    "documents": documents,
                },
                "parameters": {
                    "return_documents": bool(return_documents),
                },
            }
            if top_n is not None:
                payload["parameters"]["top_n"] = top_n
            # gte-rerank-v2 does not support instruct; only qwen3-rerank does

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.error(f"Bailian Rerank failed: {e}")
            return []

        # Normalize results from different response shapes
        raw_results = []
        if isinstance(data, dict):
            if "results" in data:
                raw_results = data.get("results") or []
            elif isinstance(data.get("output"), dict):
                raw_results = data["output"].get("results") or []

        results: list[RerankResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            idx = item.get("index")
            score = item.get("relevance_score", item.get("score", 0.0))
            if idx is None:
                continue
            try:
                idx = int(idx)
            except (TypeError, ValueError):
                continue
            text = documents[idx] if 0 <= idx < len(documents) else ""
            doc = item.get("document")
            if isinstance(doc, dict):
                text = doc.get("text") or text
            elif isinstance(doc, str) and doc:
                text = doc
            results.append(RerankResult(index=idx, score=float(score or 0.0), text=text))

        return results


# ───────────────────────────── Image ─────────────────────────────



# ───────────────────────────── Image size helpers ─────────────────────────────
#
# Design goals:
#   1) "1K/2K/4K/8K..." mean REAL resolution intent (long-edge ≈ N*1024), not
#      a fixed square token blindly sent to every model.
#   2) Always combine with aspect ratio when present ("4k 横屏" → 16:9 pixels).
#   3) Clamp to each model's official max/min total pixels & aspect range so
#      oversize requests never crash the API (works for all Wan / wanx models).

# Known aspect labels -> (w_ratio, h_ratio)
_ASPECT_RATIOS: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "16:9": (16, 9),
    "9:16": (9, 16),
    "4:3": (4, 3),
    "3:4": (3, 4),
    "3:2": (3, 2),
    "2:3": (2, 3),
    "21:9": (21, 9),
}

# Explicit pixel patterns (support up to 5 digits for 4K+/8K)
_SIZE_EXPLICIT_RE = re.compile(
    r"(?P<w>\d{3,5})\s*[xX*×]\s*(?P<h>\d{3,5})"
)
_ASPECT_RE = re.compile(
    r"(?<!\d)(?P<a>\d{1,2})\s*[:：/]\s*(?P<b>\d{1,2})(?!\d)"
)
# 1K / 2k / 4K / 8K / 16k ... (1–99)
_K_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(\d{1,2})\s*[Kk](?![A-Za-z0-9])"
)


@dataclass(frozen=True)
class _ImageSizeLimits:
    """Per-model size constraints (official-friendly defaults)."""

    min_total: int  # min width*height
    max_total: int  # max width*height
    min_side: int
    max_side: int
    min_aspect: float  # min w/h
    max_aspect: float  # max w/h
    multiple: int = 16  # round sides to this multiple when possible
    # Official token sizes this model accepts (empty = never send 1K/2K/4K)
    allow_k_tokens: tuple[str, ...] = ()


def _image_size_limits(
    model_id: str, *, editing: bool = False, interleave: bool = False
) -> _ImageSizeLimits:
    """Return size limits for a DashScope image model.

    Sources (Aliyun docs / community mirrors, 2025-2026):
      - wan2.6-t2i / wan2.5-t2i: total [1280^2, 1440^2], aspect [1:4, 4:1]
      - wan2.7-image: total [768^2, 2048^2], aspect [1:8, 8:1], tokens 1K/2K
      - wan2.7-image-pro (t2i): total [768^2, 4096^2], tokens 1K/2K/4K
      - image edit / ref-image (enable_interleave=false): max 2K (never 4K)
      - wan2.6-image text/interleave (enable_interleave=true): max ~1280^2
      - wan2.2 / wanx*: side [512, 1440], max ~1440^2
    """
    mid = (model_id or "").lower().replace("_", ".")

    # Official wan2.6-image interleave/text-only path.
    # Keep min_total / min_side / max_side / 1:4–4:1 mutually satisfiable:
    # extreme 4:1 at max_side 1280 → 1280*320 (total 409600).
    # Old min_total=768^2 cannot coexist with max_side=1280 at 4:1.
    if interleave:
        return _ImageSizeLimits(
            min_total=640 * 640,  # 409600 == 1280*320 (4:1 @ max_side)
            max_total=1280 * 1280,
            min_side=320,  # short edge of 4:1 @ max_side 1280
            max_side=1280,
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=16,
            allow_k_tokens=("1K",),
        )

    # Preserve legacy edit limits for wanx-v1 / older wanx & wan2.2 paths BEFORE
    # the generic modern edit profile (which allows up to 2K). Otherwise
    # image_to_image() with editing=True would send oversized sizes to wanx-v1.
    if editing and (
        mid in ("wanx-v1", "wanx.v1")
        or mid.startswith("wan2.2")
        or mid.startswith("wanx")
        or mid.startswith("wan2.1")
    ):
        return _ImageSizeLimits(
            min_total=512 * 512,
            max_total=1440 * 1440,
            min_side=512,
            max_side=1440,
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=8,
            allow_k_tokens=(),
        )

    # wan2.6-image edit profile BEFORE generic edit fallback (aspect 1:4–4:1,
    # not the generic 1:8–8:1 used by wan2.7).
    if editing and mid.startswith("wan2.6") and "t2i" not in mid:
        return _ImageSizeLimits(
            min_total=768 * 768,
            max_total=2048 * 2048,
            min_side=256,
            max_side=2048,
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=16,
            allow_k_tokens=("1K", "2K"),
        )

    # Reference-image / edit mode never accepts 4K (including wan2.7-image-pro).
    if editing:
        return _ImageSizeLimits(
            min_total=768 * 768,
            max_total=2048 * 2048,
            min_side=256,
            max_side=2048,
            min_aspect=1 / 8,
            max_aspect=8 / 1,
            multiple=16,
            allow_k_tokens=("1K", "2K"),
        )

    if mid.startswith("wan2.7") and "pro" in mid:
        return _ImageSizeLimits(
            min_total=768 * 768,
            max_total=4096 * 4096,
            min_side=256,
            max_side=4096,
            min_aspect=1 / 8,
            max_aspect=8 / 1,
            multiple=16,
            allow_k_tokens=("1K", "2K", "4K"),
        )
    if mid.startswith("wan2.7"):
        return _ImageSizeLimits(
            min_total=768 * 768,
            max_total=2048 * 2048,
            min_side=256,
            max_side=2048,
            min_aspect=1 / 8,
            max_aspect=8 / 1,
            multiple=16,
            allow_k_tokens=("1K", "2K"),  # no 4K on standard
        )
    if mid.startswith("wan2.6") and "t2i" not in mid:
        # wan2.6-image (non-edit path fallback): total [768^2, 2048^2], tokens 1K/2K
        return _ImageSizeLimits(
            min_total=768 * 768,
            max_total=2048 * 2048,
            min_side=256,
            max_side=2048,
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=16,
            allow_k_tokens=("1K", "2K"),
        )
    if mid.startswith("wan2.6") or mid.startswith("wan2.5"):
        # Pure t2i: total roughly [~1.2M, 1440^2]; official presets like
        # 1696*960 are slightly under 1280^2 so min is soft.
        return _ImageSizeLimits(
            min_total=960 * 960,
            max_total=1440 * 1440,
            min_side=256,
            max_side=2700,  # docs example 768*2700
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=16,
            allow_k_tokens=(),  # must be width*height
        )
    if mid.startswith("wan2.2") or mid.startswith("wanx") or mid.startswith("wan2.1"):
        return _ImageSizeLimits(
            min_total=512 * 512,
            max_total=1440 * 1440,
            min_side=512,
            max_side=1440,
            min_aspect=1 / 4,
            max_aspect=4 / 1,
            multiple=8,
            allow_k_tokens=(),
        )
    # Unknown image model: conservative wide clamp (still safer than raw 8K)
    return _ImageSizeLimits(
        min_total=512 * 512,
        max_total=2048 * 2048,
        min_side=256,
        max_side=2048,
        min_aspect=1 / 8,
        max_aspect=8 / 1,
        multiple=16,
        allow_k_tokens=(),
    )


def _image_model_family(model_id: str) -> str:
    """legacy helper name kept for callers; maps to limit profile."""
    mid = (model_id or "").lower().replace("_", ".")
    if mid.startswith("wan2.7"):
        return "token"
    if mid.startswith("wan2.6") or mid.startswith("wan2.5"):
        return "modern"
    return "legacy"


def _k_level_to_long_edge(k_level: float) -> int:
    """Map N K → intended long-edge pixels (true resolution intent).

    1K→1024, 2K→2048, 4K→4096, 8K→8192, 3K→3072, ...
    """
    if k_level <= 0:
        k_level = 1
    return max(256, int(round(float(k_level) * 1024)))


def _parse_k_level(raw: str | None) -> float | None:
    """Parse '2K' / '4k' / '8K' → 2.0 / 4.0 / 8.0."""
    if not raw:
        return None
    m = re.fullmatch(r"(\d{1,2})\s*[Kk]", str(raw).strip())
    if not m:
        return None
    return float(m.group(1))


def _round_to_multiple(value: float, multiple: int) -> int:
    if multiple <= 1:
        return max(1, int(round(value)))
    return max(multiple, int(round(value / multiple)) * multiple)


def _size_from_aspect_and_long_edge(
    aw: int, ah: int, long_edge: int
) -> tuple[int, int]:
    """Compute (w,h) for aspect aw:ah with max(w,h)=long_edge."""
    if aw <= 0 or ah <= 0:
        return long_edge, long_edge
    if aw >= ah:
        w = long_edge
        h = long_edge * ah / aw
    else:
        h = long_edge
        w = long_edge * aw / ah
    return max(1, int(round(w))), max(1, int(round(h)))


def _clamp_wh(w: int, h: int, limits: _ImageSizeLimits) -> tuple[int, int]:
    """Clamp width/height into model limits, preserving aspect as much as possible."""
    w = float(max(1, w))
    h = float(max(1, h))

    # 1) aspect ratio clamp
    aspect = w / h
    if aspect > limits.max_aspect:
        w = h * limits.max_aspect
        aspect = limits.max_aspect
    elif aspect < limits.min_aspect:
        h = w / limits.min_aspect
        aspect = limits.min_aspect

    # 2) total pixel clamp (scale uniformly)
    total = w * h
    if total > limits.max_total:
        scale = sqrt(limits.max_total / total)
        w *= scale
        h *= scale
    elif total < limits.min_total:
        scale = sqrt(limits.min_total / total)
        w *= scale
        h *= scale

    # 3) side clamp
    if w > limits.max_side or h > limits.max_side:
        scale = min(limits.max_side / w, limits.max_side / h)
        w *= scale
        h *= scale
    if w < limits.min_side or h < limits.min_side:
        # scale up if either side too small, then re-check max
        scale = max(limits.min_side / w, limits.min_side / h)
        w *= scale
        h *= scale
        if w > limits.max_side or h > limits.max_side or w * h > limits.max_total:
            # fall back: fit into max box
            scale = min(
                limits.max_side / w,
                limits.max_side / h,
                sqrt(limits.max_total / (w * h)),
            )
            w *= scale
            h *= scale

    # 4) round to multiple
    wi = _round_to_multiple(w, limits.multiple)
    hi = _round_to_multiple(h, limits.multiple)

    # 5) re-clamp after rounding (total may slightly exceed)
    for _ in range(4):
        if wi * hi <= limits.max_total and wi <= limits.max_side and hi <= limits.max_side:
            break
        scale = min(
            1.0,
            sqrt(limits.max_total / max(1, wi * hi)),
            limits.max_side / max(1, wi),
            limits.max_side / max(1, hi),
        )
        wi = _round_to_multiple(wi * scale, limits.multiple)
        hi = _round_to_multiple(hi * scale, limits.multiple)
        # ensure at least one step down if still over
        if wi * hi > limits.max_total:
            if wi >= hi:
                wi = max(limits.multiple, wi - limits.multiple)
            else:
                hi = max(limits.multiple, hi - limits.multiple)

    # ensure min total roughly (best-effort)
    if wi * hi < limits.min_total:
        scale = sqrt(limits.min_total / max(1, wi * hi))
        wi = _round_to_multiple(wi * scale, limits.multiple)
        hi = _round_to_multiple(hi * scale, limits.multiple)
        if wi * hi > limits.max_total:
            scale = sqrt(limits.max_total / max(1, wi * hi))
            wi = _round_to_multiple(wi * scale, limits.multiple)
            hi = _round_to_multiple(hi * scale, limits.multiple)

    wi = max(limits.min_side, min(limits.max_side, wi))
    hi = max(limits.min_side, min(limits.max_side, hi))
    return int(wi), int(hi)


def _format_wh(w: int, h: int) -> str:
    return f"{int(w)}*{int(h)}"


def _maybe_k_token(w: int, h: int, k_level: float | None, limits: _ImageSizeLimits) -> str | None:
    """Only for models that officially accept 1K/2K/4K AND request is square-ish.

    User wants real proportions; non-square always returns pixels.
    Square + exact official K may keep token for wan2.7 convenience.
    """
    if not limits.allow_k_tokens or k_level is None:
        return None
    if abs(w - h) > max(16, int(0.02 * max(w, h))):
        return None  # non-square → always pixels
    # Map nearest official token
    candidates = []
    for t in limits.allow_k_tokens:
        lvl = _parse_k_level(t)
        if lvl is not None:
            candidates.append((abs(lvl - k_level), t))
    if not candidates:
        return None
    candidates.sort()
    # only if close enough (within 0.6K)
    if candidates[0][0] <= 0.6:
        return candidates[0][1]
    return None


def _build_size_pixels(
    *,
    aspect: str | None,
    k_level: float | None,
    explicit_wh: tuple[int, int] | None,
    model_id: str,
    editing: bool = False,
    interleave: bool = False,
) -> str | None:
    """Build final size string for API (always clamped)."""
    limits = _image_size_limits(model_id, editing=editing, interleave=interleave)

    if explicit_wh is not None:
        w, h = explicit_wh
        w, h = _clamp_wh(w, h, limits)
        return _format_wh(w, h)

    # default aspect when only K given → square
    aw, ah = 1, 1
    if aspect and aspect in _ASPECT_RATIOS:
        aw, ah = _ASPECT_RATIOS[aspect]
    elif aspect:
        # try parse "a:b"
        m = re.fullmatch(r"(\d{1,2}):(\d{1,2})", aspect)
        if m:
            aw, ah = int(m.group(1)), int(m.group(2))

    if k_level is None and aspect is None:
        return None

    # default K when only aspect given: use ~model mid-band long edge
    if k_level is None:
        # target near geometric mean of min/max total for 1:1, then long edge
        mid_side = int(round(sqrt((limits.min_total + limits.max_total) / 2)))
        long_edge = mid_side
    else:
        long_edge = _k_level_to_long_edge(k_level)

    w, h = _size_from_aspect_and_long_edge(aw, ah, long_edge)
    w, h = _clamp_wh(w, h, limits)

    # optional token for square + wan2.7
    token = _maybe_k_token(w, h, k_level, limits)
    if token:
        return token
    return _format_wh(w, h)


def _normalize_size_token(raw: str) -> str | None:
    """Normalize user/config size string. Returns None if empty/auto."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    low = s.lower()
    if low in {"auto", "default", "none", "自动", "默认", "不限制", "不指定"}:
        return None
    # N K
    if re.fullmatch(r"\d{1,2}k", low):
        return low.upper() if low.endswith("k") else s
    # 1024x1024 / 1024*1024 / 1024×1024
    compact = s.replace(" ", "").replace("×", "*").replace("x", "*").replace("X", "*")
    m = _SIZE_EXPLICIT_RE.fullmatch(compact)
    if m:
        return f"{int(m.group('w'))}*{int(m.group('h'))}"
    m = _SIZE_EXPLICIT_RE.search(compact)
    if m and compact == f"{m.group('w')}*{m.group('h')}":
        return f"{int(m.group('w'))}*{int(m.group('h'))}"
    # aspect only in config e.g. 16:9
    if re.fullmatch(r"\d{1,2}:\d{1,2}", compact):
        return compact
    return compact


def _detect_aspect_from_prompt(prompt: str) -> str | None:
    """Infer aspect ratio keyword from natural-language prompt."""
    if not prompt:
        return None
    p = prompt

    for m in _ASPECT_RE.finditer(p):
        a, b = int(m.group("a")), int(m.group("b"))
        if a <= 0 or b <= 0 or a > 32 or b > 32:
            continue
        g = gcd(a, b)
        key = f"{a // g}:{b // g}"
        if key in _ASPECT_RATIOS:
            return key

    rules = [
        (r"21\s*[:：/]\s*9|超宽|带鱼屏|电影宽屏", "21:9"),
        (r"16\s*[:：/]\s*9|横版|横图|横屏|宽屏|landscape|widescreen|桌面壁纸|电脑壁纸", "16:9"),
        (r"9\s*[:：/]\s*16|竖版|竖图|竖屏|手机壁纸|全面屏|portrait|story|短视频封面", "9:16"),
        (r"4\s*[:：/]\s*3", "4:3"),
        (r"3\s*[:：/]\s*4", "3:4"),
        (r"3\s*[:：/]\s*2", "3:2"),
        (r"2\s*[:：/]\s*3", "2:3"),
        (r"1\s*[:：/]\s*1|正方形|方形|方图|头像|square", "1:1"),
    ]
    for pat, aspect in rules:
        if re.search(pat, p, flags=re.I):
            return aspect
    return None


def _detect_k_level_from_prompt(prompt: str) -> float | None:
    """Detect 1K/2K/4K/8K... from prompt; pick the largest if multiple."""
    if not prompt:
        return None
    levels = [float(m.group(1)) for m in _K_TOKEN_RE.finditer(prompt)]
    if not levels:
        return None
    return max(levels)


def _detect_size_from_prompt(
    prompt: str,
    model_id: str,
    *,
    editing: bool = False,
    interleave: bool = False,
) -> str | None:
    """Parse size intent from prompt → clamped width*height (or official token)."""
    if not prompt:
        return None

    # 1) explicit pixels
    m = _SIZE_EXPLICIT_RE.search(prompt.replace("×", "*"))
    if m:
        w, h = int(m.group("w")), int(m.group("h"))
        if 64 <= w <= 16384 and 64 <= h <= 16384:
            return _build_size_pixels(
                aspect=None,
                k_level=None,
                explicit_wh=(w, h),
                model_id=model_id,
                editing=editing,
                interleave=interleave,
            )

    # 2) aspect + K (aspect may be None; K may be None)
    aspect = _detect_aspect_from_prompt(prompt)
    k_level = _detect_k_level_from_prompt(prompt)
    if aspect is None and k_level is None:
        return None
    return _build_size_pixels(
        aspect=aspect,
        k_level=k_level,
        explicit_wh=None,
        model_id=model_id,
        editing=editing,
        interleave=interleave,
    )


def _resolve_image_size(
    mc: dict,
    prompt: str,
    model_id: str,
    *,
    editing: bool = False,
    interleave: bool = False,
) -> str | None:
    """Resolve final size for API.

    Priority:
      1. model_config.size if fixed (not auto/empty)
      2. parse from prompt (16:9 / 竖图 / 4k 横屏 / 1920x1080)
      3. None -> omit size, let model default

    Always:
      - convert N K to real pixels with aspect
      - clamp to the target model's max/min limits
      - editing/ref-image mode clamps to 2K max (never 4K)
      - interleave/text-only wan2.6-image clamps to ~1280^2
    """
    mc = mc or {}
    cfg = _normalize_size_token(mc.get("size"))
    if cfg is not None:
        # config may be "2K", "16:9", "1920*1080"
        k_level = _parse_k_level(cfg)
        if k_level is not None:
            return _build_size_pixels(
                aspect=None,
                k_level=k_level,
                explicit_wh=None,
                model_id=model_id,
                editing=editing,
                interleave=interleave,
            )
        if re.fullmatch(r"\d{1,2}:\d{1,2}", cfg):
            return _build_size_pixels(
                aspect=cfg,
                k_level=None,
                explicit_wh=None,
                model_id=model_id,
                editing=editing,
                interleave=interleave,
            )
        m = _SIZE_EXPLICIT_RE.fullmatch(cfg.replace("×", "*").replace("x", "*").replace("X", "*"))
        if m:
            return _build_size_pixels(
                aspect=None,
                k_level=None,
                explicit_wh=(int(m.group("w")), int(m.group("h"))),
                model_id=model_id,
                editing=editing,
                interleave=interleave,
            )
        # unknown fixed string — still try clamp if looks like w*h
        m = _SIZE_EXPLICIT_RE.search(str(cfg))
        if m:
            return _build_size_pixels(
                aspect=None,
                k_level=None,
                explicit_wh=(int(m.group("w")), int(m.group("h"))),
                model_id=model_id,
                editing=editing,
                interleave=interleave,
            )
        # token passthrough (e.g. "4K") is unsafe in constrained modes
        if editing or interleave:
            k_edit = _parse_k_level(cfg)
            if k_edit is not None:
                return _build_size_pixels(
                    aspect=None,
                    k_level=min(k_edit, 1.0 if interleave else 2.0),
                    explicit_wh=None,
                    model_id=model_id,
                    editing=editing,
                    interleave=interleave,
                )
        return cfg  # last resort pass-through

    return _detect_size_from_prompt(
        prompt or "", model_id, editing=editing, interleave=interleave
    )


class BailianImageClient(ImageModelClient):
    """Wanxiang text-to-image via DashScope async task API."""

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    def _create_url(self, http_base: str, model_id: str) -> str:
        """Pick async create endpoint by model generation.

        Official (async):
        - wan2.6 / wan2.7: .../aigc/image-generation/generation
        - wan2.5 / wan2.2 / wanx2.x / wanx-v1: .../aigc/text2image/image-synthesis
        """
        mid = (model_id or "").lower().replace("_", ".")
        if mid.startswith("wan2.6") or mid.startswith("wan2.7"):
            return f"{http_base}/services/aigc/image-generation/generation"
        return f"{http_base}/services/aigc/text2image/image-synthesis"

    @staticmethod
    def _is_messages_image_model(model_id: str) -> bool:
        """wan2.6+ use messages protocol; older use input.prompt."""
        mid = (model_id or "").lower().replace("_", ".")
        return mid.startswith("wan2.6") or mid.startswith("wan2.7")

    @staticmethod
    def _is_pure_t2i_model(model_id: str) -> bool:
        """Pure text-to-image models that reject reference images."""
        mid = (model_id or "").lower().replace("_", ".")
        # wan2.6-t2i / wan2.5-t2i-* / wan2.2-t2i-* / wanx*-t2i-*
        if "t2i" in mid:
            return True
        return False

    @staticmethod
    def _is_edit_image_model(model_id: str) -> bool:
        """Models designed for image edit / multimodal (accept refs)."""
        mid = (model_id or "").lower().replace("_", ".")
        if mid.startswith("wan2.7"):
            return True
        if mid.startswith("wan2.6") and "t2i" not in mid:
            return True
        return False

    @staticmethod
    def _supports_legacy_ref_img(model_id: str) -> bool:
        """Older models that accept input.ref_img on text2image endpoint."""
        # Underscores are normalized to dots first, so wanx_v1 -> wanx.v1
        mid = (model_id or "").lower().replace("_", ".")
        return mid in ("wanx-v1", "wanx.v1")

    @staticmethod
    def _supports_messages_img2img(model_id: str) -> bool:
        """Models that accept reference images via messages content[].image."""
        return BailianImageClient._is_edit_image_model(model_id)

    @staticmethod
    def _auto_route_enabled(mc: dict | None) -> bool:
        """Whether model auto-routing is enabled (default: False)."""
        if not mc:
            return False
        return bool(mc.get("auto_route", False))

    @staticmethod
    def _resolve_img2img_model(model_id: str, auto_route: bool = False) -> str:
        """Optionally map pure t2i ids to an edit-capable model when ref is required.

        Only remaps when auto_route=True. Default is off: always keep configured id.
        """
        if not auto_route:
            return model_id
        mid = (model_id or "").lower().replace("_", ".")
        if BailianImageClient._supports_messages_img2img(model_id):
            return model_id
        if BailianImageClient._supports_legacy_ref_img(model_id):
            return model_id
        # Any pure t2i or unknown wan image model with refs → modern edit model
        if "t2i" in mid or mid.startswith("wan"):
            return "wan2.6-image"
        return model_id

    @staticmethod
    def _resolve_t2i_model(model_id: str, auto_route: bool = False) -> str:
        """Optionally prefer pure-t2i model for text-only generation.

        Only remaps when auto_route=True. Default is off: always keep configured id.
        """
        if not auto_route:
            return model_id
        mid = (model_id or "").lower().replace("_", ".")
        if mid.startswith("wan2.6") and "t2i" not in mid and "image" in mid:
            return "wan2.6-t2i"
        return model_id

    @staticmethod
    def _normalize_ref_uri(value: str | None) -> str | None:
        """Normalize a candidate reference URI; reject empty/malformed data URLs."""
        if not value:
            return None
        val = str(value).strip()
        if not val:
            return None
        if val.startswith(("http://", "https://")):
            return val
        if val.startswith("data:"):
            header, separator, payload = val.partition(",")
            # Require a non-empty payload after the comma. Also require a base64
            # marker in the header for DashScope data-url acceptance; bare
            # data:image/png, / data:image/png;base64 (no payload) are invalid.
            if not separator or not payload.strip():
                return None
            if ";base64" not in header.lower():
                return None
            return val
        return None

    async def _image_to_ref_uri(self, image: Image) -> str | None:
        """Convert KiraAI Image to a DashScope-accepted image URI (url or data-url)."""
        if image is None:
            return None
        file_type = getattr(image, "file_type", None) or getattr(image, "image_type", None)
        file_val = getattr(image, "file", None) or getattr(image, "image", None)
        if file_type == "url" and file_val:
            return self._normalize_ref_uri(str(file_val))
        # Prefer data URL for local/base64 images
        if hasattr(image, "to_data_url"):
            try:
                data_url = await image.to_data_url()
                normalized = self._normalize_ref_uri(str(data_url) if data_url else None)
                if normalized:
                    return normalized
            except Exception as e:
                logger.warning(f"Bailian Image: to_data_url failed: {e}")
        if file_val and str(file_val).startswith(("http://", "https://", "data:")):
            return self._normalize_ref_uri(str(file_val))
        if hasattr(image, "to_base64"):
            try:
                b64 = await image.to_base64()
                if not b64:
                    return None
                mime = getattr(image, "mime", None) or "image/png"
                return self._normalize_ref_uri(f"data:{mime};base64,{b64}")
            except Exception as e:
                logger.warning(f"Bailian Image: to_base64 failed: {e}")
        return None

    async def _poll_image_task(
        self,
        client: httpx.AsyncClient,
        *,
        http_base: str,
        api_key: str,
        task_id: str,
        timeout: int,
        label: str = "Image",
    ) -> Image:
        task_url = f"{http_base}/tasks/{task_id}"
        poll_headers = {"Authorization": f"Bearer {api_key}"}
        # Monotonic clock: immune to wall-clock jumps that would extend/shorten
        # the configured timeout unexpectedly.
        start = time.monotonic()
        total_timeout = max(1, int(timeout or 1))
        while True:
            remaining = total_timeout - (time.monotonic() - start)
            if remaining <= 0:
                break
            # Bound each poll HTTP request to the remaining overall deadline so a
            # short configured timeout cannot be exceeded by the client default.
            tr = await client.get(
                task_url,
                headers=poll_headers,
                timeout=max(0.1, remaining),
            )
            tr.raise_for_status()
            tdata = tr.json()
            output = (tdata.get("output") or {}) if isinstance(tdata, dict) else {}
            status = (output.get("task_status") or tdata.get("task_status") or "").upper()
            if status == "SUCCEEDED":
                url = self._extract_image_url(output, tdata)
                if not url:
                    raise RuntimeError(f"Bailian {label} succeeded but no url: {tdata}")
                return Image(image=url)
            if status in ("FAILED", "CANCELED", "UNKNOWN"):
                msg = output.get("message") or tdata.get("message") or status
                code = output.get("code") or tdata.get("code") or ""
                raise RuntimeError(f"Bailian {label} failed: {code} {msg}".strip())
            remaining_after = total_timeout - (time.monotonic() - start)
            if remaining_after <= 0:
                break
            await asyncio.sleep(min(2.0, remaining_after))
        raise TimeoutError(f"Bailian {label} timed out after {total_timeout}s")

    @staticmethod
    def _extract_image_url(output: dict, tdata: dict | None = None) -> str | None:
        """Extract first image URL from async task success payload.

        - Old protocol (wan2.5-): output.results[].url
        - New protocol (wan2.6+): output.choices[].message.content[].image
        """
        if not isinstance(output, dict):
            return None

        # Old: results[].url
        results = output.get("results") or []
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("image")
                    if url:
                        return url

        # New: choices[].message.content[].image
        choices = output.get("choices") or []
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, list):
                    for part in content:
                        if isinstance(part, dict):
                            url = part.get("image") or part.get("url")
                            if url:
                                return url
                elif isinstance(content, dict):
                    url = content.get("image") or content.get("url")
                    if url:
                        return url
                elif isinstance(content, str) and content.startswith("http"):
                    return content

        # Rare top-level fallbacks
        if tdata and isinstance(tdata, dict):
            for key in ("url", "image_url", "image"):
                if tdata.get(key):
                    return tdata.get(key)
        return None

    def _build_payload(self, prompt: str, size: str | None = None, model_id: str | None = None) -> dict:
        mc = self.model.model_config or {}
        model_id = model_id or self.model.model_id
        n = int(mc.get("n", 1) or 1)
        n = max(1, min(4, n))
        negative_prompt = (mc.get("negative_prompt") or "").strip()
        seed = mc.get("seed")
        prompt_extend = mc.get("prompt_extend", True)
        watermark = mc.get("watermark", False)

        mid = (model_id or "").lower().replace("_", ".")
        # wan2.6 / wan2.7 use messages protocol (official)
        if self._is_messages_image_model(model_id):
            # Text-only wan2.6-image is treated as generation (not edit).
            # Without enable_interleave the API may reject prompt-only calls.
            text_only_wan26_image = (
                mid.startswith("wan2.6")
                and "t2i" not in mid
                and "image" in mid
            )
            # size: None means omit (API model default); never force 1024*1024
            if size is None:
                size = _resolve_image_size(
                    mc, prompt, model_id, interleave=text_only_wan26_image
                )
            parameters = {
                "n": 1 if text_only_wan26_image else n,
                "prompt_extend": bool(prompt_extend),
                "watermark": bool(watermark),
            }
            if text_only_wan26_image:
                parameters["enable_interleave"] = True
                parameters["max_images"] = 1
            if size:
                parameters["size"] = size
            if negative_prompt:
                parameters["negative_prompt"] = negative_prompt
            if seed is not None and str(seed).strip() != "":
                try:
                    parameters["seed"] = int(seed)
                except (TypeError, ValueError):
                    pass
            # wan2.7 supports thinking_mode; keep optional from config
            if "thinking_mode" in mc and mid.startswith("wan2.7"):
                parameters["thinking_mode"] = bool(mc.get("thinking_mode"))
            payload = {
                "model": model_id,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            # official examples use {"text": "..."} without type
                            "content": [{"text": prompt}],
                        }
                    ]
                },
                "parameters": parameters,
            }
            return payload

        # size for older non-messages models
        if size is None:
            size = _resolve_image_size(mc, prompt, model_id)

        payload = {
            "model": model_id,
            "input": {
                "prompt": prompt,
            },
            "parameters": {
                "n": n,
            },
        }
        if size:
            payload["parameters"]["size"] = size
        if negative_prompt:
            payload["input"]["negative_prompt"] = negative_prompt
        if seed is not None and str(seed).strip() != "":
            try:
                payload["parameters"]["seed"] = int(seed)
            except (TypeError, ValueError):
                pass
        # style only for wanx-v1 (underscore already normalized to dot)
        style = (mc.get("style") or "").strip()
        if style and mid in ("wanx-v1", "wanx.v1"):
            payload["parameters"]["style"] = style
        if "prompt_extend" in mc:
            payload["parameters"]["prompt_extend"] = bool(prompt_extend)
        if "watermark" in mc:
            payload["parameters"]["watermark"] = bool(watermark)
        return payload

    async def text_to_image(self, prompt: str) -> Image:
        mp = self.model.provider_config or {}
        mc = self.model.model_config or {}
        api_key = (mp.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("Bailian Image: api_key is not configured")

        configured = self.model.model_id
        auto_route = self._auto_route_enabled(mc)
        model_id = self._resolve_t2i_model(configured, auto_route=auto_route)
        if model_id != configured:
            logger.info(
                f"Bailian Image auto_route: pure-text {configured!r} → {model_id!r}"
            )

        timeout = int(mc.get("timeout", 120) or 120)
        http_base = resolve_http_base_url(mp).rstrip("/")
        create_url = self._create_url(http_base, model_id)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }
        # _build_payload resolves size with model-specific mode
        # (e.g. wan2.6-image text-only uses interleave limits ~1280^2).
        payload = self._build_payload(prompt, size=None, model_id=model_id)
        size = (payload.get("parameters") or {}).get("size")
        logger.info(
            f"Bailian Image size resolved: config={mc.get('size')!r} -> {size!r} "
            f"(model={model_id})"
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(create_url, json=payload, headers=headers)
            if resp.status_code >= 400:
                try:
                    err_body = resp.text
                except Exception:
                    err_body = ""
                logger.error(f"Bailian Image HTTP {resp.status_code}: {err_body[:800]}")
                resp.raise_for_status()
            data = resp.json()

            task_id = None
            if isinstance(data, dict):
                output = data.get("output") or {}
                task_id = output.get("task_id") or data.get("task_id")
            if not task_id:
                raise RuntimeError(f"Bailian Image: no task_id in response: {data}")

            return await self._poll_image_task(
                client,
                http_base=http_base,
                api_key=api_key,
                task_id=task_id,
                timeout=timeout,
                label="Image",
            )

    async def image_to_image(self, prompt: str, image: Union[Image, list[Image]]) -> Image:
        """Image-to-image / edit with reference image(s).

        Protocol (always, independent of auto_route):
          - wan2.6-image / wan2.7-image*: messages + content[].image
          - wanx-v1: legacy text2image + ref_img
          - pure t2i without auto_route: raise clear error (model cannot take refs)
          - pure t2i with auto_route=True: remap to wan2.6-image
          - if no usable ref URI: fall back to text_to_image(prompt)
        """
        if isinstance(image, Image):
            images = [image]
        else:
            images = list(image or [])

        mp = self.model.provider_config or {}
        mc = self.model.model_config or {}
        api_key = (mp.get("api_key") or "").strip()
        if not api_key:
            raise RuntimeError("Bailian Image: api_key is not configured")

        # Collect up to 4 *valid* reference URIs (official edit limit).
        # Validate first, then cap — so an invalid early image does not
        # prevent a later valid one from being used.
        ref_uris: list[str] = []
        for img in images:
            uri = await self._image_to_ref_uri(img)
            if uri:
                ref_uris.append(uri)
                if len(ref_uris) == 4:
                    break

        configured_model = self.model.model_id
        if not ref_uris:
            logger.warning(
                "Bailian Image2Image: no usable reference image, falling back to text_to_image "
                f"(model={configured_model})"
            )
            return await self.text_to_image(prompt)

        auto_route = self._auto_route_enabled(mc)
        model_id = self._resolve_img2img_model(configured_model, auto_route=auto_route)
        if model_id != configured_model:
            logger.info(
                f"Bailian Image2Image auto_route: {configured_model!r} → {model_id!r} "
                f"(reference image requires an edit-capable model)"
            )

        # Configured model cannot take refs and auto_route is off
        if (
            not self._supports_messages_img2img(model_id)
            and not self._supports_legacy_ref_img(model_id)
        ):
            raise RuntimeError(
                f"Bailian Image2Image: model {model_id!r} does not support reference images. "
                f"Use wan2.6-image / wan2.7-image, or enable model_config.auto_route "
                f"(default is off)."
            )

        timeout = int(mc.get("timeout", 120) or 120)
        http_base = resolve_http_base_url(mp).rstrip("/")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "X-DashScope-Async": "enable",
        }

        # Size: resolve against the *actual* model we will call.
        # Editing / ref-image path must clamp to 2K (never send 4K).
        size = _resolve_image_size(mc, prompt, model_id, editing=True)
        negative_prompt = (mc.get("negative_prompt") or "").strip()
        prompt_extend = mc.get("prompt_extend", True)
        watermark = mc.get("watermark", False)
        seed = mc.get("seed")

        # ── Path A: modern messages img2img (wan2.6-image / wan2.7-*) ──
        if self._supports_messages_img2img(model_id):
            create_url = f"{http_base}/services/aigc/image-generation/generation"
            content: list[dict] = [{"text": prompt}]
            for uri in ref_uris:
                content.append({"image": uri})

            parameters: dict = {
                "n": 1,
                "prompt_extend": bool(prompt_extend),
                "watermark": bool(watermark),
                "enable_interleave": False,  # image edit mode (requires refs)
            }
            if size:
                parameters["size"] = size
            if negative_prompt:
                parameters["negative_prompt"] = negative_prompt
            if seed is not None and str(seed).strip() != "":
                try:
                    parameters["seed"] = int(seed)
                except (TypeError, ValueError):
                    pass
            if "thinking_mode" in mc and str(model_id).lower().startswith("wan2.7"):
                parameters["thinking_mode"] = bool(mc.get("thinking_mode"))

            payload = {
                "model": model_id,
                "input": {
                    "messages": [
                        {
                            "role": "user",
                            "content": content,
                        }
                    ]
                },
                "parameters": parameters,
            }
            logger.info(
                f"Bailian Image2Image (messages): model={model_id}, refs={len(ref_uris)}, size={size!r}"
            )

            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(create_url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    try:
                        err_body = resp.text
                    except Exception:
                        err_body = ""
                    logger.error(
                        f"Bailian Image2Image HTTP {resp.status_code}: {err_body[:800]}"
                    )
                    resp.raise_for_status()
                data = resp.json()
                output = data.get("output") or {}
                task_id = output.get("task_id") or data.get("task_id")
                if not task_id:
                    raise RuntimeError(f"Bailian Image2Image: no task_id: {data}")
                return await self._poll_image_task(
                    client,
                    http_base=http_base,
                    api_key=api_key,
                    task_id=task_id,
                    timeout=timeout,
                    label="Image2Image",
                )

        # ── Path B: legacy wanx-v1 style ref_img only ──
        if self._supports_legacy_ref_img(model_id):
            create_url = f"{http_base}/services/aigc/text2image/image-synthesis"
            payload = {
                "model": model_id,
                "input": {
                    "prompt": prompt,
                    "ref_img": ref_uris[0],
                },
                "parameters": {
                    "n": 1,
                },
            }
            if size:
                payload["parameters"]["size"] = size
            ref_mode = (mc.get("ref_mode") or "repaint").strip()
            payload["parameters"]["ref_mode"] = ref_mode
            if mc.get("ref_strength") is not None:
                try:
                    payload["parameters"]["ref_strength"] = float(mc.get("ref_strength"))
                except (TypeError, ValueError):
                    pass
            if negative_prompt:
                payload["input"]["negative_prompt"] = negative_prompt

            logger.info(
                f"Bailian Image2Image (legacy ref_img): model={model_id}, size={size!r}"
            )
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(create_url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    try:
                        err_body = resp.text
                    except Exception:
                        err_body = ""
                    logger.error(
                        f"Bailian Image2Image HTTP {resp.status_code}: {err_body[:800]}"
                    )
                    resp.raise_for_status()
                data = resp.json()
                output = data.get("output") or {}
                task_id = output.get("task_id") or data.get("task_id")
                if not task_id:
                    raise RuntimeError(f"Bailian Image2Image: no task_id: {data}")
                return await self._poll_image_task(
                    client,
                    http_base=http_base,
                    api_key=api_key,
                    task_id=task_id,
                    timeout=timeout,
                    label="Image2Image",
                )

        # Should be unreachable: unsupported models raise earlier
        raise RuntimeError(
            f"Bailian Image2Image: no protocol handler for model {model_id!r}"
        )


# ───────────────────────────── STT ─────────────────────────────


class BailianSTTClient(STTModelClient):
    """
    Speech-to-text via Paraformer / Fun-ASR realtime Recognition.call(local file).
    """

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def speech_to_text(self, record: Record, **kwargs) -> str:
        if record is None:
            return ""

        mp = self.model.provider_config or {}
        mc = self.model.model_config or {}
        api_key = (mp.get("api_key") or "").strip()
        if not api_key:
            logger.error("Bailian STT: api_key is not configured")
            return ""

        model_id = self.model.model_id or "paraformer-realtime-v2"
        sample_rate = int(mc.get("sample_rate", 16000) or 16000)
        audio_format = (mc.get("audio_format") or "wav").lower().strip()
        language_hints_raw = (mc.get("language_hints") or "zh,en").strip()
        language_hints = [
            h.strip() for h in language_hints_raw.replace("，", ",").split(",") if h.strip()
        ] or ["zh", "en"]
        timeout = int(mc.get("timeout", 120) or 120)

        # Materialize audio to a temp file for Recognition.call
        tmp_path = None
        try:
            # Prefer existing local path
            if getattr(record, "file_type", None) == "path" and record.file and os.path.isfile(record.file):
                file_path = record.file
                # Guess format from extension
                ext = os.path.splitext(file_path)[1].lstrip(".").lower()
                if ext in ("wav", "mp3", "pcm", "opus", "aac", "amr", "speex"):
                    audio_format = ext
            else:
                b64 = await record.to_base64()
                audio_bytes = base64.b64decode(b64)
                # Infer format from mime if possible
                mime = (getattr(record, "mime", None) or "").lower()
                if "mpeg" in mime or "mp3" in mime:
                    audio_format = "mp3"
                elif "wav" in mime:
                    audio_format = "wav"
                elif "pcm" in mime:
                    audio_format = "pcm"
                elif "ogg" in mime or "opus" in mime:
                    audio_format = "opus"
                suffix = f".{audio_format}" if audio_format else ".wav"
                fd, tmp_path = tempfile.mkstemp(suffix=suffix)
                os.close(fd)
                with open(tmp_path, "wb") as f:
                    f.write(audio_bytes)
                file_path = tmp_path

            text = await asyncio.wait_for(
                asyncio.to_thread(
                    self._recognize_sync,
                    file_path=file_path,
                    api_key=api_key,
                    model_id=model_id,
                    region=_region(mp),
                    workspace_id=_workspace_id(mp),
                    sample_rate=sample_rate,
                    audio_format=audio_format,
                    language_hints=language_hints,
                ),
                timeout=timeout,
            )
            return text or ""
        except asyncio.TimeoutError:
            logger.error(f"Bailian STT timed out after {timeout}s (model={model_id})")
            return ""
        except Exception as e:
            logger.error(f"Bailian STT failed: {e}")
            return ""
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    def _recognize_sync(
        self,
        file_path: str,
        api_key: str,
        model_id: str,
        region: str,
        workspace_id: str,
        sample_rate: int,
        audio_format: str,
        language_hints: list[str],
    ) -> str:
        from http import HTTPStatus
        from dashscope.audio.asr import Recognition

        kwargs = {
            "model": model_id,
            "format": audio_format or "wav",
            "sample_rate": sample_rate,
            "callback": None,
            "api_key": api_key,
            "base_address": _resolve_ws_url(region, workspace_id),
            "workspace": workspace_id or None,
        }
        # language_hints mainly for v2 multi-lang models
        mid = (model_id or "").lower()
        if language_hints and ("v2" in mid or "fun-asr" in mid or "fun_asr" in mid):
            kwargs["language_hints"] = language_hints

        recognition = Recognition(**kwargs)
        result = recognition.call(file_path)

        if result is None:
            raise RuntimeError("STT returned empty result")

        status = getattr(result, "status_code", None)
        if status is not None and status != HTTPStatus.OK:
            msg = getattr(result, "message", "") or str(result)
            raise RuntimeError(f"STT error status={status}: {msg}")

        # get_sentence may return list[dict] or str depending on SDK version
        sentence = None
        if hasattr(result, "get_sentence"):
            sentence = result.get_sentence()
        elif hasattr(result, "output"):
            sentence = result.output

        return self._extract_text(sentence)

    @staticmethod
    def _extract_text(sentence) -> str:
        if sentence is None:
            return ""
        if isinstance(sentence, str):
            return sentence.strip()
        if isinstance(sentence, dict):
            return (sentence.get("text") or sentence.get("sentence") or "").strip()
        if isinstance(sentence, list):
            parts = []
            for item in sentence:
                if isinstance(item, dict):
                    t = item.get("text") or item.get("sentence") or ""
                    if t:
                        parts.append(str(t))
                elif isinstance(item, str) and item:
                    parts.append(item)
            return "".join(parts).strip()
        return str(sentence).strip()


# ───────────────────────────── TTS (CosyVoice) ─────────────────────────────


def _resolve_audio_format(audio_format: str):
    """Map config string to dashscope AudioFormat enum. Import lazily."""
    from dashscope.audio.tts_v2 import AudioFormat

    fmt = (audio_format or "mp3").lower().strip()
    mapping = {
        "mp3": AudioFormat.MP3_22050HZ_MONO_256KBPS,
        "wav": AudioFormat.WAV_22050HZ_MONO_16BIT,
        "pcm": AudioFormat.PCM_22050HZ_MONO_16BIT,
    }
    return mapping.get(fmt, AudioFormat.MP3_22050HZ_MONO_256KBPS)


def _resolve_mime(audio_format: str) -> str:
    fmt = (audio_format or "mp3").lower().strip()
    return {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "pcm": "audio/pcm",
    }.get(fmt, "audio/mpeg")


def _is_v1_model(model_id: str) -> bool:
    mid = (model_id or "").lower().strip()
    return mid == "cosyvoice-v1" or mid.endswith("-v1")




# CosyVoice v3.5 声音复刻音色支持的中文方言（官方文档）
# 方言通过 instruction 设置，格式：请用<方言>表达。
_COSYVOICE_DIALECTS = (
    "普通话",
    "广东话",
    "东北话",
    "甘肃话",
    "贵州话",
    "河南话",
    "湖北话",
    "江西话",
    "闽南话",
    "宁夏话",
    "山西话",
    "陕西话",
    "山东话",
    "上海话",
    "四川话",
    "天津话",
    "云南话",
)

# 常见别名 -> 官方名称
_DIALECT_ALIASES = {
    "auto": "auto",
    "automatic": "auto",
    "detect": "auto",
    "自动": "auto",
    "自动检测": "auto",
    "none": "auto",
    "default": "auto",
    "mandarin": "普通话",
    "putonghua": "普通话",
    "zh-cn": "普通话",
    "zh_cn": "普通话",
    "cmn": "普通话",
    "cantonese": "广东话",
    "yue": "广东话",
    "粤语": "广东话",
    "广东": "广东话",
    "dongbei": "东北话",
    "东北": "东北话",
    "sichuan": "四川话",
    "四川": "四川话",
    "chengdu": "四川话",
    "shanghai": "上海话",
    "上海": "上海话",
    "wu": "上海话",
    "henan": "河南话",
    "河南": "河南话",
    "shandong": "山东话",
    "山东": "山东话",
    "shanxi": "山西话",  # 山西
    "山西": "山西话",
    "shaanxi": "陕西话",
    "陕西": "陕西话",
    "hunan": "湖南话",  # 系统音色 longanhuan_v3 支持；v3.5 列表未列，仍允许用户手填
    "湖南": "湖南话",
    "湖南话": "湖南话",
    "hubei": "湖北话",
    "湖北": "湖北话",
    "anhui": "安徽话",
    "安徽": "安徽话",
    "安徽话": "安徽话",
    "minnan": "闽南话",
    "hokkien": "闽南话",
    "闽南": "闽南话",
    "tianjin": "天津话",
    "天津": "天津话",
    "yunnan": "云南话",
    "云南": "云南话",
    "guizhou": "贵州话",
    "贵州": "贵州话",
    "gansu": "甘肃话",
    "甘肃": "甘肃话",
    "ningxia": "宁夏话",
    "宁夏": "宁夏话",
    "jiangxi": "江西话",
    "江西": "江西话",
}


def _normalize_dialect(raw: str) -> str:
    """Normalize dialect config to official name, 'auto', or custom passthrough."""
    raw = (raw or "").strip()
    if not raw:
        return "auto"
    key = raw.lower() if raw.isascii() else raw
    # try alias with original and lower
    if raw in _DIALECT_ALIASES:
        return _DIALECT_ALIASES[raw]
    if key in _DIALECT_ALIASES:
        return _DIALECT_ALIASES[key]
    # exact official names
    if raw in _COSYVOICE_DIALECTS:
        return raw
    # allow "请用四川话表达" pasted by user -> extract
    m = re.search(r"请用(.+?)表达", raw)
    if m:
        name = m.group(1).strip()
        if name in _DIALECT_ALIASES:
            return _DIALECT_ALIASES[name]
        return name
    return raw


def _dialect_instruction(dialect: str) -> str:
    """Build official-style dialect instruction. Empty if auto/none."""
    d = _normalize_dialect(dialect)
    if not d or d == "auto":
        return ""
    # already a full instruction
    if d.startswith("请用") and "表达" in d:
        return d if d.endswith("。") or d.endswith(".") else d + "。"
    return f"请用{d}表达。"


def _merge_instruction(dialect: str, user_instruction: str, language_hints: list[str] | None = None) -> str:
    """Merge dialect instruction with user custom instruction.

    - dialect=auto: do not force dialect (CosyVoice default / sample accent)
    - non-Chinese language_hints: skip dialect injection (dialect is Chinese-only)
    - if user_instruction already contains dialect directive, do not duplicate
    """
    user_instruction = (user_instruction or "").strip()
    lang = (language_hints or ["zh"])[0] if language_hints else "zh"

    dialect_part = ""
    d = _normalize_dialect(dialect)
    if d and d != "auto":
        # Only inject Chinese dialect when target language is Chinese (or unknown)
        if lang in ("zh", "cmn", "yue") or not lang:
            dialect_part = _dialect_instruction(d)
        else:
            # fixed dialect but non-Chinese text: still allow if user forced dialect
            dialect_part = _dialect_instruction(d)

    if not dialect_part:
        return user_instruction

    # Avoid duplicating if user already wrote dialect instruction
    if user_instruction:
        if dialect_part.rstrip("。.") in user_instruction or "请用" in user_instruction and "表达" in user_instruction:
            return user_instruction
        return f"{dialect_part}{user_instruction}"
    return dialect_part



def _detect_language_hint(text: str) -> str:
    """Detect a CosyVoice language_hints value from text script features.

    CosyVoice currently uses only the first language hint. When config is
    "auto", we pick one dominant language for the current utterance.
    """
    if not text:
        return "zh"

    # Count script characters (ignore whitespace/punctuation for scoring)
    counts = {
        "ja": 0,  # Hiragana / Katakana
        "ko": 0,  # Hangul
        "zh": 0,  # CJK Unified Ideographs
        "en": 0,  # Latin letters
        "ru": 0,  # Cyrillic
        "ar": 0,  # Arabic
        "th": 0,  # Thai
    }

    for ch in text:
        o = ord(ch)
        if 0x3040 <= o <= 0x30FF or 0x31F0 <= o <= 0x31FF:  # kana
            counts["ja"] += 1
        elif 0xAC00 <= o <= 0xD7AF or 0x1100 <= o <= 0x11FF:  # hangul
            counts["ko"] += 1
        elif 0x4E00 <= o <= 0x9FFF or 0x3400 <= o <= 0x4DBF:  # CJK
            counts["zh"] += 1
        elif ("A" <= ch <= "Z") or ("a" <= ch <= "z"):
            counts["en"] += 1
        elif 0x0400 <= o <= 0x04FF:
            counts["ru"] += 1
        elif 0x0600 <= o <= 0x06FF:
            counts["ar"] += 1
        elif 0x0E00 <= o <= 0x0E7F:
            counts["th"] += 1

    # Japanese often mixes kana + kanji: if any kana exists, prefer ja
    if counts["ja"] > 0:
        return "ja"
    if counts["ko"] > 0:
        return "ko"

    # Mixed CJK + Latin: prefer Chinese when there is meaningful CJK content
    if counts["zh"] > 0 and counts["en"] > 0:
        # e.g. Chinese sentence mixed with a few English words -> zh
        if counts["zh"] >= 2 or counts["zh"] >= counts["en"] * 0.3:
            return "zh"

    # Prefer the script with the highest count among remaining
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top_lang, top_n = ranked[0]
    if top_n <= 0:
        return "zh"
    return top_lang


def _resolve_language_hints(raw: str, text: str) -> list[str]:
    """Resolve language_hints config into a list for CosyVoice.

    - auto / empty -> detect from text
    - zh,ja / zh，ja -> take first fixed value (official currently uses first only)
    """
    raw = (raw or "").strip()
    auto_tokens = {"auto", "automatic", "detect", "自动", "自动检测"}
    if not raw or raw.lower() in auto_tokens or raw in auto_tokens:
        return [_detect_language_hint(text)]

    # Support both English and Chinese commas
    parts = [p.strip() for p in raw.replace("，", ",").split(",") if p.strip()]
    if not parts:
        return [_detect_language_hint(text)]

    # If user explicitly puts auto as first token, still detect
    first = parts[0]
    if first.lower() in auto_tokens or first in auto_tokens:
        return [_detect_language_hint(text)]
    return [first]



class BailianCosyVoiceTTSClient(TTSModelClient):
    """
    Alibaba Cloud Bailian (DashScope) CosyVoice TTS client.

    - model_id: e.g. cosyvoice-v3.5-plus / cosyvoice-v3-flash / cosyvoice-v2 ...
    - voice: system voice (longanyang) or cloned voice ID from Bailian console
    """

    def __init__(self, model: ModelInfo):
        super().__init__(model)

    async def text_to_speech(self, text: str, **kwargs) -> Optional[Record]:
        if not text or not str(text).strip():
            logger.warning("Bailian CosyVoice TTS: empty text, skip")
            return None

        text = str(text).strip()
        if len(text) > _MAX_TEXT_CHARS:
            logger.warning(
                f"Bailian CosyVoice TTS: text length {len(text)} exceeds {_MAX_TEXT_CHARS}, truncating"
            )
            text = text[:_MAX_TEXT_CHARS]

        mp = self.model.provider_config or {}
        mc = self.model.model_config or {}

        api_key = (mp.get("api_key") or "").strip()
        if not api_key:
            logger.error("Bailian CosyVoice TTS: api_key is not configured")
            return None

        voice = (mc.get("voice") or "").strip()
        if not voice:
            logger.error("Bailian CosyVoice TTS: voice is not configured")
            return None

        model_id = self.model.model_id
        region = _region(mp)
        workspace_id = _workspace_id(mp)

        volume = int(mc.get("volume", 50) or 50)
        speech_rate = float(mc.get("speech_rate", 1.0) or 1.0)
        pitch_rate = float(mc.get("pitch_rate", 1.0) or 1.0)
        audio_format = (mc.get("audio_format") or "mp3").lower().strip()
        language_hints_raw = (mc.get("language_hints") or "auto").strip()
        dialect_raw = (mc.get("dialect") or "auto").strip()
        instruction_raw = (mc.get("instruction") or "").strip()

        section_advanced = mc.get("section_advanced") or {}
        if not isinstance(section_advanced, dict):
            section_advanced = {}
        timeout = int(section_advanced.get("timeout", 60) or 60)
        enable_markdown_filter = bool(section_advanced.get("enable_markdown_filter", False))

        language_hints = _resolve_language_hints(language_hints_raw, text)
        instruction = _merge_instruction(dialect_raw, instruction_raw, language_hints)
        logger.debug(
            f"Bailian CosyVoice TTS language_hints resolved: config={language_hints_raw!r} -> {language_hints}; dialect={dialect_raw!r}; instruction={instruction!r}"
        )

        try:
            # Run blocking synthesis off the event loop. The sync path holds
            # _DASHSCOPE_LOCK until the SDK call actually returns; timeout is
            # enforced inside the SDK (timeout_millis), not by abandoning a
            # future and unlocking early.
            loop = asyncio.get_running_loop()
            audio_bytes = await loop.run_in_executor(
                None,
                lambda: self._synth_sync(
                    text=text,
                    api_key=api_key,
                    model_id=model_id,
                    voice=voice,
                    region=region,
                    workspace_id=workspace_id,
                    volume=volume,
                    speech_rate=speech_rate,
                    pitch_rate=pitch_rate,
                    audio_format=audio_format,
                    language_hints=language_hints,
                    instruction=instruction,
                    enable_markdown_filter=enable_markdown_filter,
                    timeout_sec=timeout,
                ),
            )
        except Exception as e:
            # Surface SDK/timeout failures; do not invent silent empty audio.
            if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
                logger.error(
                    f"Bailian CosyVoice TTS timed out after {timeout}s (model={model_id})"
                )
            else:
                logger.error(f"Bailian CosyVoice TTS failed: {e}")
            return None

        if not audio_bytes:
            logger.error("Bailian CosyVoice TTS returned empty audio")
            return None

        b64_str = base64.b64encode(audio_bytes).decode("utf-8")
        return Record(record=b64_str, mime=_resolve_mime(audio_format))

    @staticmethod
    def _call_speech_synthesizer(synthesizer, text: str, timeout_ms: int):
        """Invoke CosyVoice synthesizer.call with SDK-native timeout when available.

        Must be called while holding `_DASHSCOPE_LOCK`. The call is synchronous:
        we never unlock while synthesis may still be in flight.
        """
        try:
            sig = inspect.signature(synthesizer.call)
            if "timeout_millis" in sig.parameters:
                return synthesizer.call(text, timeout_millis=timeout_ms)
        except (TypeError, ValueError) as e:
            logger.debug(f"Bailian CosyVoice: timeout_millis unavailable ({e})")
        # Older SDKs without timeout_millis: block until the SDK returns.
        # Premature unlock would race on process-global dashscope.api_key.
        return synthesizer.call(text)

    def _synth_sync(
        self,
        text: str,
        api_key: str,
        model_id: str,
        voice: str,
        region: str,
        workspace_id: str,
        volume: int,
        speech_rate: float,
        pitch_rate: float,
        audio_format: str,
        language_hints: list[str],
        instruction: str,
        enable_markdown_filter: bool,
        timeout_sec: int = 60,
    ) -> bytes:
        """Synchronous CosyVoice synthesis via DashScope SDK (run in thread).

        Mutates process-global dashscope.api_key under `_DASHSCOPE_LOCK`.
        Uses ONE shared deadline for lock acquisition + synthesis. The lock is
        held until the SDK call returns (success, error, or SDK-native timeout).
        Never releases the lock based on a local future wait alone.
        """
        from dashscope.audio.tts_v2 import SpeechSynthesizer

        fmt = _resolve_audio_format(audio_format)

        kwargs = {
            "model": model_id,
            "voice": voice,
            "format": fmt,
            "volume": max(0, min(100, volume)),
            "speech_rate": max(0.5, min(2.0, speech_rate)),
            "pitch_rate": max(0.5, min(2.0, pitch_rate)),
        }

        if language_hints and not _is_v1_model(model_id):
            kwargs["language_hints"] = language_hints[:1]

        if instruction:
            kwargs["instruction"] = instruction

        additional_params = {}
        if enable_markdown_filter:
            additional_params["enable_markdown_filter"] = True
        if additional_params:
            kwargs["additional_params"] = additional_params

        # Single overall deadline: lock wait budget + remaining synthesis budget.
        call_timeout = max(1, int(timeout_sec or 60))
        deadline = time.monotonic() + call_timeout
        synthesizer = None
        audio = None

        lock_budget = max(0.01, deadline - time.monotonic())
        acquired = _DASHSCOPE_LOCK.acquire(timeout=lock_budget)
        if not acquired:
            raise TimeoutError(
                f"CosyVoice waiting for DashScope lock timed out after {call_timeout}s"
            )
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"CosyVoice overall deadline exceeded after waiting for lock "
                    f"({call_timeout}s)"
                )

            import dashscope

            dashscope.api_key = api_key
            synthesizer = SpeechSynthesizer(
                **kwargs,
                workspace=workspace_id or None,
                url=_resolve_ws_url(region, workspace_id),
            )

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(
                    f"CosyVoice overall deadline exceeded before synthesis "
                    f"({call_timeout}s)"
                )
            timeout_ms = max(1, int(remaining * 1000))

            # Blocking SDK call under the lock. Unlock only after this returns.
            audio = self._call_speech_synthesizer(synthesizer, text, timeout_ms)
        finally:
            _DASHSCOPE_LOCK.release()

        if audio is None:
            try:
                if synthesizer is not None:
                    resp = synthesizer.get_response()
                    logger.error(f"Bailian CosyVoice empty audio, response={resp}")
            except Exception as e:
                logger.debug(f"Bailian CosyVoice get_response after empty audio failed: {e}")
            raise RuntimeError("CosyVoice returned empty audio")

        if isinstance(audio, (bytes, bytearray)):
            return bytes(audio)

        if hasattr(audio, "get_audio_data"):
            data = audio.get_audio_data()
            if data:
                return bytes(data)

        raise RuntimeError(f"Unexpected CosyVoice audio type: {type(audio)}")
