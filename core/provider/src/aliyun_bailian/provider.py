import httpx

from core.provider import ModelType, BaseProvider

from .model_clients import (
    BailianLLMClient,
    BailianCosyVoiceTTSClient,
    BailianSTTClient,
    BailianImageClient,
    BailianEmbeddingClient,
    BailianRerankClient,
    resolve_compatible_base_url,
)


def _tag(model_type: str, text: str = "") -> str:
    """Prefix description with a type tag for WebUI display."""
    prefix = f"[{model_type.upper()}]"
    text = (text or "").strip()
    if not text:
        return prefix
    if text.startswith("["):
        return text
    return f"{prefix} {text}"


def _infer_type(model_id: str) -> str:
    """
    Best-effort type inference from model id.
    Used only for display tags.
    Order matters: video/tts/stt before broad wan/image prefixes.
    """
    mid = (model_id or "").lower().strip()
    if not mid:
        return "llm"
    if mid.startswith("cosyvoice") or "tts" in mid or mid.startswith("sambert"):
        return "tts"
    if (
        mid.startswith("paraformer")
        or mid.startswith("fun-asr")
        or mid.startswith("fun_asr")
        or "asr" in mid
        or mid.startswith("sensevoice")
    ):
        return "stt"
    # Video before image: wan2.x-i2v / t2v / r2v / s2v / kf2v / *-video*
    # must not be tagged as image.
    if (
        "video" in mid
        or "i2v" in mid
        or "t2v" in mid
        or "r2v" in mid
        or "s2v" in mid
        or "kf2v" in mid
        or (("i2i" in mid) and ("video" in mid))
        or "-vace" in mid
    ):
        return "video"
    if "embedding" in mid or mid.startswith("text-embedding"):
        return "embedding"
    if "rerank" in mid:
        return "rerank"
    if (
        mid.startswith("wanx")
        or "t2i" in mid
        or mid.startswith("flux")
        or ("image" in mid and "video" not in mid)
        or (
            mid.startswith("wan")
            and "i2v" not in mid
            and "t2v" not in mid
            and "r2v" not in mid
            and "s2v" not in mid
            and "kf2v" not in mid
            and "-vace" not in mid
            and "video" not in mid
        )
    ):
        return "image"
    return "llm"


def _annotate(item: dict, forced_type: str | None = None) -> dict:
    """Return a shallow-copied model dict with type-tagged description."""
    out = dict(item)
    mid = out.get("id") or ""
    mtype = forced_type or _infer_type(mid)
    out["description"] = _tag(mtype, out.get("description") or "")
    # Keep raw type for potential future UI use (harmless extra field)
    out.setdefault("type", mtype)
    return out


# DashScope models that are real and callable via native / WS APIs, but are
# typically ABSENT from OpenAI-compatible GET /models (which mostly lists chat
# LLMs). These are NOT a failure fallback: they are only merged AFTER a successful
# remote listing, and never override a same-id entry already returned by remote.
#
# Sources: Aliyun Model Studio official model docs (TTS / STT / image / embedding).
_DASH_SCOPE_NATIVE_CATALOG: list[tuple[list[dict], str]] = [
    (
        [
            {
                "id": "cosyvoice-v3.5-plus",
                "name": "CosyVoice v3.5 Plus",
                "description": "Official CosyVoice TTS (clone + design + instruct)",
            },
            {
                "id": "cosyvoice-v3.5-flash",
                "name": "CosyVoice v3.5 Flash",
                "description": "Official CosyVoice TTS flash (clone + design + instruct)",
            },
            {
                "id": "cosyvoice-v3-plus",
                "name": "CosyVoice v3 Plus",
                "description": "Official CosyVoice TTS (clone + design)",
            },
            {
                "id": "cosyvoice-v3-flash",
                "name": "CosyVoice v3 Flash",
                "description": "Official CosyVoice TTS flash (clone + design + instruct)",
            },
            {
                "id": "cosyvoice-v2",
                "name": "CosyVoice v2",
                "description": "Official CosyVoice TTS v2 (clone)",
            },
            {
                "id": "cosyvoice-v1",
                "name": "CosyVoice v1",
                "description": "Official CosyVoice TTS v1 (legacy)",
            },
        ],
        "tts",
    ),
    (
        [
            {
                "id": "paraformer-realtime-v2",
                "name": "Paraformer Realtime v2",
                "description": "Official realtime ASR (recommended)",
            },
            {
                "id": "paraformer-realtime-8k-v2",
                "name": "Paraformer Realtime 8k v2",
                "description": "Official 8kHz phone-scene ASR",
            },
            {
                "id": "paraformer-realtime-v1",
                "name": "Paraformer Realtime v1",
                "description": "Official realtime ASR v1",
            },
            {
                "id": "fun-asr-realtime",
                "name": "Fun-ASR Realtime",
                "description": "Official Fun-ASR realtime recognition",
            },
        ],
        "stt",
    ),
    (
        [
            {
                "id": "wan2.7-image-pro",
                "name": "Wan 2.7 Image Pro",
                "description": "Official Wanxiang 2.7 pro image (t2i/edit, up to 4K)",
            },
            {
                "id": "wan2.7-image",
                "name": "Wan 2.7 Image",
                "description": "Official Wanxiang 2.7 standard image",
            },
            {
                "id": "wan2.6-image",
                "name": "Wan 2.6 Image",
                "description": "Official Wanxiang 2.6 image generation/edit",
            },
            {
                "id": "wan2.6-t2i",
                "name": "Wan 2.6 T2I",
                "description": "Official Wanxiang 2.6 pure text-to-image",
            },
            {
                "id": "wan2.5-t2i-preview",
                "name": "Wan 2.5 T2I Preview",
                "description": "Official Wanxiang 2.5 text-to-image preview",
            },
            {
                "id": "wan2.2-t2i-flash",
                "name": "Wan 2.2 T2I Flash",
                "description": "Official Wanxiang 2.2 flash text-to-image",
            },
            {
                "id": "wan2.2-t2i-plus",
                "name": "Wan 2.2 T2I Plus",
                "description": "Official Wanxiang 2.2 plus text-to-image",
            },
            {
                "id": "wanx2.1-t2i-turbo",
                "name": "Wanx 2.1 T2I Turbo",
                "description": "Official Wanx 2.1 turbo text-to-image",
            },
            {
                "id": "wanx2.1-t2i-plus",
                "name": "Wanx 2.1 T2I Plus",
                "description": "Official Wanx 2.1 plus text-to-image",
            },
            {
                "id": "wanx-v1",
                "name": "Wanx v1",
                "description": "Official Wanx v1 text-to-image (legacy)",
            },
        ],
        "image",
    ),
    (
        [
            {
                "id": "text-embedding-v4",
                "name": "Text Embedding v4",
                "description": "Official text embedding v4",
            },
            {
                "id": "text-embedding-v3",
                "name": "Text Embedding v3",
                "description": "Official text embedding v3",
            },
            {
                "id": "text-embedding-v2",
                "name": "Text Embedding v2",
                "description": "Official text embedding v2",
            },
        ],
        "embedding",
    ),
    (
        [
            {
                "id": "qwen3-rerank",
                "name": "Qwen3 Rerank",
                "description": "Official Qwen3 text rerank",
            },
            {
                "id": "gte-rerank-v2",
                "name": "GTE Rerank v2",
                "description": "Official GTE text rerank v2",
            },
        ],
        "rerank",
    ),
]


def _merge_native_catalog(remote_models: list[dict]) -> list[dict]:
    """Merge known DashScope-native models missing from OpenAI-compatible /models.

    - Remote entries always win for the same id (never override remote)
    - Catalog is only used after a successful remote fetch
    - Does not invent LLM ids; only multimodal native IDs that /models omits
    """
    by_id: dict[str, dict] = {}
    for item in remote_models:
        mid = item.get("id")
        if isinstance(mid, str) and mid:
            by_id[mid] = item

    for catalog, forced_type in _DASH_SCOPE_NATIVE_CATALOG:
        for item in catalog:
            mid = item["id"]
            if mid not in by_id:
                by_id[mid] = _annotate(dict(item), forced_type=forced_type)

    return list(by_id.values())


class BailianProvider(BaseProvider):
    """
    Alibaba Cloud Bailian (DashScope) full provider.

    - LLM / Embedding: OpenAI-compatible API
    - TTS: CosyVoice (DashScope SDK)
    - STT: Paraformer / Fun-ASR realtime recognition (local files)
    - Image: Wanxiang async image generation / editing
    - Rerank: text ranking

    Listing policy:
    1. Always fetch OpenAI-compatible GET /models (required; failure raises)
    2. Merge official DashScope-native multimodal models that /models never
       returns (CosyVoice, Paraformer, Wanxiang, embeddings, rerank)
    3. Never use a static list when remote fetch fails
    """

    models = {
        ModelType.LLM: BailianLLMClient,
        ModelType.TTS: BailianCosyVoiceTTSClient,
        ModelType.STT: BailianSTTClient,
        ModelType.IMAGE: BailianImageClient,
        ModelType.EMBEDDING: BailianEmbeddingClient,
        ModelType.RERANK: BailianRerankClient,
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def get_llm_list(self) -> list[dict]:
        """
        Fetch available models from Bailian OpenAI-compatible API (GET /models),
        then merge known DashScope-native multimodal models missing from that API.

        Failure / empty key / HTTP error still raises (same as other providers).
        """
        base_url = resolve_compatible_base_url(self.provider_config).rstrip("/")
        api_key = (self.provider_config.get("api_key") or "").strip()
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models: list[dict] = []
        # Accept common response shapes, but only keep ids that the API actually returned.
        raw_list = []
        if isinstance(data, dict):
            raw_list = data.get("data") or data.get("models") or []
        elif isinstance(data, list):
            raw_list = data

        for item in raw_list:
            if not isinstance(item, dict):
                if isinstance(item, str) and item.strip():
                    models.append(
                        _annotate(
                            {
                                "id": item.strip(),
                                "name": item.strip(),
                                "description": "",
                            }
                        )
                    )
                continue
            model_id = item.get("id") or item.get("model") or item.get("model_id") or ""
            # Require a non-empty string id (strip whitespace); skip invalid types
            # so _infer_type never sees non-str / blank ids.
            if not isinstance(model_id, str) or not model_id.strip():
                continue
            model_id = model_id.strip()
            # Display metadata must be strings — list/dict description would
            # crash _tag().strip() and abort the whole remote listing.
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                name = model_id
            else:
                name = name.strip()
            description = item.get("description")
            if not isinstance(description, str):
                description = item.get("owned_by")
            if not isinstance(description, str):
                description = ""
            models.append(
                _annotate(
                    {
                        "id": model_id,
                        "name": name,
                        "description": description,
                    }
                )
            )

        # Remote succeeded: fill multimodal IDs that OpenAI-compatible /models omits.
        return _merge_native_catalog(models)
