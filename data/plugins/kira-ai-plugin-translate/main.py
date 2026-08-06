"""
KiraAI 翻译插件 (kira-ai-plugin-translate)
多后端文本翻译：自动语言检测、后端自动回退、按用户额度控制
"""
import asyncio
import hashlib
import logging
import random
import time
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Optional

import aiohttp

from core.plugin import BasePlugin, PluginContext, register
from core.chat import KiraMessageBatchEvent

logger = logging.getLogger(__name__)

# ── 语言代码归一化（统一 ISO 639-1 小写，兼容各别名） ──────────
_LANG_ALIASES = {
    "zh": "zh", "zh-cn": "zh", "zh_cn": "zh", "cn": "zh", "chs": "zh",
    "zh-hans": "zh", "zh-tw": "zh", "zh-hant": "zh", "cht": "zh", "中文": "zh",
    "en": "en", "english": "en", "英语": "en",
    "ja": "ja", "jp": "ja", "japanese": "ja", "日语": "ja",
    "ko": "ko", "kor": "ko", "korean": "ko", "韩语": "ko",
    "fr": "fr", "fra": "fr", "法语": "fr",
    "de": "de", "ger": "de", "德语": "de",
    "es": "es", "spa": "es", "西班牙语": "es",
    "ru": "ru", "rus": "ru", "俄语": "ru",
    "pt": "pt", "葡萄牙语": "pt", "it": "it", "意大利语": "it",
    "nl": "nl", "荷兰语": "nl", "ar": "ar", "ara": "ar", "阿拉伯语": "ar",
    "hi": "hi", "印地语": "hi", "th": "th", "泰语": "th",
    "vi": "vi", "vie": "vi", "越南语": "vi", "id": "id", "印尼语": "id",
}
_SUPPORTED = {"auto", "zh", "en", "ja", "ko", "fr", "de", "es", "ru",
              "pt", "it", "nl", "ar", "hi", "th", "vi", "id"}

# canonical -> 各家后端语言代码
_VENDOR_LANG = {
    "baidu":  {"zh": "zh", "en": "en", "ja": "jp", "ko": "kor", "fr": "fra",
               "de": "de", "es": "spa", "ru": "ru", "pt": "pt", "it": "it",
               "nl": "nl", "ar": "ara", "hi": "hi", "th": "th", "vi": "vie"},
    "deepl":  {"zh": "ZH", "en": "EN", "ja": "JA", "ko": "KO", "fr": "FR",
               "de": "DE", "es": "ES", "ru": "RU", "pt": "PT", "it": "IT",
               "nl": "NL", "ar": "AR"},
    "google": {"zh": "zh-CN", "en": "en", "ja": "ja", "ko": "ko", "fr": "fr",
               "de": "de", "es": "es", "ru": "ru", "pt": "pt", "it": "it",
               "nl": "nl", "ar": "ar", "hi": "hi", "th": "th", "vi": "vi", "id": "id"},
    "aliyun": {"zh": "zh", "en": "en", "ja": "ja", "ko": "ko", "fr": "fr",
               "de": "de", "es": "es", "ru": "ru", "pt": "pt", "it": "it",
               "nl": "nl", "ar": "ar", "hi": "hi", "th": "th", "vi": "vi", "id": "id"},
}
_FALLBACK_CHAIN = ["baidu", "aliyun", "deepl", "local"]


def _norm_lang(code: str) -> str:
    """把用户/LLM 传入的语言代码规范化为 ISO 639-1 小写；非法则抛 ValueError"""
    if not code:
        return "auto"
    key = code.strip().lower().replace("_", "-")
    key = _LANG_ALIASES.get(key, key)
    if key not in _SUPPORTED:
        raise ValueError(f"不支持的语言代码: {code}")
    return key


def _to_vendor(backend: str, lang: str, vendor_map: dict) -> str:
    if lang == "auto":
        return "auto"
    return vendor_map.get(lang, lang)


class TranslatePlugin(BasePlugin):
    """KiraAI 翻译插件"""

    def __init__(self, ctx: PluginContext, cfg: dict):
        super().__init__(ctx, cfg)
        self._http: Optional[aiohttp.ClientSession] = None
        self._cache: "OrderedDict[str, str]" = OrderedDict()
        self._cache_max = 1024
        self._quota: dict = {}          # session_id -> {"date": str, "chars": int}
        self._window: dict = {}         # session_id -> {"ts": float, "n": int}
        self._lock = asyncio.Lock()
        self._data_dir: Optional[Path] = None

    # ── 生命周期 ──────────────────────────────────────────
    async def initialize(self):
        self._data_dir = self.ctx.get_plugin_data_dir()
        self._http = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={"User-Agent": "KiraAI-Translate/1.0"},
        )
        available = [b for b in _FALLBACK_CHAIN if self._backend_ready(b)]
        if not available:
            logger.warning("翻译插件：未配置任何后端，插件已加载但 translate 不可用（可只配本地模型实现零成本离线翻译）")
        else:
            logger.info(f"翻译插件已初始化，可用后端: {', '.join(available)}")

    async def terminate(self):
        if self._http:
            await self._http.close()
            self._http = None
        logger.info("翻译插件已卸载")

    # ── 配置 ──────────────────────────────────────────────
    def _get_config(self) -> dict:
        return {
            "default_backend": self.plugin_cfg.get("default_backend", "auto"),
            "baidu_appid": self.plugin_cfg.get("baidu_appid", ""),
            "baidu_secret_key": self.plugin_cfg.get("baidu_secret_key", ""),
            "deepl_api_key": self.plugin_cfg.get("deepl_api_key", ""),
            "deepl_pro": bool(self.plugin_cfg.get("deepl_pro", False)),
            "google_api_key": self.plugin_cfg.get("google_api_key", ""),
            "aliyun_ak": self.plugin_cfg.get("aliyun_access_key_id", ""),
            "aliyun_sk": self.plugin_cfg.get("aliyun_access_key_secret", ""),
            "aliyun_region": self.plugin_cfg.get("aliyun_region", "cn-hangzhou"),
            "local_url": self.plugin_cfg.get("local_backend_url", "http://127.0.0.1:11434"),
            "local_model": self.plugin_cfg.get("local_model", "qwen2.5:7b"),
            "local_timeout": int(self.plugin_cfg.get("local_timeout", 120)),
            "max_chars_per_call": int(self.plugin_cfg.get("max_chars_per_call", 5000)),
            "max_chars_per_day": int(self.plugin_cfg.get("max_chars_per_day", 10000)),
            "max_qpm": int(self.plugin_cfg.get("max_queries_per_min", 30)),
            "enable_cache": bool(self.plugin_cfg.get("enable_cache", True)),
        }

    def _backend_ready(self, backend: str, model: Optional[str] = None) -> bool:
        cfg = self._get_config()
        if backend == "baidu":
            return bool(cfg["baidu_appid"] and cfg["baidu_secret_key"])
        if backend == "deepl":
            return bool(cfg["deepl_api_key"])
        if backend == "google":
            return bool(cfg["google_api_key"])
        if backend == "aliyun":
            return bool(cfg["aliyun_ak"] and cfg["aliyun_sk"])
        if backend == "local":
            # 传入的 model 可覆盖（甚至补全）插件配置里的 local_model
            return bool(cfg["local_url"] and (model or cfg["local_model"]))
        return False

    # ── 工具：翻译 ────────────────────────────────────────
    @register.tool(
        name="translate",
        description=(
            "将文本翻译成目标语言。自动检测源语言；支持多后端（百度/DeepL/Google/阿里云/本地模型），"
            "默认按配置自动回退。适用于对话翻译、长文翻译、术语查译。"
        ),
        params={
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "需要翻译的文本"},
                "target_lang": {
                    "type": "string",
                    "description": "目标语言代码：zh(中文) en(英语) ja(日语) ko(韩语) fr(法语) "
                                   "de(德语) es(西语) ru(俄语) pt(葡语) it(意语) nl(荷语) "
                                   "ar(阿语) hi(印地语) th(泰语) vi(越语) id(印尼语)",
                },
                "source_lang": {"type": "string", "description": "源语言代码，auto=自动检测（默认 auto）"},
                "backend": {"type": "string", "description": "指定后端：auto(默认，按配置回退)/baidu/deepl/google/aliyun/local"},
                "model": {"type": "string", "description": "（可选）仅当 backend=local 时生效，覆盖本地模型名称，如 qwen2.5:7b"},
            },
            "required": ["text", "target_lang"],
        },
    )
    async def translate(
        self,
        event: KiraMessageBatchEvent,
        *_,
        text: str,
        target_lang: str,
        source_lang: str = "auto",
        backend: str = "auto",
        model: Optional[str] = None,
    ) -> str:
        """翻译文本（含额度/限流/缓存/后端回退）"""
        cfg = self._get_config()
        if not text or not text.strip():
            return "❌ 翻译失败：文本为空。"

        # 参数校验与归一化
        try:
            tgt = _norm_lang(target_lang)
            src = _norm_lang(source_lang)
        except ValueError as e:
            return f"❌ {e}"
        if tgt == "auto":
            return "❌ 翻译失败：目标语言不能为 auto。"
        if len(text) > cfg["max_chars_per_call"]:
            return f"❌ 翻译失败：文本超过单次上限 {cfg['max_chars_per_call']} 字符（当前 {len(text)}）。"

        sid = event.session.session_id if event and event.session else "unknown"

        # 缓存命中（不消耗额度）
        cache_key = f"{backend}|{model or ''}|{src}|{tgt}|{text}"
        if cfg["enable_cache"] and cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return f"✅ {self._cache[cache_key]}\n（缓存命中，未消耗额度）"

        # 额度与限流
        ok, err = await self._check_quota(sid, len(text), cfg)
        if not ok:
            return f"❌ {err}"

        # 选择后端执行顺序
        chain = _FALLBACK_CHAIN if backend in ("", "auto") else [backend]
        errors = []
        for b in chain:
            if not self._backend_ready(b, model if b == "local" else None):
                errors.append(f"{b}未配置")
                continue
            try:
                result = await self._translate_with(b, text, src, tgt, cfg, model)
            except Exception as e:
                logger.error(f"翻译后端 {b} 失败: {e}")
                errors.append(f"{b}: {e}")
                continue
            if result is None:
                errors.append(f"{b}: 无返回结果")
                continue
            # 成功：记录额度、写缓存
            await self._add_quota(sid, len(text), cfg)
            if cfg["enable_cache"]:
                self._cache[cache_key] = result
                self._cache.move_to_end(cache_key)
                while len(self._cache) > self._cache_max:
                    self._cache.popitem(last=False)
            return f"✅ {result}\n（后端: {b}）"

        return "❌ 翻译失败：" + "；".join(errors)

    # ── 后端适配器 ────────────────────────────────────────
    async def _translate_with(self, backend: str, text: str, src: str, tgt: str, cfg: dict,
                              model: Optional[str] = None) -> Optional[str]:
        """调用单后端，成功返回翻译结果字符串，失败抛异常或返回 None"""
        if backend == "baidu":
            return await self._baidu(text, src, tgt, cfg)
        if backend == "deepl":
            return await self._deepl(text, src, tgt, cfg)
        if backend == "google":
            return await self._google(text, src, tgt, cfg)
        if backend == "aliyun":
            return await self._aliyun(text, src, tgt, cfg)
        if backend == "local":
            return await self._local(text, src, tgt, cfg, model)
        raise ValueError(f"未知后端: {backend}")

    async def _baidu(self, text, src, tgt, cfg) -> str:
        """百度翻译：POST https://fanyi-api.baidu.com/api/trans/vip/translate"""
        appid, secret = cfg["baidu_appid"], cfg["baidu_secret_key"]
        salt = str(random.randint(32768, 65536))
        sign = hashlib.md5(f"{appid}{text}{salt}{secret}".encode()).hexdigest()
        data = {
            "q": text, "from": _to_vendor("baidu", src, _VENDOR_LANG["baidu"]),
            "to": _to_vendor("baidu", tgt, _VENDOR_LANG["baidu"]),
            "appid": appid, "salt": salt, "sign": sign,
        }
        async with self._http.post("https://fanyi-api.baidu.com/api/trans/vip/translate",
                                   data=data) as resp:
            body = await resp.json()
        if "error_code" in body:
            raise RuntimeError(f"百度翻译错误 {body['error_code']}: {body.get('error_msg')}")
        parts = [item.get("dst", "") for item in body.get("trans_result", [])]
        detected = body.get("from", src)
        return f"[{detected}→{tgt}] " + "\n".join(parts)

    async def _deepl(self, text, src, tgt, cfg) -> str:
        """DeepL：api-free.deepl.com 或 api.deepl.com"""
        host = "api.deepl.com" if cfg["deepl_pro"] else "api-free.deepl.com"
        params = {
            "text": text, "target_lang": _to_vendor("deepl", tgt, _VENDOR_LANG["deepl"]),
            "source_lang": _to_vendor("deepl", src, _VENDOR_LANG["deepl"]),
        }
        headers = {"Authorization": f"DeepL-Auth-Key {cfg['deepl_api_key']}"}
        async with self._http.post(f"https://{host}/v2/translate",
                                   params=params, headers=headers) as resp:
            body = await resp.json()
        if "message" in body:
            raise RuntimeError(f"DeepL 错误: {body['message']}")
        detected = body["translations"][0].get("detected_source_language", src)
        return f"[{detected}→{tgt}] " + body["translations"][0]["text"]

    async def _google(self, text, src, tgt, cfg) -> str:
        """Google Cloud Translation v2（需要境外网络）"""
        params = {
            "q": text, "target": _to_vendor("google", tgt, _VENDOR_LANG["google"]),
            "key": cfg["google_api_key"], "format": "text",
        }
        if src != "auto":
            params["source"] = _to_vendor("google", src, _VENDOR_LANG["google"])
        async with self._http.post("https://translation.googleapis.com/language/translate/v2",
                                   params=params) as resp:
            body = await resp.json()
        if "error" in body:
            raise RuntimeError(f"Google 错误: {body['error'].get('message')}")
        data = body["data"]["translations"][0]
        detected = data.get("detectedSourceLanguage", src)
        return f"[{detected}→{tgt}] " + data["translatedText"]

    async def _aliyun(self, text, src, tgt, cfg) -> str:
        """阿里云机器翻译（通用版，使用官方 SDK，延迟 import 降低依赖成本）"""
        from aliyun_python_sdk_core.auth.credentials import AccessKeyCredential
        from aliyun_python_sdk_core.client import AcsClient
        import aliyun_python_sdk_alimt.request.v20181012 as alimt_api

        cred = AccessKeyCredential(cfg["aliyun_ak"], cfg["aliyun_sk"])
        client = AcsClient(region_id=cfg["aliyun_region"], credential=cred)
        req = alimt_api.TranslateGeneralRequest.TranslateGeneralRequest()
        req.set_FormatType("text")
        req.set_SourceLanguage(_to_vendor("aliyun", src, _VENDOR_LANG["aliyun"]))
        req.set_TargetLanguage(_to_vendor("aliyun", tgt, _VENDOR_LANG["aliyun"]))
        req.set_SourceText(text)
        req.set_Scene("general")
        body = await asyncio.to_thread(client.do_action_with_exception, req)
        import json as _json
        result = _json.loads(body)
        if result.get("Code") != "200":
            raise RuntimeError(f"阿里云错误: {result.get('Message')}")
        return f"[{src}→{tgt}] " + result["Data"]["Translated"]

    async def _local(self, text, src, tgt, cfg, model: Optional[str] = None) -> str:
        """本地模型（Ollama / OpenAI 兼容），隐私兜底后端；model 可覆盖插件配置的 local_model"""
        local_model = model or cfg["local_model"]
        prompt = f"Translate the following text from {src or 'auto'} to {tgt}. " \
                 f"Reply with ONLY the translation, no explanation.\n\n{text}"
        payload = {"model": local_model, "prompt": prompt, "stream": False}
        url = cfg["local_url"].rstrip("/") + "/api/generate"
        timeout = aiohttp.ClientTimeout(total=cfg["local_timeout"])
        async with self._http.post(url, json=payload, timeout=timeout) as resp:
            body = await resp.json()
        if "error" in body:
            raise RuntimeError(f"本地模型错误: {body['error']}")
        return f"[{src}→{tgt}] " + body.get("response", "").strip()

    # ── 额度与限流 ────────────────────────────────────────
    async def _check_quota(self, sid: str, chars: int, cfg: dict) -> tuple:
        """返回 (是否允许, 错误信息)"""
        async with self._lock:
            today = date.today().isoformat()
            q = self._quota.setdefault(sid, {"date": today, "chars": 0})
            if q["date"] != today:
                q.update(date=today, chars=0)
            if q["chars"] + chars > cfg["max_chars_per_day"]:
                return False, f"今日翻译额度已用完（{cfg['max_chars_per_day']} 字符/日），请明日再试或提高配置。"
            w = self._window.setdefault(sid, {"ts": time.time(), "n": 0})
            if time.time() - w["ts"] > 60:
                w.update(ts=time.time(), n=0)
            if w["n"] >= cfg["max_qpm"]:
                return False, "请求过于频繁，请稍后再试。"
            return True, ""

    async def _add_quota(self, sid: str, chars: int, cfg: dict):
        async with self._lock:
            today = date.today().isoformat()
            q = self._quota.setdefault(sid, {"date": today, "chars": 0})
            if q["date"] != today:
                q.update(date=today, chars=0)
            q["chars"] += chars
            w = self._window.setdefault(sid, {"ts": time.time(), "n": 0})
            if time.time() - w["ts"] > 60:
                w.update(ts=time.time(), n=0)
            w["n"] += 1


# ── 插件入口 ──────────────────────────────────────────────
plugin_class = TranslatePlugin
