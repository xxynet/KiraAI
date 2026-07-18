import httpx

from core.provider import ModelType, BaseProvider
from core.logging_manager import get_logger

from .model_clients import (
    BailianLLMClient,
    BailianCosyVoiceTTSClient,
    BailianSTTClient,
    BailianImageClient,
    BailianEmbeddingClient,
    BailianRerankClient,
    resolve_compatible_base_url,
)

logger = get_logger("provider", "purple")


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
    Used only for display tags; never blocks listing unknown remote models.
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
        or mid.endswith("-vace")
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


# CosyVoice 全系列（远端 /models 通常不含语音模型，静态补充）
COSYVOICE_MODELS = [
    {
        "id": "cosyvoice-v3.5-plus",
        "name": "CosyVoice v3.5 Plus",
        "description": "超高表现力，声音复刻与声音设计效果升级，推荐",
    },
    {
        "id": "cosyvoice-v3.5-flash",
        "name": "CosyVoice v3.5 Flash",
        "description": "v3.5 轻量版，低延迟，支持复刻音色",
    },
    {
        "id": "cosyvoice-v3-plus",
        "name": "CosyVoice v3 Plus",
        "description": "合成效果佳，支持声音复刻与指令控制",
    },
    {
        "id": "cosyvoice-v3-flash",
        "name": "CosyVoice v3 Flash",
        "description": "常用 Flash 版本，低延迟，支持复刻音色",
    },
    {
        "id": "cosyvoice-v2",
        "name": "CosyVoice v2",
        "description": "v2 大模型，多音色与多语言支持",
    },
    {
        "id": "cosyvoice-v1",
        "name": "CosyVoice v1",
        "description": "旧版 v1，功能有限，不推荐新项目使用",
    },
]

# 语音识别常用模型（远端列表通常不含）
STT_MODELS = [
    {
        "id": "paraformer-realtime-v2",
        "name": "Paraformer Realtime v2",
        "description": "实时/本地文件语音识别，推荐",
    },
    {
        "id": "paraformer-realtime-8k-v2",
        "name": "Paraformer Realtime 8k v2",
        "description": "8kHz 电话场景语音识别",
    },
    {
        "id": "paraformer-realtime-v1",
        "name": "Paraformer Realtime v1",
        "description": "实时识别 v1",
    },
    {
        "id": "fun-asr-realtime",
        "name": "Fun-ASR Realtime",
        "description": "Fun-ASR 实时语音识别",
    },
]

# 文生图常用模型
IMAGE_MODELS = [
    {
        "id": "wan2.7-image-pro",
        "name": "Wan 2.7 Image Pro",
        "description": "万相 2.7 专业版（文生图/编辑，最高 4K）",
    },
    {
        "id": "wan2.7-image",
        "name": "Wan 2.7 Image",
        "description": "万相 2.7 标准版（更快）",
    },
    {
        "id": "wan2.6-image",
        "name": "Wan 2.6 Image",
        "description": "万相 2.6 图像生成与编辑（支持参考图/图生图）",
    },
    {
        "id": "wan2.6-t2i",
        "name": "Wan 2.6 T2I",
        "description": "万相 2.6 纯文生图（不支持参考图；selfie 请用 wan2.6-image，或开启 auto_route）",
    },
    {
        "id": "wan2.5-t2i-preview",
        "name": "Wan 2.5 T2I Preview",
        "description": "万相 2.5 文生图 preview",
    },
    {
        "id": "wan2.2-t2i-flash",
        "name": "Wan 2.2 T2I Flash",
        "description": "万相 2.2 极速版",
    },
    {
        "id": "wan2.2-t2i-plus",
        "name": "Wan 2.2 T2I Plus",
        "description": "万相 2.2 专业版",
    },
    {
        "id": "wanx2.1-t2i-turbo",
        "name": "Wanx 2.1 T2I Turbo",
        "description": "万相 2.1 极速版",
    },
    {
        "id": "wanx2.1-t2i-plus",
        "name": "Wanx 2.1 T2I Plus",
        "description": "万相 2.1 专业版",
    },
    {
        "id": "wanx-v1",
        "name": "Wanx v1",
        "description": "万相 v1 文生图（旧版）",
    },
]

# Embedding / Rerank 常用模型（远端可能已包含，静态作兜底）
EMBEDDING_MODELS = [
    {
        "id": "text-embedding-v4",
        "name": "Text Embedding v4",
        "description": "通用文本向量 v4（推荐）",
    },
    {
        "id": "text-embedding-v3",
        "name": "Text Embedding v3",
        "description": "通用文本向量 v3",
    },
    {
        "id": "text-embedding-v2",
        "name": "Text Embedding v2",
        "description": "通用文本向量 v2",
    },
]

RERANK_MODELS = [
    {
        "id": "qwen3-rerank",
        "name": "Qwen3 Rerank",
        "description": "文本重排序（推荐）",
    },
    {
        "id": "gte-rerank-v2",
        "name": "GTE Rerank v2",
        "description": "GTE 文本重排序 v2",
    },
]


class BailianProvider(BaseProvider):
    """
    Alibaba Cloud Bailian (DashScope) full provider.

    - LLM / Embedding: OpenAI-compatible API
    - TTS: CosyVoice (DashScope SDK)
    - STT: Paraformer / Fun-ASR realtime recognition (local files)
    - Image: Wanxiang async image generation / editing
    - Rerank: text ranking
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
        优先从百炼 OpenAI 兼容 /models 远端拉取；
        失败时回退静态列表，并始终补充 TTS/STT/Image 等远端通常不返回的模型。

        容错策略（官网调整模型列表时不会“出错”）：
        1. 远端成功：原样收录所有 id（含新增未知模型），仅加类型备注
        2. 远端失败/空 Key：静态兜底，不抛异常给 WebUI
        3. 静态列表只做“缺失 id 补充”，绝不覆盖远端同名项
        4. 类型标签仅用于展示，不影响实际调用
        """
        remote: list[dict] = []
        try:
            remote = await self._fetch_remote_models()
        except Exception as e:
            logger.warning(f"Bailian remote model list failed, using static fallback: {e}")

        # 合并：远端优先，静态补充缺失 id
        by_id: dict[str, dict] = {}
        for item in remote:
            mid = item.get("id")
            if not mid:
                continue
            # 远端模型：推断类型并打标签；未知 id 默认 [LLM]，仍完整保留
            by_id[mid] = _annotate(item)

        static_groups = (
            (COSYVOICE_MODELS, "tts"),
            (STT_MODELS, "stt"),
            (IMAGE_MODELS, "image"),
            (EMBEDDING_MODELS, "embedding"),
            (RERANK_MODELS, "rerank"),
        )
        for static_list, mtype in static_groups:
            for item in static_list:
                mid = item["id"]
                if mid not in by_id:
                    by_id[mid] = _annotate(item, forced_type=mtype)

        # 若远端完全失败，至少给一些常用 LLM 兜底
        if not remote:
            for item in self._static_llm_fallback():
                mid = item["id"]
                if mid not in by_id:
                    by_id[mid] = _annotate(item, forced_type="llm")

        return list(by_id.values())

    async def _fetch_remote_models(self) -> list[dict]:
        base_url = resolve_compatible_base_url(self.provider_config).rstrip("/")
        api_key = (self.provider_config.get("api_key") or "").strip()
        if not api_key:
            raise ValueError("api_key is empty")

        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = []
        # 兼容多种返回形态，避免官网字段微调导致整表失败
        raw_list = []
        if isinstance(data, dict):
            raw_list = data.get("data") or data.get("models") or []
        elif isinstance(data, list):
            raw_list = data

        for item in raw_list:
            if not isinstance(item, dict):
                # 偶发纯字符串 id
                if isinstance(item, str) and item.strip():
                    models.append({"id": item.strip(), "name": item.strip(), "description": ""})
                continue
            model_id = item.get("id") or item.get("model") or item.get("model_id") or ""
            if not model_id:
                continue
            models.append({
                "id": model_id,
                "name": item.get("name") or model_id,
                "description": item.get("description") or item.get("owned_by") or "",
            })
        return models

    @staticmethod
    def _static_llm_fallback() -> list[dict]:
        return [
            {"id": "qwen-plus", "name": "Qwen Plus", "description": "通义千问 Plus"},
            {"id": "qwen-turbo", "name": "Qwen Turbo", "description": "通义千问 Turbo"},
            {"id": "qwen-max", "name": "Qwen Max", "description": "通义千问 Max"},
            {"id": "qwen-long", "name": "Qwen Long", "description": "通义千问 Long"},
            {"id": "qwen-vl-plus", "name": "Qwen VL Plus", "description": "通义千问视觉 Plus"},
            {"id": "qwen-vl-max", "name": "Qwen VL Max", "description": "通义千问视觉 Max"},
            {"id": "deepseek-v3", "name": "DeepSeek V3", "description": "DeepSeek V3（百炼）"},
            {"id": "deepseek-r1", "name": "DeepSeek R1", "description": "DeepSeek R1（百炼）"},
        ]
