import asyncio
import json
import re
from typing import Literal, Optional

from tavily import TavilyClient

from core.plugin import BasePlugin, logger, register
from core.utils.path_utils import get_config_path

from .anysearch import AnySearchClient
from .utils import (
    format_anysearch_domains,
    format_anysearch_extract,
    format_anysearch_search,
    format_hybrid_results,
)


class SearchPlugin(BasePlugin):
    """
    联网搜索插件：Tavily / AnySearch 双引擎
    - hybrid（推荐，默认）：双源并发调用，RRF + score 归一化加权融合去重；任一源不可用自动降级单源
    - tavily / anysearch：强制指定单源
    AnySearch 额外提供并行批量搜索与垂直领域目录查询（hybrid/anysearch 模式下可用）
    """

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self._tavily_key = None
        self._provider = "hybrid"
        self._any_client = None
        self._max_results = 5
        self._hybrid_weight = 0.4
        self.tavily_available = True
        self.anysearch_available = True

    async def initialize(self):
        """加载配置：Tavily Key / 搜索模式 / AnySearch 参数（section 优先，扁平兜底兼容旧配置）"""
        if self._migrate_legacy_tavily_key():
            self._persist_config()
        src = self.plugin_cfg.get("section_source", {}) or {}
        common = self.plugin_cfg.get("section_common", {}) or {}

        # Tavily Key：section -> 扁平兜底
        self._tavily_key = src.get("tavily_key") or self.plugin_cfg.get("tavily_key")
        # 搜索模式
        self._provider = str(src.get("search_provider") or self.plugin_cfg.get("search_provider", "hybrid") or "hybrid").strip().lower()
        if self._provider == "auto":
            # auto 已并入 hybrid（任一源可用即自动兜底），保留旧配置兼容
            self._provider = "hybrid"
        if self._provider not in ("tavily", "anysearch", "hybrid"):
            self._provider = "hybrid"
        # AnySearch
        anysearch_key = str(src.get("anysearch_key") or self.plugin_cfg.get("anysearch_key", "") or "").strip()
        base = str(src.get("anysearch_base_url") or self.plugin_cfg.get("anysearch_base_url", "") or "").strip().rstrip("/")
        anysearch_base = base or "https://api.anysearch.com"
        try:
            mr = common.get("max_results")
            if mr is None:
                mr = self.plugin_cfg.get("max_results", 5)
            self._max_results = max(1, min(int(mr), 10))
        except Exception:
            self._max_results = 5
        # AnySearch 超时跟随框架全局工具调用超时（bot_config.agent.tool_call_timeout），
        # 不设独立配置项，与 1.0 版本行为对齐（由框架 wait_for 兜底）
        try:
            w = common.get("hybrid_score_weight")
            if w is None:
                w = self.plugin_cfg.get("hybrid_score_weight", 0.4)
            self._hybrid_weight = max(0.0, min(float(w), 1.0))
        except Exception:
            self._hybrid_weight = 0.4

        if not self._tavily_key:
            logger.warning("Tavily API key not found. Tavily source unavailable")
            self.tavily_available = False
        self._any_client = AnySearchClient(
            base_url=anysearch_base,
            api_key=anysearch_key,
            timeout=self._tool_timeout(),
            auto_key_path=self.ctx.get_plugin_data_dir() / "anysearch_auto_key.txt",
        )
        await self._any_client.initialize()

        logger.info("Initializing Search Plugin mode=%s tavily=%s anysearch=%s hybrid_weight=%s",
                    self._provider, self.tavily_available, self._any_client.has_credentials, self._hybrid_weight)

    def _tool_timeout(self) -> float:
        """跟随框架全局工具调用超时（bot_config.agent.tool_call_timeout，默认 60s）"""
        try:
            t = self.ctx.config.get_config("bot_config.agent.tool_call_timeout", 60.0)
            t = float(t)
            return t if t > 0 else 60.0
        except Exception:
            return 60.0

    def _migrate_legacy_tavily_key(self) -> bool:
        """Move a legacy top-level ``tavily_key`` into ``section_source``.

        Pre-section configs stored the Tavily key at the top level. If a top-level
        key exists and the section slot is empty, move it in; otherwise drop the
        stale top-level key. Idempotent, safe on every startup.
        """
        if "tavily_key" not in self.plugin_cfg:
            return False
        flat_val = self.plugin_cfg.get("tavily_key")
        section = self.plugin_cfg.get("section_source")
        if not isinstance(section, dict):
            return False
        if flat_val and not section.get("tavily_key"):
            section["tavily_key"] = flat_val
        del self.plugin_cfg["tavily_key"]
        return True

    def _persist_config(self):
        """Write the in-memory plugin config back to the config file.

        ``self.plugin_cfg`` is the same dict the registry keeps in memory, so
        WebUI reads the migrated state without a reload.
        """
        try:
            config_path = get_config_path() / "plugins" / "search.json"
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(self.plugin_cfg, f, indent=4, ensure_ascii=False)
            logger.info("Migrated legacy top-level tavily_key into section_source for search plugin")
        except Exception as e:
            logger.error(f"Failed to persist migrated search plugin config: {e}")

    async def terminate(self):
        if self._any_client:
            await self._any_client.close()

    @staticmethod
    def _parse_params(raw: Optional[str]) -> Optional[dict]:
        if not raw:
            return None
        raw = raw.strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        result = {}
        for kv in raw.split(","):
            if "=" in kv:
                k, _, v = kv.partition("=")
                k = k.strip().strip("'\"")
                v = v.strip().strip("'\"")
                if k:
                    result[k] = v
        return result or None

    # ---------- Tavily 内部逻辑 ----------

    async def _tavily_search(self, query: str, topic: str = "general", search_depth: str = "basic") -> dict:
        """返回 {"results": [...], "error": None}"""
        if not self.tavily_available:
            return {"results": [], "error": "Tavily 不可用（未配置 Key）"}
        try:
            client = TavilyClient(self._tavily_key)
            res = await asyncio.to_thread(
                client.search, query=query, topic=topic, search_depth=search_depth, max_results=self._max_results
            )
            return {"results": res.get("results") or [], "error": None}
        except Exception as e:
            logger.warning("Tavily search failed: %s", e)
            return {"results": [], "error": f"Tavily 搜索失败：{e}"}

    async def _any_search(self, query: str, sub_domain: str = None, params: str = None, topic: str = "general") -> dict:
        """返回 {"results": [...], "error": None}，results 项含 url/title/content/score/source"""
        if not self._any_client:
            return {"results": [], "error": "AnySearch 客户端未初始化"}
        return await self._any_client.search(
            query,
            max_results=self._max_results,
            sub_domain=sub_domain,
            params=self._parse_params(params),
            topic=topic,
        )

    # ---------- 混合融合 ----------

    _RRF_K = 60.0

    @staticmethod
    def _norm_url(url: str) -> str:
        """URL 规范化用于去重：去协议/scheme、www、query、fragment、末尾斜杠，转小写"""
        if not url:
            return ""
        u = url.strip()
        u = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", u)
        u = re.sub(r"^www\.", "", u, flags=re.I)
        u = u.split("#", 1)[0].split("?", 1)[0].rstrip("/")
        return u.lower()

    @staticmethod
    def _minmax_norm(scores: list) -> dict:
        """min-max 归一化 score 到 [0,1]，返回 {index: norm}"""
        if not scores:
            return {}
        lo, hi = min(scores), max(scores)
        if hi <= lo:
            # 无区分度（含全 0）时给中性分，避免无 score 的源被系统性拔高
            return {i: 0.5 for i in range(len(scores))}
        return {i: (s - lo) / (hi - lo) for i, s in enumerate(scores)}

    def _fuse_results(self, lists: list) -> list:
        """
        多源融合：RRF 排名分 + score 归一化加权，URL 规范化去重。
        lists: [{"name": "tavily", "results": [...]}, ...]
        返回融合排序后的结果列表（每项含 source/score/fusion_score）
        """
        merged = {}  # norm_url -> {item, fusion_score, sources:set}
        for lst in lists:
            results = lst.get("results") or []
            if not results:
                continue
            # score 归一化
            raw_scores = [(it.get("score") or 0.0) for it in results]
            norm_map = self._minmax_norm(raw_scores)
            # RRF 排名分归一化到 [0,1]，与 score 同量级，否则 RRF≈0.016 会被权重淹没
            rrf_scores = [1.0 / (self._RRF_K + r) for r in range(1, len(results) + 1)]
            rrf_norm_map = self._minmax_norm(rrf_scores)
            for rank, it in enumerate(results, 1):
                key = self._norm_url(it.get("url") or "")
                if not key:
                    key = f"__title_{(it.get('title') or '')[:80].lower()}"
                rrf = rrf_norm_map.get(rank - 1, 0.5)
                nscore = norm_map.get(rank - 1, 0.0)
                fusion = self._hybrid_weight * nscore + (1.0 - self._hybrid_weight) * rrf
                if key in merged:
                    merged[key]["fusion_score"] += fusion
                    merged[key]["sources"].add(lst.get("name") or lst.get("source") or "?")
                else:
                    merged[key] = {
                        "title": it.get("title") or "",
                        "url": it.get("url") or "",
                        "content": it.get("content") or it.get("snippet") or "",
                        "fusion_score": fusion,
                        "sources": {lst.get("name") or lst.get("source") or "?"},
                    }
        results = sorted(merged.values(), key=lambda x: x["fusion_score"], reverse=True)
        return results[: self._max_results]

    # ---------- 源选择 ----------

    def _resolve_mode(self) -> str:
        """返回实际执行模式：hybrid / tavily / anysearch
        hybrid 下任一源不可用自动降级为另一单源（Tavily 无 Key 时走 AnySearch），
        已完全覆盖原 auto 模式语义，故不再单设 auto；
        tavily / anysearch 为强制单源，不可用时报错而非回退"""
        if self._provider == "tavily":
            # 显式选择 tavily 即强制单源，不可用时由调用方返回错误，不回退 AnySearch
            return "tavily"
        if self._provider == "anysearch":
            return "anysearch"
        return "hybrid"

    # ---------- 工具：通用搜索 ----------

    @register.tool(
        "search",
        "A web search tool to search the web for relevant content. Supports dual engines: Tavily / AnySearch. Hybrid mode (default) merges both sources with RRF + score fusion. AnySearch supports vertical sub-domains (finance/code/legal/academic etc.) for structured queries.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query to execute."},
                "topic": {"type": "string", "enum": ["general", "news", "finance"], "description": "Optional. The category of the search. news is useful for retrieving real-time updates, general is for broader searches. Defaults to general"},
                "search_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "Optional. Controls the latency vs relevance tradeoff (Tavily only). Defaults to basic"},
                "sub_domain": {"type": "string", "description": "AnySearch vertical sub-domain, e.g. finance.quote / code.github / legal.cn_case. When set, the query is forced to AnySearch vertical engine; query available sub-domains via get_sub_domains first"},
                "params": {"type": "string", "description": "AnySearch structured params (JSON or key=value), e.g. {\"type\":\"stock\",\"symbol\":\"AAPL\"}. Only used when sub_domain is set"}
            },
            "required": ["query"]
        }
    )
    async def search(self, event, query: str,
                     topic: Literal["general", "news", "finance"] = "general",
                     search_depth: Literal["basic", "advanced"] = "basic",
                     sub_domain: str = None, params: str = None) -> str:
        # 垂直领域查询强制走 AnySearch（Tavily 不支持）
        if sub_domain or params:
            if not self._any_enabled():
                return "搜索失败：垂直领域查询（sub_domain/params）仅 AnySearch 引擎支持，当前为 tavily 单源模式"
            res = await self._any_search(query, sub_domain, params, topic)
            if res["error"]:
                return f"搜索失败：{res['error']}"
            return format_anysearch_search({"results": res["results"]})

        mode = self._resolve_mode()
        if mode == "hybrid":
            t_res, a_res = await asyncio.gather(
                self._tavily_search(query, topic, search_depth),
                self._any_search(query, None, None, topic),
            )
            fused = self._fuse_results([
                {"source": "tavily", "results": t_res["results"]},
                {"source": "anysearch", "results": a_res["results"]},
            ])
            if not fused:
                errs = [e for e in (t_res["error"], a_res["error"]) if e]
                if errs:
                    return "搜索失败：" + "；".join(errs)
            return format_hybrid_results(fused)

        if mode == "tavily":
            res = await self._tavily_search(query, topic, search_depth)
            if res["error"]:
                return f"搜索失败：{res['error']}"
            return "".join(json.dumps(ele, ensure_ascii=False) for ele in res["results"])

        # anysearch 单源
        res = await self._any_search(query, None, None, topic)
        if res["error"]:
            return f"搜索失败：{res['error']}"
        return format_anysearch_search({"results": res["results"]})

    # ---------- 工具：网页内容提取 ----------

    @register.tool(
        "extract_webpage",
        "Extract web page content from a specified URL. Uses Tavily Extract or AnySearch extract (auto by config).",
        {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to extract content from."},
                "query": {"type": "string", "description": "Optional. User intent for reranking extracted content chunks. When provided, chunks are reranked based on relevance to this query."},
                "extract_depth": {"type": "string", "enum": ["basic", "advanced"], "description": "Optional. Controls the latency vs relevance tradeoff."}
            },
            "required": ["url"]
        }
    )
    async def extract_webpage(self, event, url: str, query: str = None,
                              extract_depth: Literal["basic", "advanced"] = "basic") -> str:
        mode = self._resolve_mode()
        if mode == "tavily":
            # 强制单源：不可用或失败直接报错，不回退 AnySearch
            if not self.tavily_available:
                return "提取失败：Tavily 不可用（未配置 Key），当前为 tavily 单源模式"
            try:
                client = TavilyClient(self._tavily_key)
                res = await asyncio.to_thread(
                    client.extract, urls=url, query=query, extract_depth=extract_depth
                )
                results = res.get("results") or []
                if results:
                    return "".join(json.dumps(ele, ensure_ascii=False) for ele in results)
                return f"未能从 {url} 提取到正文（可能是不支持的格式或页面为空）"
            except Exception as e:
                logger.warning("Tavily extract failed: %r", e)
                return f"Tavily 提取失败：{e}"

        # hybrid 模式优先 Tavily，失败回落 AnySearch；anysearch 单源直接走 AnySearch
        if mode == "hybrid" and self.tavily_available:
            try:
                client = TavilyClient(self._tavily_key)
                res = await asyncio.to_thread(
                    client.extract, urls=url, query=query, extract_depth=extract_depth
                )
                results = res.get("results") or []
                if results:
                    return "".join(json.dumps(ele, ensure_ascii=False) for ele in results)
            except Exception as e:
                logger.warning("Tavily extract failed: %r", e)

        if not self._any_client:
            return "提取失败：AnySearch 客户端未初始化"
        body = await self._any_client.extract(url)
        if "error" in body:
            return f"提取失败：{body['error']}"
        data = body.get("data") or {}
        if not data.get("content"):
            return f"未能从 {url} 提取到正文（可能是不支持的格式或页面为空）"
        return format_anysearch_extract(data)

    # ---------- 工具：AnySearch 专属：并行批量搜索 ----------

    @register.tool(
        "anysearch_batch_search",
        "AnySearch parallel batch search: execute 1-5 independent queries at once and merge results. Available when AnySearch engine is enabled (hybrid/anysearch mode).",
        {
            "type": "object",
            "properties": {
                "queries": {"type": "string", "description": "JSON array string, e.g. [{\"query\":\"AAPL\"},{\"query\":\"量子计算\",\"max_results\":3}], max 5 items"},
                "sub_domain": {"type": "string", "description": "Shared vertical sub-domain applied to queries without their own (optional)"},
                "max_results": {"type": "integer", "description": "Shared max results 1-10 (optional)"}
            },
            "required": ["queries"]
        }
    )
    async def anysearch_batch_search(self, event, queries: str, sub_domain: str = None, max_results: int = None) -> str:
        if not self._any_enabled():
            return "batch_search 仅 AnySearch 引擎可用（当前为 tavily 单源模式），可切换 search_provider 或直接使用 search 工具"
        try:
            items = json.loads(queries)
            if not isinstance(items, list):
                items = [items]
        except Exception:
            return "batch_search 失败：queries 必须是合法 JSON 数组字符串"
        if not items or len(items) > 5:
            return "batch_search 失败：查询数量须为 1-5 条"
        normalized = []
        for it in items:
            if not isinstance(it, dict) or not str(it.get("query", "")).strip():
                return "batch_search 失败：每项必须是包含非空 query 的对象"
            q = {"query": str(it["query"])}
            tag = it.get("tag") or it.get("sub_domain") or sub_domain
            if tag:
                q["tag"] = tag
            p = self._parse_params(it.get("params"))
            if p:
                q["params"] = p
            mr = it.get("max_results") or it.get("max") or max_results
            if mr:
                try:
                    q["max_results"] = max(1, min(int(mr), 10))
                except (TypeError, ValueError):
                    return "batch_search 失败：max_results 必须是 1-10 的整数"
            normalized.append(q)

        async def one(item: dict) -> tuple:
            result = await self._any_client.search(
                item["query"],
                max_results=item.get("max_results"),
                sub_domain=item.get("tag"),
                params=item.get("params"),
            )
            return item["query"], result

        results = await asyncio.gather(*(one(it) for it in normalized))
        out = []
        for q, result in results:
            if result["error"]:
                out.append(json.dumps({"query": q, "error": result["error"]}, ensure_ascii=False))
            else:
                out.append(format_anysearch_search({"results": result["results"]}))
        return "\n".join(out)

    # ---------- 工具：AnySearch 专属：垂直领域目录 ----------

    @register.tool(
        "get_sub_domains",
        "Query AnySearch vertical domain catalog (finance/legal/code/academic/health/security etc.) to get available sub-domains and required params. Available when AnySearch engine is enabled (hybrid/anysearch mode).",
        {
            "type": "object",
            "properties": {
                "domains": {"type": "string", "description": "Domain names, comma separated, max 5. e.g. finance or finance,legal,code. Available: general/resource/social_media/finance/academic/legal/health/business/security/ip/code/energy/environment/agriculture/travel/film/gaming"}
            },
            "required": ["domains"]
        }
    )
    async def get_sub_domains(self, event, domains: str) -> str:
        if not self._any_enabled():
            return "get_sub_domains 仅 AnySearch 引擎可用（当前为 tavily 单源模式），可切换 search_provider"
        ds = [d.strip() for d in domains.split(",") if d.strip()]
        if not ds or len(ds) > 5:
            return "get_sub_domains 失败：需提供 1-5 个领域名"
        if not self._any_client:
            return "查询失败：AnySearch 客户端未初始化"
        body = await self._any_client.get_sub_domains(ds)
        if "error" in body:
            return f"查询失败：{body['error']}"
        return format_anysearch_domains(body.get("data") or {})

    def _any_enabled(self) -> bool:
        if self._provider == "tavily":
            return False
        return True
