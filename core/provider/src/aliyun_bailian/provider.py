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
    Best-effort type inference from remote model id.
    Used only for display tags on truly returned models.
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


def _annotate(item: dict) -> dict:
    """Return a shallow-copied remote model dict with type-tagged description."""
    out = dict(item)
    mid = out.get("id") or ""
    mtype = _infer_type(mid)
    out["description"] = _tag(mtype, out.get("description") or "")
    # Keep raw type for potential future UI use (harmless extra field)
    out.setdefault("type", mtype)
    return out


class BailianProvider(BaseProvider):
    """
    Alibaba Cloud Bailian (DashScope) full provider.

    - LLM / Embedding: OpenAI-compatible API
    - TTS: CosyVoice (DashScope SDK)
    - STT: Paraformer / Fun-ASR realtime recognition (local files)
    - Image: Wanxiang async image generation / editing
    - Rerank: text ranking

    Model listing is always remote-only (GET /models), same as other providers.
    On failure the error is propagated; no static fallback list is injected.
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
        Fetch available models from Bailian OpenAI-compatible API (GET /models).

        Same behavior as OpenAI / SiliconFlow / ModelScope / DeepSeek / Volcengine:
        - success: return remote models only (optionally type-tagged for display)
        - failure / empty key / HTTP error: raise and let ProviderManager report it
        - never inject static/fallback model ids
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
        return models
