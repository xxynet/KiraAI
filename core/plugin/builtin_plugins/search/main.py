import asyncio
import json
import re
from typing import Literal, Optional

import httpx
from tavily import TavilyClient

from core.plugin import BasePlugin, logger, register


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
        self._any_key = ""
        self._any_auto_key = ""
        self._any_base = "https://api.anysearch.com"
        self._max_results = 5
        self._hybrid_weight = 0.4
        self.tavily_available = True
        self.anysearch_available = True

    async def initialize(self):
        """加载配置：Tavily Key / 搜索模式 / AnySearch 参数（section 优先，扁平兜底兼容旧配置）"""
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
        self._any_key = str(src.get("anysearch_key") or self.plugin_cfg.get("anysearch_key", "") or "").strip()
        base = str(src.get("anysearch_base_url") or self.plugin_cfg.get("anysearch_base_url", "") or "").strip().rstrip("/")
        if base:
            self._any_base = base
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
        if not self._any_key:
            # 尝试读取缓存的匿名自动 Key
            try:
                f = self.ctx.get_plugin_data_dir() / "anysearch_auto_key.txt"
                if f.exists():
                    self._any_auto_key = f.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        logger.info("Initializing Search Plugin mode=%s tavily=%s anysearch=%s hybrid_weight=%s",
                    self._provider, self.tavily_available, bool(self._any_key or self._any_auto_key), self._hybrid_weight)

    def _tool_timeout(self) -> float:
        """跟随框架全局工具调用超时（bot_config.agent.tool_call_timeout，默认 60s）"""
        try:
            t = self.ctx.config.get_config("bot_config.agent.tool_call_timeout", 60.0)
            t = float(t)
            return t if t > 0 else 60.0
        except Exception:
            return 60.0

    async def terminate(self):
        pass

    # ---------- AnySearch 内部逻辑 ----------

    def _any_headers(self, key: str = None) -> dict:
        h = {"Content-Type": "application/json", "X-Anysearch-Client": "kiraai/1.0.0"}
        k = key or self._any_key or self._any_auto_key
        if k:
            h["Authorization"] = f"Bearer {k}"
        return h

    async def _save_any_auto_key(self, key: str):
        if not key or key == self._any_auto_key:
            return
        self._any_auto_key = key
        try:
            f = self.ctx.get_plugin_data_dir() / "anysearch_auto_key.txt"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(key, encoding="utf-8")
            try:
                f.chmod(0o600)
            except OSError:
                pass
        except Exception as e:
            logger.warning("save anysearch auto key failed: %s", e)

    @staticmethod
    def _extract_any_key(message: str) -> str:
        if not message:
            return ""
        for line in message.splitlines():
            line = line.strip()
            if line.startswith("api_key="):
                return line.split("=", 1)[1].strip().rstrip(".")
        return ""

    async def _any_call(self, method: str, path: str, payload: dict = None, params: list = None) -> dict:
        try:
            async with httpx.AsyncClient(timeout=self._tool_timeout()) as client:
                resp = await client.request(
                    method, f"{self._any_base}{path}", json=payload, params=params,
                    headers=self._any_headers(),
                )
        except httpx.TimeoutException:
            return {"error": "AnySearch 请求超时，请稍后重试"}
        except httpx.HTTPError as e:
            return {"error": f"AnySearch 网络错误：{e}"}
        try:
            body = resp.json()
        except Exception:
            return {"error": f"AnySearch 无效响应（HTTP {resp.status_code}）：{resp.text[:200]}"}
        if not isinstance(body, dict):
            return {"error": f"AnySearch 无效响应（HTTP {resp.status_code}）：非 JSON 对象"}

        # 匿名自动开户：message 里带自动生成的 api_key，提取并重试一次
        if resp.status_code >= 400 and body.get("code", 0) != 0:
            auto_key = self._extract_any_key(body.get("message", ""))
            if auto_key:
                await self._save_any_auto_key(auto_key)
                try:
                    async with httpx.AsyncClient(timeout=self._tool_timeout()) as client:
                        resp = await client.request(
                            method, f"{self._any_base}{path}", json=payload, params=params,
                            headers=self._any_headers(auto_key),
                        )
                    body = resp.json()
                    if resp.status_code < 400 and body.get("code", 0) == 0:
                        return body
                except Exception as e:
                    logger.warning("AnySearch retry after auto key failed: %s", e)
                return {"error": "AnySearch 匿名开户后重试失败，请稍后重试"}
        if resp.status_code >= 400 or body.get("code", 0) != 0:
            msg = body.get("message") or f"HTTP {resp.status_code}"
            rid = body.get("request_id", "")
            return {"error": f"{msg}（request_id: {rid}）" if rid else msg}
        return body

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
        payload = {"query": query}
        if sub_domain:
            payload["tag"] = sub_domain
        p = self._parse_params(params)
        if p:
            payload["params"] = p
        if topic == "news":
            payload["language"] = "zh"
        payload["max_results"] = self._max_results
        body = await self._any_call("POST", "/v1/search", payload=payload)
        if "error" in body:
            return {"results": [], "error": body["error"]}
        data = body.get("data") or {}
        results = []
        for it in (data.get("results") or []):
            item = dict(it)
            item["source"] = "anysearch"
            item["score"] = float(item.get("score") or 0.0)
            results.append(item)
        return {"results": results, "error": None}

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
            for rank, it in enumerate(results, 1):
                key = self._norm_url(it.get("url") or "")
                if not key:
                    key = f"__title_{(it.get('title') or '')[:80].lower()}"
                rrf = 1.0 / (self._RRF_K + rank)
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

    @staticmethod
    def _fmt_hybrid(results: list, total: int = None) -> str:
        """融合结果按原版 Tavily JSON 风格输出：全量字段，source/fusion_score 附加，content 不截断"""
        if not results:
            return "[]"
        out = []
        for r in results:
            item = {
                "title": r["title"],
                "url": r["url"],
                "content": r["content"],
                "score": round(r["fusion_score"], 4),
                "source": ",".join(sorted(r["sources"])),
                "fusion_score": round(r["fusion_score"], 4),
            }
            out.append(item)
        return "".join(json.dumps(ele, ensure_ascii=False) for ele in out)

    # ---------- 源选择 ----------

    def _resolve_mode(self) -> str:
        """返回实际执行模式：hybrid / tavily / anysearch
        hybrid 下任一源不可用自动降级为另一单源（Tavily 无 Key 时走 AnySearch），
        已完全覆盖原 auto 模式语义，故不再单设 auto"""
        if self._provider == "tavily":
            return "tavily" if self.tavily_available else "anysearch"
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
            res = await self._any_search(query, sub_domain, params, topic)
            if res["error"]:
                return f"搜索失败：{res['error']}"
            return self._fmt_any_search({"results": res["results"]})

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
            return self._fmt_hybrid(fused)

        if mode == "tavily":
            res = await self._tavily_search(query, topic, search_depth)
            if res["error"]:
                return f"搜索失败：{res['error']}"
            return "".join(json.dumps(ele, ensure_ascii=False) for ele in res["results"])

        # anysearch 单源
        res = await self._any_search(query, None, None, topic)
        if res["error"]:
            return f"搜索失败：{res['error']}"
        return self._fmt_any_search({"results": res["results"]})

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
        if mode in ("hybrid", "tavily") and self.tavily_available:
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

        body = await self._any_call("POST", "/v1/extract", payload={"url": url})
        if "error" in body:
            return f"提取失败：{body['error']}"
        data = body.get("data") or {}
        if not data.get("content"):
            return f"未能从 {url} 提取到正文（可能是不支持的格式或页面为空）"
        return self._fmt_any_extract(data)

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
            body = await self._any_call("POST", "/v1/search", payload=item)
            return item["query"], body

        results = await asyncio.gather(*(one(it) for it in normalized))
        out = []
        for q, body in results:
            if "error" in body:
                out.append(json.dumps({"query": q, "error": body["error"]}, ensure_ascii=False))
            else:
                out.append(self._fmt_any_search(body.get("data") or {}))
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
        body = await self._any_call("GET", "/v1/sub-domains", params=[("domain", d) for d in ds])
        if "error" in body:
            return f"查询失败：{body['error']}"
        return self._fmt_any_domains(body.get("data") or {})

    def _any_enabled(self) -> bool:
        return self._provider in ("hybrid", "anysearch") or not self.tavily_available

    # ---------- 格式化 ----------

    @staticmethod
    def _fmt_any_search(data: dict) -> str:
        """AnySearch 结果按原版 Tavily JSON 风格输出，保留 source/score 字段"""
        results = data.get("results") or []
        if not results:
            return "[]"
        out = []
        for r in results:
            out.append({
                "title": r.get("title") or "",
                "url": r.get("url") or "",
                "content": r.get("content") or r.get("snippet") or "",
                "score": r.get("score") or 0.0,
                "source": r.get("source") or "anysearch",
            })
        return "".join(json.dumps(ele, ensure_ascii=False) for ele in out)

    @staticmethod
    def _fmt_any_extract(data: dict) -> str:
        title = data.get("title") or ""
        url = data.get("url") or ""
        content = data.get("content") or ""
        head = f"## {title}\n\n**来源**: {url}\n\n---\n\n" if title or url else ""
        return head + content

    @staticmethod
    def _fmt_any_domains(data: dict) -> str:
        domains = data.get("domains") or []
        if not domains:
            return "该领域暂无可用的垂直子域"
        lines = []
        for d in domains:
            subs = d.get("sub_domains") or []
            if not subs:
                continue
            lines.append(f"## {d.get('domain', '')}（{len(subs)} 个子域）")
            for s in subs:
                lines.append(f"### {s.get('sub_domain', '')}")
                lines.append(s.get("description", ""))
                params = s.get("params") or {}
                if params:
                    lines.append("")
                    lines.append("**参数：**")
                    entries = sorted(params.items(), key=lambda item: (item[1] or {}).get("sort_order", 0))
                    for name, info in entries:
                        info = info or {}
                        req = "（必填）" if info.get("required") else ""
                        lines.append(f"- `{name}`{req}: {info.get('description', '')}")
                lines.append("")
        return "\n".join(lines).rstrip()
