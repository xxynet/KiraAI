"""
KiraAI arXiv 论文查询/下载插件

功能：
- /arxiv search <关键词>   搜索论文，返回标题/摘要/作者/arXiv ID/PDF 链接（默认 5 条）
- /arxiv get <arXiv ID>    获取单篇论文详情
- /arxiv tr  <arXiv ID>    将单篇论文的标题与摘要翻译成中文
- /arxiv src <arXiv ID>    下载 LaTeX 源码到 data/files/arxiv_src/
- /arxiv dl  <arXiv ID>    下载 PDF 到 data/files/arxiv_pdf/ 并返回本地路径
- /arxiv help              查看帮助

同时注册 LLM 工具：arxiv_search / arxiv_get / arxiv_translate / arxiv_download / arxiv_src /
arxiv_translate_latex（后台异步翻译任务，提交后立即返回任务 ID，完成后自动推送 PDF）/ query_arxiv_translate_task / parse_arxiv_command。

数据源：arXiv 官方 API（export.arxiv.org/api/query，Atom XML 格式）。
PDF：   https://arxiv.org/pdf/{id}
源码：  https://arxiv.org/e-print/{id}

实现要点：
- 遵守 arXiv API 礼貌间隔（两次请求 >= 3 秒），模块级锁 + 时间戳节流
- PDF 并发下载通过信号量限制（默认 3），临时文件 + os.replace 原子落盘
- 结果带 TTL 内存缓存，减少重复 API 调用
- 全部网络错误/解析错误/ID 校验均有兜底，返回友好错误信息
- arXiv ID 白名单正则校验，防止路径穿越
"""

import asyncio
import gzip
import inspect
import io
import os
import re
import shutil
import tarfile
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Dict, List, Optional, Tuple

import httpx

from core.plugin import BasePlugin, logger, register, on, Priority
from core.chat.message_utils import MessageChain, KiraMessageEvent
from core.chat.message_elements import Text, At
from core.provider import LLMRequest

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

API_BASE = "https://export.arxiv.org/api/query"
PDF_BASE = "https://arxiv.org/pdf/"

# arXiv API 官方建议两次请求间隔 >= 3 秒
MIN_API_INTERVAL = 3.0
# PDF 并发下载上限
MAX_DOWNLOAD_CONCURRENCY = 3
# 结果缓存 TTL（秒）与最大条数
CACHE_TTL = 600.0
MAX_CACHE_SIZE = 200

# 新旧两种 arXiv ID 格式：2101.00001 或 math/0101011（可带 vN 版本号）
ARXIV_ID_RE = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z\-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?$",
    re.IGNORECASE,
)

# 模块级节流状态（跨实例共享，防止多用户同时打爆 API）
_api_lock = asyncio.Lock()
_last_api_call = 0.0
_download_sem = asyncio.Semaphore(MAX_DOWNLOAD_CONCURRENCY)

# ── 后台翻译任务注册表（模块级，跨实例共享）──
# task_id → 任务状态 dict；asyncio.Lock 保证同一事件循环内对字典的读写串行化
_translation_tasks: Dict[str, dict] = {}
_translation_tasks_lock = asyncio.Lock()
# 持有后台 asyncio.Task 引用，防止任务被垃圾回收而意外取消
_bg_tasks: set = set()


class ArxivApiError(Exception):
    """arXiv API 请求 / 解析 / 下载相关错误"""


class ArxivSearchPlugin(BasePlugin):
    """arXiv 论文查询与下载插件"""

    SELF_PLUGIN_ID = "arxiv_search"

    # ---------------------------------------------------------------
    # 生命周期
    # ---------------------------------------------------------------

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.download_dir = self._resolve_download_dir()
        self.source_dir = self._resolve_source_dir()
        self._cache: Dict[str, Tuple[float, List[dict]]] = {}

    def _cfg(self, key: str, default=None):
        """读取配置：优先顶层字段，其次扫描各 section 下的字段。"""
        cfg = self.plugin_cfg or {}
        if key in cfg:
            return cfg.get(key, default)
        for value in cfg.values():
            if isinstance(value, dict) and key in value:
                return value.get(key, default)
        return default

    def _resolve_download_dir(self) -> Path:
        cfg_dir = (self._cfg("download_dir", "") or "").strip()
        base = Path(cfg_dir) if cfg_dir else Path("data/files/arxiv_pdf")
        if not base.is_absolute():
            base = Path.cwd() / base
        return base

    def _resolve_source_dir(self) -> Path:
        cfg_dir = (self._cfg("source_dir", "") or "").strip()
        base = Path(cfg_dir) if cfg_dir else Path("data/files/arxiv_src")
        if not base.is_absolute():
            base = Path.cwd() / base
        return base

    async def on_load(self):
        logger.info("arXiv 插件已加载，PDF 目录: %s，源码目录: %s", self.download_dir, self.source_dir)
        for _dir in (self.download_dir, self.source_dir):
            try:
                _dir.mkdir(parents=True, exist_ok=True)
            except OSError as e:
                logger.error("创建目录失败（%s）: %s", _dir, e)

    async def on_unload(self):
        logger.info("arXiv 插件已卸载")
        # 取消仍挂起的后台翻译任务（在途任务会被标记为 failed）
        for _t in list(_bg_tasks):
            if not _t.done():
                _t.cancel()
        _bg_tasks.clear()

    async def initialize(self):
        await self.on_load()

    async def terminate(self):
        await self.on_unload()

    # ---------------------------------------------------------------
    # 内部工具方法
    # ---------------------------------------------------------------

    async def _translate_lines(
        self, lines: List[str], target: str = "zh", client=None, fallback: bool = True
    ) -> Optional[List[str]]:
        """批量翻译多行文本（每行一条）。

        client 缺省用快速 LLM；失败/禁用/无 client 时：fallback=True 回退原文（原行为），
        fallback=False 返回 None（供 /arxiv tr 等需要区分「翻译失败」的调用方使用）。
        """
        if not lines:
            return lines
        if not self._cfg("translate_enabled", True):
            return lines if fallback else None
        if client is None:
            client = self.ctx.get_default_fast_llm_client()
        if not client:
            return lines if fallback else None
        try:
            numbered = "\n".join(f"{i+1}. {line}" for i, line in enumerate(lines))
            prompt = (
                f"请将以下 {len(lines)} 条文本逐条翻译成{target}，"
                f"严格保持编号格式，每条一行，只输出翻译结果，不要任何解释。\n\n{numbered}"
            )
            request = LLMRequest(messages=[{"role": "user", "content": prompt}])
            response = await client.chat(request)
            result = (response.text_response or "").strip()
            translated: List[str] = []
            for line in result.splitlines():
                line = line.strip()
                m = re.match(r"^\d+[.、:：]\s*(.*)$", line)
                translated.append(m.group(1).strip() if m else line)
            if len(translated) != len(lines) or any(not x for x in translated):
                return lines if fallback else None
            return translated
        except Exception as e:
            logger.warning("arXiv 翻译失败: %s", e)
            return lines if fallback else None

    @staticmethod
    def _truncate(text: str, length: int) -> str:
        """压缩空白并截断文本，超出部分以省略号结尾。"""
        text = re.sub(r"\s+", " ", text or "").strip()
        if len(text) <= length:
            return text
        return text[: length - 1].rstrip() + "…"

    @staticmethod
    def _fmt_date(value: str) -> str:
        """把 2021-05-06T14:42:39Z 格式化为 2021-05-06。"""
        if not value:
            return ""
        return value[:10]

    @staticmethod
    def _fmt_size(size: int) -> str:
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / 1024 / 1024:.2f} MB"

    def _cache_get(self, key: str) -> Optional[List[dict]]:
        item = self._cache.get(key)
        if item and time.monotonic() - item[0] < CACHE_TTL:
            return item[1]
        return None

    def _cache_set(self, key: str, value: List[dict]) -> None:
        if len(self._cache) >= MAX_CACHE_SIZE:
            now = time.monotonic()
            for k in [k for k, v in self._cache.items() if now - v[0] >= CACHE_TTL]:
                self._cache.pop(k, None)
        self._cache[key] = (time.monotonic(), value)

    def _parse_entry(self, entry: ET.Element) -> dict:
        """解析单条 Atom <entry> 为结构化 dict。"""
        def _text(tag: str, ns: str = ATOM_NS) -> str:
            node = entry.find(f"{{{ns}}}{tag}")
            if node is None:
                return ""
            return " ".join("".join(node.itertext()).split())

        authors = []
        for author in entry.findall(f"{{{ATOM_NS}}}author"):
            name = author.findtext(f"{{{ATOM_NS}}}name") or ""
            name = " ".join(name.split())
            if name:
                authors.append(name)

        pdf_url = ""
        abs_url = ""
        for link in entry.findall(f"{{{ATOM_NS}}}link"):
            if link.get("title") == "pdf" and not pdf_url:
                pdf_url = link.get("href") or ""
            if link.get("rel") == "alternate" and not abs_url:
                abs_url = link.get("href") or ""

        entry_id = _text("id")
        paper_id = ""
        if entry_id:
            paper_id = entry_id.rstrip("/").rsplit("/", 1)[-1]

        primary = entry.find(f"{{{ARXIV_NS}}}primary_category")
        categories = [
            c.get("term")
            for c in entry.findall(f"{{{ATOM_NS}}}category")
            if c.get("term")
        ]
        if primary is not None and primary.get("term") not in categories:
            categories.insert(0, primary.get("term"))

        return {
            "id": paper_id,
            "title": _text("title") or "（无标题）",
            "summary": _text("summary"),
            "authors": authors,
            "published": _text("published"),
            "updated": _text("updated"),
            "primary_category": primary.get("term") if primary is not None else "",
            "categories": categories,
            "comment": _text("comment", ARXIV_NS),
            "doi": _text("doi", ARXIV_NS),
            "pdf_url": pdf_url or (f"{PDF_BASE}{paper_id}" if paper_id else ""),
            "abs_url": abs_url or (f"https://arxiv.org/abs/{paper_id}" if paper_id else ""),
        }

    async def _api_query(self, params: dict) -> List[dict]:
        """调用 arXiv API（带节流），返回解析后的论文列表。"""
        global _last_api_call
        timeout = float(self._cfg("request_timeout", 15) or 15)
        async with _api_lock:
            now = time.monotonic()
            wait = MIN_API_INTERVAL - (now - _last_api_call)
            if wait > 0:
                await asyncio.sleep(wait)
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    resp = await client.get(API_BASE, params=params)
                    resp.raise_for_status()
                    content = resp.content
                _last_api_call = time.monotonic()
            except httpx.HTTPError as e:
                raise ArxivApiError(f"arXiv API 请求失败: {e}") from e
        try:
            root = ET.fromstring(content)
        except ET.ParseError as e:
            raise ArxivApiError(f"arXiv API 返回解析失败: {e}") from e
        return [self._parse_entry(entry) for entry in root.findall(f"{{{ATOM_NS}}}entry")]

    @staticmethod
    def _normalize_search_query(raw: str) -> str:
        """构造 arXiv search_query：带字段前缀（ti:/au:/abs:/cat:/all:）则原样透传，否则默认 all:。"""
        query = raw.strip()
        if not query:
            raise ValueError("搜索关键词不能为空")
        if re.match(r"^(?:all|ti|au|abs|co|jr|cat|rn):", query, re.IGNORECASE):
            return query
        return f"all:{query}"

    async def _search(self, query: str, max_results: int = 5) -> List[dict]:
        search_query = self._normalize_search_query(query)
        cache_key = f"search|{search_query}|{max_results}|{self._cfg('sort_by', 'relevance')}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        sort_by = self._cfg("sort_by", "relevance")
        if sort_by not in ("relevance", "submittedDate", "lastUpdatedDate"):
            sort_by = "relevance"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max(max_results, 0),
            "sortBy": sort_by,
        }
        results = await self._api_query(params)
        self._cache_set(cache_key, results)
        return results

    async def _get_by_id(self, arxiv_id: str) -> Optional[dict]:
        cache_key = f"id|{arxiv_id.lower()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached[0] if cached else None
        results = await self._api_query({"id_list": arxiv_id})
        paper = results[0] if results else None
        self._cache_set(cache_key, [paper] if paper else [])
        return paper

    @staticmethod
    def _sanitize_id(arxiv_id: str) -> str:
        """校验并规范化 arXiv ID，仅保留安全字符，防止路径穿越。"""
        raw = (arxiv_id or "").strip().lower()
        if not raw:
            raise ValueError("arXiv ID 不能为空")
        if not ARXIV_ID_RE.match(raw):
            raise ValueError(
                f"无效的 arXiv ID: {arxiv_id!r}（格式示例：1706.03762 或 math/0101011v1）"
            )
        # 旧式 ID 中的斜杠（如 math/0101011）替换为下划线，避免路径层级
        return raw.replace("/", "_")

    async def _download_pdf(self, arxiv_id: str) -> Tuple[str, int]:
        """下载 PDF 到下载目录，返回 (本地绝对路径, 字节数)。临时文件 + os.replace 原子落盘。"""
        safe_id = self._sanitize_id(arxiv_id)
        save_dir = self.download_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        final_path = save_dir / f"{safe_id}.pdf"
        url = f"{PDF_BASE}{arxiv_id}"
        timeout = float(self._cfg("request_timeout", 30) or 30)

        tmp_path = None
        async with _download_sem:
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        fd, tmp_name = tempfile.mkstemp(
                            prefix=f".{safe_id}.", suffix=".part", dir=str(save_dir)
                        )
                        tmp_path = Path(tmp_name)
                        size = 0
                        with os.fdopen(fd, "wb") as fh:
                            async for chunk in resp.aiter_bytes(65536):
                                fh.write(chunk)
                                size += len(chunk)
            except httpx.HTTPError as e:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
                raise ArxivApiError(f"PDF 下载失败（{arxiv_id}）: {e}") from e
            except OSError as e:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
                raise ArxivApiError(f"PDF 写入失败（{arxiv_id}）: {e}") from e

        # 内容校验：必须是 PDF 魔数
        try:
            with open(tmp_path, "rb") as fh:
                head = fh.read(5)
        except OSError as e:
            tmp_path.unlink(missing_ok=True)
            raise ArxivApiError(f"PDF 校验失败（{arxiv_id}）: {e}") from e
        if head[:4] != b"%PDF":
            tmp_path.unlink(missing_ok=True)
            raise ArxivApiError(
                f"下载内容不是有效的 PDF 文件（{arxiv_id}），可能是 ID 不存在或 arXiv 返回了错误页"
            )
        os.replace(tmp_path, final_path)
        return str(final_path), size

    @staticmethod
    def _infer_src_extension(content_type: str, head: bytes) -> str:
        """推断 arXiv e-print 源码包扩展名：优先 Content-Type，其次魔数嗅探。

        e-print 接口常见 Content-Type：
        - application/x-eprint-tar   → .tar.gz（多文件打包）
        - application/x-eprint       → .tex.gz（gzip 压缩的单篇 .tex）
        - application/x-tex / text/plain → .tex
        """
        ct = (content_type or "").lower()
        if "eprint-tar" in ct or ("tar" in ct and "gzip" in ct):
            return ".tar.gz"
        if "x-eprint" in ct or "gzip" in ct:
            return ".tex.gz"
        if "tar" in ct:
            return ".tar"
        if "tex" in ct or "plain" in ct:
            return ".tex"
        # Content-Type 缺失或不可靠时按魔数嗅探
        if head[:2] == b"\x1f\x8b":  # gzip 魔数
            try:
                with gzip.GzipFile(fileobj=io.BytesIO(head)) as gz:
                    decompressed = gz.read(1024)
                if decompressed[257:262] == b"ustar":  # gzip 内是 tar → .tar.gz
                    return ".tar.gz"
            except (OSError, EOFError, ValueError):
                pass
            return ".tex.gz"
        if head[257:262] == b"ustar":  # 未压缩的 tar
            return ".tar"
        return ".tex"

    async def _download_src(self, arxiv_id: str) -> Tuple[str, int]:
        """下载 LaTeX 源码包（e-print）到源码目录，返回 (本地绝对路径, 字节数)。

        临时文件 + os.replace 原子落盘，流式下载，校验非空且非 HTML 错误页；
        扩展名按 Content-Type / 魔数推断，文件名 = _sanitize_id 后的 id + 扩展名。
        """
        safe_id = self._sanitize_id(arxiv_id)
        save_dir = self.source_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        url = f"https://arxiv.org/e-print/{arxiv_id}"
        timeout = float(self._cfg("request_timeout", 30) or 30)

        tmp_path = None
        content_type = ""
        size = 0
        async with _download_sem:
            try:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                    async with client.stream("GET", url) as resp:
                        resp.raise_for_status()
                        content_type = resp.headers.get("content-type", "")
                        fd, tmp_name = tempfile.mkstemp(
                            prefix=f".{safe_id}.", suffix=".part", dir=str(save_dir)
                        )
                        tmp_path = Path(tmp_name)
                        with os.fdopen(fd, "wb") as fh:
                            async for chunk in resp.aiter_bytes(65536):
                                fh.write(chunk)
                                size += len(chunk)
            except httpx.HTTPError as e:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
                raise ArxivApiError(f"源码下载失败（{arxiv_id}）: {e}") from e
            except OSError as e:
                if tmp_path:
                    tmp_path.unlink(missing_ok=True)
                raise ArxivApiError(f"源码写入失败（{arxiv_id}）: {e}") from e

        # 校验：非空、非 HTML 错误页，然后推断扩展名
        try:
            with open(tmp_path, "rb") as fh:
                head = fh.read(1024)
        except OSError as e:
            tmp_path.unlink(missing_ok=True)
            raise ArxivApiError(f"源码校验失败（{arxiv_id}）: {e}") from e
        if size <= 0:
            tmp_path.unlink(missing_ok=True)
            raise ArxivApiError(f"下载内容为空（{arxiv_id}），可能该论文没有公开的 LaTeX 源码")
        stripped = head.lstrip()[:256].lower()
        if stripped[:5] in (b"<html", b"<!doc") or b"404" in stripped:
            tmp_path.unlink(missing_ok=True)
            raise ArxivApiError(
                f"下载到的是错误页面而非源码包（{arxiv_id}），可能是 ID 不存在或该论文未公开源码"
            )
        ext = self._infer_src_extension(content_type, head)
        final_path = save_dir / f"{safe_id}{ext}"
        os.replace(tmp_path, final_path)
        return str(final_path), size

    # ---------------------------------------------------------------
    # 结果格式化
    # ---------------------------------------------------------------

    def _format_search_results(self, query: str, papers: List[dict]) -> str:
        if not papers:
            return f"❌ 未在 arXiv 找到与「{query}」相关的论文"
        lines = [f"📚 arXiv 搜索结果：{query}（共 {len(papers)} 条）", ""]
        for i, paper in enumerate(papers, 1):
            authors = ", ".join(paper["authors"][:3])
            if len(paper["authors"]) > 3:
                authors += f" 等{len(paper['authors'])}人"
            category = paper["primary_category"] or (",".join(paper["categories"][:2]) if paper["categories"] else "-")
            lines.append(f"{i}. {paper['title']}")
            lines.append(f"   📎 arXiv:{paper['id']} | 🏷 {category}")
            if authors:
                lines.append(f"   👤 {authors}")
            lines.append(f"   🗓 {self._fmt_date(paper['published']) or '-'}")
            lines.append(f"   📝 {self._truncate(paper['summary'], 180)}")
            lines.append(f"   🔗 PDF: {paper['pdf_url']}")
            lines.append("")
        return "\n".join(lines).rstrip()

    def _format_paper_detail(self, paper: dict) -> str:
        lines = [f"📄 {paper['title']}", ""]
        lines.append(f"🔖 arXiv ID: {paper['id']}")
        if paper["authors"]:
            lines.append(f"👥 作者({len(paper['authors'])}): {', '.join(paper['authors'])}")
        published = self._fmt_date(paper["published"])
        updated = self._fmt_date(paper["updated"])
        if published and updated and updated != published:
            lines.append(f"🗓 发布: {published} | 更新: {updated}")
        elif published:
            lines.append(f"🗓 发布: {published}")
        if paper["categories"]:
            lines.append(f"🏷 分类: {', '.join(paper['categories'])}")
        if paper.get("comment"):
            lines.append(f"💬 备注: {self._truncate(paper['comment'], 120)}")
        if paper.get("doi"):
            lines.append(f"🔗 DOI: {paper['doi']}")
        lines.append("")
        lines.append(f"📝 摘要: {paper['summary']}")
        lines.append("")
        if paper["pdf_url"]:
            lines.append(f"🔗 PDF: {paper['pdf_url']}")
        if paper["abs_url"]:
            lines.append(f"🌐 页面: {paper['abs_url']}")
        return "\n".join(lines)

    def _format_download_result(self, paper: dict, local_path: str, size: int) -> str:
        lines = ["✅ 论文下载成功", ""]
        lines.append(f"📄 {paper['title']}")
        lines.append(f"🔖 arXiv ID: {paper['id']}")
        lines.append(f"📁 本地路径: {local_path}")
        lines.append(f"📦 文件大小: {self._fmt_size(size)}")
        lines.append(f"🔗 在线: {paper['pdf_url']}")
        return "\n".join(lines)

    def _format_src_result(self, arxiv_id: str, local_path: str, size: int) -> str:
        lines = ["✅ 源码下载成功", ""]
        lines.append(f"🔖 arXiv ID: {arxiv_id}")
        lines.append(f"📁 本地路径: {local_path}")
        lines.append(f"📦 文件大小: {self._fmt_size(size)}")
        lines.append(f"🔗 在线: https://arxiv.org/e-print/{arxiv_id}")
        return "\n".join(lines)

    # ---------------------------------------------------------------
    # LLM 工具 1：搜索
    # ---------------------------------------------------------------

    @register.tool(
        "arxiv_search",
        "在 arXiv 学术预印本库中按关键词搜索论文，返回标题、摘要、作者、arXiv ID、分类和 PDF 下载链接。"
        "支持 arXiv 高级查询语法（如 au:vaswani、ti:attention、cat:cs.CL、abs:deep learning），"
        "多个词默认按 AND 组合，可通过 AND/OR/NOT 与括号组合。",
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，例如 'large language model' 或高级语法 'au:vaswani AND ti:attention'"
                },
                "max_results": {
                    "type": "integer",
                    "description": "返回条数，默认 5，最大 20",
                    "default": 5
                },
                "translate": {
                    "type": "boolean",
                    "description": "是否将各论文标题翻译为目标语言（默认 false）",
                    "default": False
                }
            },
            "required": ["query"]
        }
    )
    async def tool_arxiv_search(self, event, query: str, max_results: int = 5, translate: bool = False):
        """按关键词搜索 arXiv 论文。"""
        try:
            limit = int(max_results) if max_results else 0
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            limit = int(self._cfg("max_results", 5) or 5)
        limit = max(1, min(limit, 20))
        try:
            papers = await self._search(query, limit)
        except ArxivApiError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.exception("arxiv_search 未预期异常")
            return f"❌ 搜索失败：{type(e).__name__}: {e}"
        result = self._format_search_results(query, papers)
        if translate:
            titles = [p["title"] for p in papers]
            translated = await self._translate_lines(titles)
            if translated and len(translated) == len(titles):
                lines = ["", "【标题译文】"]
                for i, t in enumerate(translated, 1):
                    lines.append(f"{i}. {t}")
                result += "\n" + "\n".join(lines)
        return result

    # ---------------------------------------------------------------
    # LLM 工具 2：获取单篇详情
    # ---------------------------------------------------------------

    @register.tool(
        "arxiv_get",
        "根据 arXiv ID 获取单篇论文详情，包含完整标题、全部作者、摘要、发布日期、分类、PDF 链接。"
        "arXiv ID 示例：1706.03762 或 math/0101011。",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "arXiv ID，例如 1706.03762"
                },
                "translate": {
                    "type": "boolean",
                    "description": "是否将标题与摘要翻译为目标语言（默认 false）",
                    "default": False
                }
            },
            "required": ["arxiv_id"]
        }
    )
    async def tool_arxiv_get(self, event, arxiv_id: str, translate: bool = False):
        """根据 arXiv ID 获取单篇论文详情。"""
        try:
            self._sanitize_id(arxiv_id)
        except ValueError as e:
            return f"❌ {e}"
        try:
            paper = await self._get_by_id(arxiv_id.strip())
        except ArxivApiError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.exception("arxiv_get 未预期异常")
            return f"❌ 获取失败：{type(e).__name__}: {e}"
        if not paper:
            return f"❌ 未找到 arXiv 论文：{arxiv_id.strip()}"
        result = self._format_paper_detail(paper)
        if translate:
            translated = await self._translate_lines([paper["title"], paper["summary"]])
            if translated and len(translated) == 2:
                t_title, t_summary = translated
                result += "\n\n【标题译文】" + t_title
                result += "\n\n【摘要译文】" + t_summary
        return result

    # ---------------------------------------------------------------
    # LLM 工具 3：下载 PDF
    # ---------------------------------------------------------------

    @register.tool(
        "arxiv_download",
        "根据 arXiv ID 下载论文 PDF 到本地 data/files/arxiv_pdf/ 目录，返回本地文件路径、大小与在线链接。"
        "支持一次传入多个 ID（空格或逗号分隔），将并发下载。arXiv ID 示例：1706.03762。",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "arXiv ID，或空格/逗号分隔的多个 ID，例如 '1706.03762 2105.02723'"
                }
            },
            "required": ["arxiv_id"]
        }
    )
    async def tool_arxiv_download(self, event, arxiv_id: str):
        """下载论文 PDF 到本地。"""
        ids = [x.strip() for x in re.split(r"[\s,]+", arxiv_id or "") if x.strip()]
        if not ids:
            return "❌ 请提供 arXiv ID，例如：/arxiv dl 1706.03762"
        for raw in ids:
            try:
                self._sanitize_id(raw)
            except ValueError as e:
                return f"❌ {e}"
        if len(ids) == 1:
            return await self._download_one(ids[0])
        return await self._download_many(ids)

    async def _download_one(self, arxiv_id: str) -> str:
        paper = None
        try:
            paper = await self._get_by_id(arxiv_id)
        except ArxivApiError as e:
            return f"❌ {e}"
        if not paper:
            return f"❌ 未找到 arXiv 论文：{arxiv_id}（ID 可能不存在，请先 /arxiv search 确认）"
        try:
            local_path, size = await self._download_pdf(paper["id"])
        except ArxivApiError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.exception("PDF 下载未预期异常")
            return f"❌ PDF 下载失败：{type(e).__name__}: {e}"
        return self._format_download_result(paper, local_path, size)

    async def _download_many(self, ids: List[str]) -> str:
        results = await asyncio.gather(
            *(self._download_one(pid) for pid in ids),
            return_exceptions=True,
        )
        blocks = []
        for pid, res in zip(ids, results):
            if isinstance(res, BaseException):
                blocks.append(f"❌ {pid}: 下载失败（{type(res).__name__}: {res}）")
            else:
                blocks.append(res)
        return "\n\n".join(blocks)

    # ---------------------------------------------------------------
    # LLM 工具 5：翻译标题/摘要
    # ---------------------------------------------------------------

    @register.tool(
        "arxiv_translate",
        "根据 arXiv ID 获取单篇论文，并将标题与摘要翻译成中文，便于快速了解论文大意。"
        "翻译使用默认 LLM；若翻译服务不可用会返回友好提示，可改用 arxiv_get 获取原文详情。"
        "arXiv ID 示例：1706.03762 或 math/0101011。",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "arXiv ID，例如 1706.03762"
                }
            },
            "required": ["arxiv_id"]
        }
    )
    async def tool_arxiv_translate(self, event, arxiv_id: str):
        """根据 arXiv ID 将单篇论文的标题与摘要翻译成中文。"""
        try:
            self._sanitize_id(arxiv_id)
        except ValueError as e:
            return f"❌ {e}"
        try:
            paper = await self._get_by_id(arxiv_id.strip())
        except ArxivApiError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.exception("arxiv_translate 未预期异常")
            return f"❌ 获取论文失败：{type(e).__name__}: {e}"
        if not paper:
            return f"❌ 未找到 arXiv 论文：{arxiv_id.strip()}"
        if not self._cfg("translate_enabled", True):
            return "❌ 翻译功能已在配置中关闭（translate_enabled=false），可先用 /arxiv get 查看原文"
        client = self.ctx.get_default_llm_client()
        if not client:
            return "❌ 翻译服务不可用，先试试 /arxiv get"
        try:
            translated = await self._translate_lines(
                [paper["title"], paper["summary"]], target="zh", client=client, fallback=False
            )
        except Exception as e:
            logger.warning("arxiv_translate LLM 调用异常: %s", e)
            return "❌ 翻译服务不可用，先试试 /arxiv get"
        if not translated or len(translated) != 2:
            return "❌ 翻译服务不可用，先试试 /arxiv get"
        t_title, t_summary = translated
        return "\n".join([
            f"📄 标题：{paper['title']}",
            "",
            f"🀄 译文标题：{t_title}",
            "",
            f"📝 摘要：{paper['summary']}",
            "",
            f"🀄 译文摘要：{t_summary}",
            "",
            f"🔖 arXiv ID: {paper['id']}",
        ])

    # ---------------------------------------------------------------
    # LLM 工具 6：下载 LaTeX 源码
    # ---------------------------------------------------------------

    @register.tool(
        "arxiv_src",
        "根据 arXiv ID 下载论文的 LaTeX 源码包（e-print，格式为 .tar.gz / .tex.gz / .tex）"
        "到本地 data/files/arxiv_src/ 目录，返回本地文件路径、大小与在线 e-print 链接。"
        "arXiv ID 示例：1706.03762。",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "arXiv ID，例如 1706.03762"
                }
            },
            "required": ["arxiv_id"]
        }
    )
    async def tool_arxiv_src(self, event, arxiv_id: str):
        """下载论文 LaTeX 源码包（e-print）到本地。"""
        try:
            self._sanitize_id(arxiv_id)
        except ValueError as e:
            return f"❌ {e}"
        try:
            local_path, size = await self._download_src(arxiv_id.strip())
        except ArxivApiError as e:
            return f"❌ {e}"
        except Exception as e:
            logger.exception("arxiv_src 未预期异常")
            return f"❌ 源码下载失败：{type(e).__name__}: {e}"
        return self._format_src_result(arxiv_id.strip(), local_path, size)

    # ---------------------------------------------------------------
    # LLM 工具 4：代为执行斜杠命令
    # ---------------------------------------------------------------

    @register.tool(
        "parse_arxiv_command",
        "解析并执行 arXiv 插件的斜杠命令（默认前缀 /arxiv，可在插件配置中自定义）。"
        "当用户消息中出现斜杠命令（如 /arxiv search transformer）时调用本工具。"
        "支持子命令：search <关键词> 搜索论文；get <ID> 获取单篇详情；dl <ID> [多个] 下载 PDF；help 帮助。",
        {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "完整的斜杠命令文本，例如 '/arxiv search attention is all you need' 或 '/arxiv dl 1706.03762'"
                }
            },
            "required": ["command"]
        }
    )
    async def tool_parse_arxiv_command(self, event, command: str):
        """LLM 可调用本工具代为执行 /arxiv 斜杠命令。"""
        return await self._parse_and_execute(command or "", event)

    # ---------------------------------------------------------------
    # 斜杠命令支持（/arxiv ...）
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_text(event) -> str:
        """从事件中提取纯文本，跳过 At 元素，并去掉 @ 残留前缀。"""
        def _iter_text_parts(chain):
            for ele in chain or []:
                if isinstance(ele, At):
                    continue
                if isinstance(ele, Text):
                    yield ele.text or ""

        msg = getattr(event, "message", None)
        chain = getattr(msg, "chain", None) if msg is not None else None
        if chain is not None:
            text = " ".join(_iter_text_parts(chain)).strip()
        else:
            parts = []
            for m in getattr(event, "messages", []) or []:
                parts.extend(_iter_text_parts(getattr(m, "chain", None)))
            text = " ".join(parts).strip()
        return re.sub(r"^(?:@\S+\s*)+", "", text).strip()

    @staticmethod
    def _get_sid(event) -> str:
        """获取会话 ID（adapter:type:id）。"""
        session = getattr(event, "session", None)
        if session is not None:
            sid = getattr(session, "sid", None)
            if sid:
                return sid
        msg = getattr(event, "message", None)
        if msg is not None:
            sender = getattr(msg, "sender", None)
            adapter = getattr(event, "adapter", None)
            adapter_name = getattr(adapter, "name", "unknown") if adapter else "unknown"
            if sender is not None:
                group = getattr(msg, "group", None)
                if group is not None and getattr(group, "group_id", None):
                    return f"{adapter_name}:gm:{group.group_id}"
                if getattr(sender, "user_id", None):
                    return f"{adapter_name}:dm:{sender.user_id}"
        return ""

    @staticmethod
    def _get_user_id(event) -> str:
        """获取发送者 QQ 号（兼容单条/批量事件）。"""
        msg = getattr(event, "message", None)
        if msg is not None:
            sender = getattr(msg, "sender", None)
            if sender is not None and getattr(sender, "user_id", None):
                return str(sender.user_id)
        for m in getattr(event, "messages", []) or []:
            sender = getattr(m, "sender", None)
            if sender is not None and getattr(sender, "user_id", None):
                return str(sender.user_id)
        return ""

    @staticmethod
    def _is_group_message(event) -> bool:
        """是否为群消息（群消息要求 @ 本 bot，私聊无需）。"""
        is_group = getattr(event, "is_group_message", None)
        if callable(is_group):
            try:
                return bool(is_group())
            except Exception:
                pass
        msg = getattr(event, "message", None)
        if msg is not None and getattr(msg, "group", None) is not None:
            return True
        messages = getattr(event, "messages", None) or []
        if messages and getattr(messages[-1], "group", None) is not None:
            return True
        return False

    @staticmethod
    def _bot_self_id(event) -> str:
        """获取本 bot 的 QQ 号（兼容单条/批量事件）。"""
        msg = getattr(event, "message", None)
        if msg is not None:
            sid = getattr(msg, "self_id", None)
            if sid:
                return str(sid)
        for m in getattr(event, "messages", []) or []:
            sid = getattr(m, "self_id", None)
            if sid:
                return str(sid)
        return ""

    @staticmethod
    def _is_bot_at(event, bot_id: str) -> bool:
        """消息链中是否存在 @ 本 bot 的 At 元素。"""
        if not bot_id:
            return False
        bot_id = str(bot_id)
        msg = getattr(event, "message", None)
        chain = getattr(msg, "chain", None) if msg is not None else None
        if chain is not None:
            return any(
                getattr(ele, "pid", None) == bot_id
                for ele in chain
                if isinstance(ele, At)
            )
        for m in getattr(event, "messages", []) or []:
            for ele in getattr(m, "chain", None) or []:
                if isinstance(ele, At) and getattr(ele, "pid", None) == bot_id:
                    return True
        return False

    def _command_prefix(self) -> str:
        """斜杠命令前缀（可配置，默认 /arxiv）。"""
        return (self._cfg("command_prefix", "/arxiv") or "/arxiv").strip()

    async def _check_slash_allowed(self, event) -> Tuple[bool, str]:
        """斜杠命令白名单校验：留空=不限制；配置了则仅限名单内 QQ。"""
        whitelist = self._cfg("slash_whitelist") or []
        if not whitelist:
            return True, ""
        allowed = {str(x).strip() for x in whitelist if str(x).strip()}
        uid = self._get_user_id(event)
        if not uid:
            return False, "❌ 无法识别发送者 QQ 号，斜杠命令已拒绝执行。"
        if uid in allowed:
            return True, ""
        return False, f"❌ 您不在白名单内，无权使用 {self._command_prefix()} 斜杠命令（你的 QQ：{uid}）。"

    async def _reply(self, event, content: str, at_uid: str = ""):
        """把结果作为消息发回当前会话；群聊带 At，私聊纯文本。"""
        sid = self._get_sid(event)
        if not sid:
            logger.warning("无法确定会话 ID，arXiv 斜杠命令结果未发送")
            return
        chain = [Text(content)]
        if at_uid and self._is_group_message(event):
            chain = [At(at_uid), Text(content)]
        try:
            await self.ctx.message_processor.send_message_chain(
                session=sid, chain=MessageChain(chain)
            )
        except Exception as e:
            logger.error(f"发送 arXiv 斜杠命令回复失败（尝试退化纯文本）: {e}")
            if len(chain) > 1:
                try:
                    await self.ctx.message_processor.send_message_chain(
                        session=sid, chain=MessageChain([Text(content)])
                    )
                except Exception as e2:
                    logger.error(f"发送 arXiv 斜杠命令回复（纯文本）失败: {e2}")

    def _help_text(self) -> str:
        prefix = self._command_prefix()
        return (
            f"📚 arXiv 论文助手使用说明\n\n"
            f"🔍 {prefix} search <关键词> — 搜索论文（默认 5 条），"
            f"支持高级语法如 au:作者 ti:标题 cat:分类\n"
            f"📄 {prefix} get <arXiv ID> — 获取单篇论文详情\n"
            f"🀄 {prefix} tr <arXiv ID> — 将单篇论文的标题与摘要翻译成中文\n"
            f"⬇️  {prefix} dl <arXiv ID> [多个ID] — 下载 PDF 到 data/files/arxiv_pdf/\n"
            f"📦 {prefix} src <arXiv ID> — 下载 LaTeX 源码包到 data/files/arxiv_src/\n"
            f"📖 {prefix} translate-latex <arXiv ID> — 提交翻译任务：下载源码→翻译正文→编译 PDF（后台异步，完成后自动推送，需先安装 TeX Live）\n"
            f"🔎 {prefix} translate-status <任务ID> — 查询翻译任务状态\n"
            f"ℹ️  {prefix} help — 查看帮助\n\n"
            f"示例：\n"
            f"  {prefix} search large language model\n"
            f"  {prefix} get 1706.03762\n"
            f"  {prefix} tr 1706.03762\n"
            f"  {prefix} dl 1706.03762\n"
            f"  {prefix} src 1706.03762"
        )

    async def _parse_and_execute(self, text: str, event) -> str:
        """解析并执行斜杠命令（前缀可配置，默认 /arxiv），返回结果字符串。"""
        parts = (text or "").split()
        if not parts:
            return ""
        sub = parts[1].lower() if len(parts) > 1 else ""
        args = parts[2:]

        if sub in ("", "help", "-h", "--help"):
            return self._help_text()

        if sub == "search":
            if not args:
                return "❌ 用法：/arxiv search <关键词> [-t]，例如 /arxiv search large language model"
            translate = any(a in ("-t", "--translate") for a in args)
            q = " ".join(a for a in args if a not in ("-t", "--translate"))
            if not q:
                return "❌ 用法：/arxiv search <关键词> [-t]，例如 /arxiv search large language model"
            return await self.tool_arxiv_search(event, q, translate=translate)

        if sub == "get":
            if not args:
                return "❌ 用法：/arxiv get <arXiv ID> [-t]，例如 /arxiv get 1706.03762"
            translate = any(a in ("-t", "--translate") for a in args)
            ids = [a for a in args if a not in ("-t", "--translate")]
            if not ids:
                return "❌ 用法：/arxiv get <arXiv ID> [-t]，例如 /arxiv get 1706.03762"
            return await self.tool_arxiv_get(event, ids[0], translate=translate)

        if sub == "tr":
            if not args:
                return "❌ 用法：/arxiv tr <arXiv ID>，例如 /arxiv tr 1706.03762"
            return await self.tool_arxiv_translate(event, args[0])

        if sub == "src":
            if not args:
                return "❌ 用法：/arxiv src <arXiv ID>，例如 /arxiv src 1706.03762"
            return await self.tool_arxiv_src(event, args[0])

        if sub in ("translate-latex", "trl"):
            if not args:
                return "❌ 用法：/arxiv translate-latex <arXiv ID>，例如 /arxiv translate-latex 1706.03762"
            return await self.tool_arxiv_translate_latex(event, args[0])

        if sub in ("translate-status", "trs", "tstatus"):
            if not args:
                return "❌ 用法：/arxiv translate-status <任务ID>，例如 /arxiv translate-status TR1700000000A1B2C3"
            return self._format_translate_task(args[0])

        if sub == "dl":
            if not args:
                return "❌ 用法：/arxiv dl <arXiv ID> [更多ID...]，例如 /arxiv dl 1706.03762"
            return await self.tool_arxiv_download(event, " ".join(args))

        return (
            f"❌ 未知子命令：{sub}\n\n{self._help_text()}"
        )

    @on.im_message(priority=Priority.HIGH)
    async def handle_arxiv_commands(self, event: KiraMessageEvent):
        """拦截斜杠命令开头的消息（前缀可配置，默认 /arxiv），直接执行，不再进入 LLM 流程。

        钩子整体兜底：任何异常都先尝试回复错误信息而不是静默抛错；
        确认命中斜杠命令后，finally 中确保 event.discard()/stop() 仍执行，
        避免消息漏进 LLM 流程。
        """
        matched = False
        try:
            if not self._cfg("enable_commands", True):
                return
            text = self._extract_text(event)
            if not text:
                return
            # 群消息必须 @ 本 bot 才检测斜杠命令；私聊无需 @
            if self._is_group_message(event):
                bot_id = self._bot_self_id(event)
                if not bot_id or not self._is_bot_at(event, bot_id):
                    return
            stripped = text.strip()
            prefix = self._command_prefix()
            # 仅匹配 "/arxiv" 或 "/arxiv ..."（大小写不敏感），避免误伤 /arxivx 等
            if not re.match(rf"^{re.escape(prefix)}(\s|$)", stripped, re.IGNORECASE):
                return
            matched = True
            logger.info("拦截到 arXiv 斜杠命令: %s", stripped[:100])

            allowed, denied = await self._check_slash_allowed(event)
            if not allowed:
                await self._reply(event, denied, at_uid=self._get_user_id(event))
                return

            try:
                result = await self._parse_and_execute(stripped, event)
            except Exception as e:
                logger.exception("arXiv 斜杠命令执行异常: %s", e)
                result = f"❌ 斜杠命令执行出错：{type(e).__name__}: {e}"

            if result and result.strip():
                await self._reply(event, result, at_uid=self._get_user_id(event))
        except Exception as e:
            logger.exception("arXiv 斜杠命令钩子异常: %s", e)
            try:
                await self._reply(
                    event, f"❌ arXiv 斜杠命令处理失败：{type(e).__name__}: {e}"
                )
            except Exception:
                logger.exception("arXiv 斜杠命令钩子异常后回复失败")
        finally:
            if matched:
                try:
                    event.discard(force=True)
                    event.stop()
                except Exception as e:
                    logger.warning("丢弃 arXiv 斜杠命令消息失败: %s", e)

    # ---------------------------------------------------------------
    # LLM 工具 7：翻译 LaTeX 并编译 PDF
    # ---------------------------------------------------------------

    @staticmethod
    def _extract_translation(result: str) -> str:
        """从翻译插件返回值中提取译文正文（去掉 ✅/❌ 前缀与后端/缓存说明行）。"""
        if not result or not result.startswith("✅"):
            return ""
        body = result[1:].strip()
        lines = body.split("\n")
        if lines and lines[-1].strip().startswith("（"):
            lines = lines[:-1]
        return "\n".join(lines).strip()

    @staticmethod
    def _protect_latex_line(line: str):
        """把一行 LaTeX 中的公式/命令/花括号内容替换为占位符，返回 (纯文本, 占位符列表)。

        占位符形如 __KIRA_PH_0__，翻译后再按序还原，保证 LaTeX 结构不被翻译破坏。
        """
        ph: list = []

        def _mk(m):
            ph.append(m.group(0))
            return f"__KIRA_PH_{len(ph) - 1}__"

        s = re.sub(r"\$\$.*?\$\$|\$.*?\$", _mk, line, flags=re.S)
        s = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?(?:\{[^}]*\})*", _mk, s)
        s = re.sub(r"\{[^}]*\}", _mk, s)
        return s, ph

    @staticmethod
    def _restore_placeholders(text: str, ph: list) -> str:
        """将译文中的占位符还原为原始 LaTeX 片段。"""
        def _rp(m):
            idx = int(m.group(1))
            return ph[idx] if idx < len(ph) else m.group(0)
        return re.sub(r"__KIRA_PH_(\d+)__", _rp, text)

    @staticmethod
    def _check_texlive() -> Optional[str]:
        """检查 TeX Live 是否可用（xelatex/pdflatex），不可用返回错误说明。"""
        if shutil.which("xelatex"):
            return None
        if shutil.which("pdflatex"):
            return None
        return "TeX Live 尚未安装完成（找不到 xelatex/pdflatex），请等安装结束后再试。"

    @staticmethod
    def _extract_source(archive: str, dest_dir: Path) -> Optional[Path]:
        """解压 arXiv e-print 源码包，返回主 .tex 文件路径（含 \\documentclass 者优先）。"""
        dest_dir.mkdir(parents=True, exist_ok=True)
        archive = str(archive)
        if archive.endswith((".tar.gz", ".tgz")):
            with tarfile.open(archive, "r:gz") as tf:
                # 防路径穿越：只解压安全成员（拒绝绝对路径与含 .. 的路径）
                safe = [
                    m for m in tf.getmembers()
                    if not m.name.startswith("/") and ".." not in m.name.split("/")
                ]
                tf.extractall(dest_dir, members=safe)
        elif archive.endswith(".tex.gz"):
            import gzip as _gz
            out = dest_dir / (os.path.basename(archive)[:-3])
            with _gz.open(archive, "rt", encoding="utf-8", errors="ignore") as f:
                out.write_text(f.read(), encoding="utf-8")
            return out
        elif archive.endswith(".tex"):
            return Path(archive)

        tex_files = sorted(dest_dir.rglob("*.tex"))
        for f in tex_files:
            try:
                head = f.read_text(encoding="utf-8", errors="ignore")[:2000]
            except Exception:
                continue
            if "\\documentclass" in head:
                return f
        return tex_files[0] if tex_files else None

    async def _send_to_session(self, sid: str, content: str):
        """向指定会话发送一条消息（后台任务推送用）。失败仅记录日志，不影响主流程。"""
        if not sid:
            return
        try:
            await self.ctx.message_processor.send_message_chain(
                session=sid, chain=MessageChain([Text(content)])
            )
        except Exception as e:
            logger.warning("向会话 %s 发送消息失败: %s", sid, e)

    @staticmethod
    def _translate_accepts_model(trans) -> bool:
        """判断翻译插件 translate() 接口是否支持按调用覆盖模型（model 参数）。

        当前 kira-ai-plugin-translate 的 translate() 仅接受 backend，不支持 model；
        若接口后续升级支持 model，本插件将自动透传 translate_local_model 实现按调用覆盖，
        否则 local 模型需在翻译插件侧配置（translate_local_model 留空即可）。
        """
        try:
            sig = inspect.signature(trans.translate)
            return "model" in sig.parameters
        except (TypeError, ValueError):
            return False

    async def _translate_tex_content(
        self,
        tex_text: str,
        event,
        on_progress: Optional[Callable[[int, int], object]] = None,
    ) -> tuple:
        """翻译 .tex 正文（保留 LaTeX 结构），返回 (译文文本或 None, 说明)。

        on_progress 为可选进度回调：每完成一块翻译后以 (done, total) 调用（async 可等待）。
        进度消息的节流（块数≤10 每块发，块数>10 每 5 块发一次含最后一块）由回调内部决定。
        """
        trans = self.ctx.get_plugin_inst("kira-ai-plugin-translate")
        if trans is None:
            return None, "翻译插件未加载，无法翻译正文。"

        out_lines: list = []
        pending: list = []  # (out_idx, protected_text, ph)
        for line in tex_text.split("\n"):
            stripped = line.strip()
            # 跳过空行、注释行、环境标记行
            if (not stripped or stripped.startswith("%")
                    or stripped.startswith("\\begin{") or stripped.startswith("\\end{")):
                out_lines.append(line)
                continue
            protected, ph = self._protect_latex_line(line)
            if protected.strip() and not protected.strip().startswith("\\"):
                pending.append((len(out_lines), protected, ph))
                out_lines.append(None)  # 占位，稍后填入译文
            else:
                out_lines.append(line)

        if not pending:
            return "\n".join(out_lines), "未发现可翻译的正文文本。"

        # 分块翻译：按字符数把待翻行切成 ≤MAX_CHARS 的块，逐块调用翻译服务（避免超长正文超上限）
        # 翻译后端/模型由插件配置控制：translate_backend（auto/baidu/deepl/google/aliyun/local）
        # 与 translate_local_model（backend=local 时覆盖翻译插件的 local_model，留空用翻译插件自身配置）
        backend = (self._cfg("translate_backend", "auto") or "auto").strip().lower()
        if backend not in ("auto", "baidu", "deepl", "google", "aliyun", "local"):
            backend = "auto"
        translate_kwargs = {"backend": backend}
        local_model = (self._cfg("translate_local_model", "") or "").strip() or None
        if local_model and backend == "local" and self._translate_accepts_model(trans):
            # 仅当翻译插件 translate() 接口支持按调用覆盖模型（model 参数）时才透传；
            # 否则回退到翻译插件自身的 local_model（需在翻译插件侧配置）。
            translate_kwargs["model"] = local_model

        MAX_CHARS = 4500
        blocks: list = []  # 每块为若干待翻行文本
        cur: list = []
        cur_len = 0
        for (idx, protected, ph) in pending:
            line_len = len(protected) + 1
            if cur and cur_len + line_len > MAX_CHARS:
                blocks.append(cur)
                cur = []
                cur_len = 0
            cur.append(protected)
            cur_len += line_len
        if cur:
            blocks.append(cur)

        total = len(blocks)

        t_lines: list = []
        for idx, block in enumerate(blocks, start=1):
            block_text = "\n".join(block)
            result = await trans.translate(
                event, text=block_text, target_lang="zh", source_lang="en", **translate_kwargs
            )
            translated = self._extract_translation(result)
            if not translated:
                return None, f"翻译失败：{result}"
            bt = translated.split("\n")
            if len(bt) != len(block):
                # 该块行数不一致时逐行翻译
                bt = []
                for bl in block:
                    r = await trans.translate(
                        event, text=bl, target_lang="zh", source_lang="en", **translate_kwargs
                    )
                    one = self._extract_translation(r)
                    if not one:
                        return None, f"逐行翻译失败：{r}"
                    bt.append(one)
            t_lines.extend(bt)
            # 翻译进度回调：每完成一块上报一次（节流/推送由回调内部处理）
            if on_progress is not None:
                try:
                    _res = on_progress(idx, total)
                    if asyncio.iscoroutine(_res):
                        await _res
                except Exception as _e:
                    logger.warning("翻译进度回调异常: %s", _e)

        for (idx, protected, ph), tline in zip(pending, t_lines):
            out_lines[idx] = self._restore_placeholders(tline, ph)
        return "\n".join(out_lines), f"翻译了 {len(pending)} 行正文（{len(blocks)} 块）。"

    async def _compile_pdf(self, tex_path: Path) -> tuple:
        """用 xelatex 编译 .tex 产出 PDF，返回 (pdf路径或 None, 错误说明)。"""
        err = self._check_texlive()
        if err:
            return None, err
        out_dir = self.download_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        cmd = (
            f'cd "{tex_path.parent}" && xelatex -interaction=nonstopmode '
            f'-halt-on-error -output-directory="{out_dir}" "{tex_path.name}"'
        )
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            tail = ((stderr or b"") + (stdout or b""))[-500:].decode("utf-8", "ignore")
            return None, f"编译失败（exit {proc.returncode}）：{tail}"
        pdf = out_dir / f"{tex_path.stem}.pdf"
        if not pdf.exists():
            return None, "编译结束但未找到 PDF 输出文件。"
        return str(pdf), ""

    # ── 后台任务注册表操作 ──

    @staticmethod
    def _new_task_id() -> str:
        """生成翻译任务 ID：时间戳 + uuid 短码（如 TR1700000000A1B2C3）。"""
        return f"TR{int(time.time())}{uuid.uuid4().hex[:6].upper()}"

    async def _update_task(self, task_id: str, **fields):
        """加锁更新任务状态记录（不存在的任务静默忽略）。"""
        async with _translation_tasks_lock:
            task = _translation_tasks.get(task_id)
            if task is None:
                return
            task.update(fields)
            task["updated_at"] = time.time()

    def _schedule_background(self, coro) -> asyncio.Task:
        """把协程调度为后台任务并持有引用，防止被 GC 回收而意外取消。"""
        task = asyncio.create_task(coro)
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)
        return task

    # ── 后台翻译任务主流程 ──

    async def _run_translate_latex_task(self, task_id: str, arxiv_id: str, sid: str):
        """后台执行：下载源码 → 解压 → 分块翻译 → 编译 PDF，全程更新任务状态并推送进度。"""
        try:
            # 轻量事件桩：供翻译插件读取会话 session_id（用于额度/缓存键）
            session_id = sid.rsplit(":", 1)[-1] if ":" in sid else sid
            stub_event = SimpleNamespace(
                session=SimpleNamespace(session_id=session_id, sid=sid)
            )

            # ── 1. 下载源码 ──
            await self._update_task(task_id, status="running", stage="download")
            local_path, _ = await self._download_src(arxiv_id)

            # ── 2. 解压 ──
            await self._update_task(task_id, stage="extract")
            archive = Path(local_path)
            work_dir = archive.parent / f"{self._sanitize_id(arxiv_id)}_work"
            try:
                main_tex = self._extract_source(str(archive), work_dir)
            except Exception as e:
                raise ArxivApiError(f"解压源码失败：{type(e).__name__}: {e}")
            if main_tex is None:
                raise ArxivApiError(f"源码包中未找到 .tex 文件：{local_path}")
            try:
                tex_text = main_tex.read_text(encoding="utf-8", errors="ignore")
            except Exception as e:
                raise ArxivApiError(f"读取 .tex 失败：{e}")

            # ── 3. 分块翻译 ──
            await self._update_task(task_id, stage="translate")

            async def _on_progress(done: int, total: int):
                # 每完成一块都更新任务状态；消息按节流规则推送：
                # 块数≤10 每块发，块数>10 每 5 块发一次（含最后一块）
                await self._update_task(
                    task_id, done_blocks=done, total_blocks=total, stage="translate"
                )
                step = 1 if total <= 10 else 5
                if done == total or done % step == 0:
                    await self._send_to_session(sid, f"📖 翻译进度 {done}/{total} 块")

            translated, note = await self._translate_tex_content(
                tex_text, stub_event, on_progress=_on_progress
            )
            if translated is None:
                raise ArxivApiError(note)

            out_tex = main_tex.with_name(f"{main_tex.stem}_zh.tex")
            try:
                out_tex.write_text(translated, encoding="utf-8")
            except Exception as e:
                raise ArxivApiError(f"写入译文 .tex 失败：{e}")

            # ── 4. 编译 PDF ──
            await self._update_task(task_id, stage="compile")
            pdf_path, err = await self._compile_pdf(out_tex)
            if err:
                raise ArxivApiError(err)

            # ── 完成 ──
            await self._update_task(
                task_id,
                status="done",
                stage="done",
                result_pdf=pdf_path,
                result_tex=str(out_tex),
                note=note,
            )
            await self._send_to_session(
                sid,
                f"✅ 翻译完成（{note}）\n"
                f"📄 译文 TeX：{out_tex}\n"
                f"📕 PDF：{pdf_path}\n"
                f"🔖 任务ID：{task_id}",
            )
        except asyncio.CancelledError:
            logger.info("后台翻译任务 %s 被取消", task_id)
            await self._update_task(task_id, status="failed", error="任务被取消（插件卸载或系统关闭）")
            raise
        except Exception as e:
            logger.exception("后台翻译任务 %s 失败: %s", task_id, e)
            err_msg = f"{type(e).__name__}: {e}"
            await self._update_task(task_id, status="failed", error=err_msg)
            try:
                await self._send_to_session(
                    sid,
                    f"❌ 翻译任务 {task_id} 失败：{err_msg}\n"
                    f"（可用 query_arxiv_translate_task 查询详情）",
                )
            except Exception:
                logger.exception("发送翻译失败通知失败")

    def _format_translate_task(self, task_id: str) -> str:
        """格式化翻译任务状态查询结果。"""
        task = _translation_tasks.get(task_id)
        if task is None:
            return f"❌ 未找到翻译任务：{task_id}"
        status = task.get("status", "unknown")
        icon = {
            "pending": "⏳ 排队中",
            "running": "🔄 进行中",
            "done": "✅ 已完成",
            "failed": "❌ 已失败",
        }.get(status, f"❓ {status}")
        stage_name = {
            "queued": "排队",
            "download": "下载源码",
            "extract": "解压源码",
            "translate": "分块翻译",
            "compile": "编译 PDF",
            "done": "完成",
        }.get(task.get("stage", ""), task.get("stage", "") or "-")
        lines = [
            f"{icon} 翻译任务 {task_id}",
            f"📄 arXiv ID：{task.get('arxiv_id', '-')}",
            f"🛠 当前阶段：{stage_name}",
        ]
        total = task.get("total_blocks", 0)
        done = task.get("done_blocks", 0)
        if total:
            lines.append(f"📖 翻译进度：{done}/{total} 块")
        elif status in ("running", "pending"):
            lines.append("📖 翻译进度：尚未开始分块")
        if task.get("result_pdf"):
            lines.append(f"📕 PDF：{task['result_pdf']}")
        if task.get("result_tex"):
            lines.append(f"📄 译文 TeX：{task['result_tex']}")
        if task.get("note"):
            lines.append(f"📝 说明：{task['note']}")
        if status == "failed" and task.get("error"):
            lines.append(f"🚨 错误：{task['error']}")
        elapsed = time.time() - task.get("created_at", time.time())
        lines.append(f"⏱ 耗时：{elapsed:.0f}s")
        return "\n".join(lines)

    @register.tool(
        "arxiv_translate_latex",
        "根据 arXiv ID 下载论文 LaTeX 源码，翻译 .tex 正文（保留命令、公式、环境结构）并编译产出翻译后的 PDF。"
        "该工具是异步任务：调用后立即返回任务 ID，完整流程（下载源码→解压→分块翻译→编译）在后台执行，"
        "执行期间会向发起会话推送翻译进度，完成后自动把翻译 PDF 路径与说明发回会话。"
        "可用 query_arxiv_translate_task(task_id=...) 查询任务状态。使用前需安装 TeX Live。"
        "arXiv ID 示例：1706.03762。",
        {
            "type": "object",
            "properties": {
                "arxiv_id": {
                    "type": "string",
                    "description": "arXiv ID，例如 1706.03762"
                }
            },
            "required": ["arxiv_id"]
        }
    )
    async def tool_arxiv_translate_latex(self, event, arxiv_id: str):
        """提交 LaTeX 翻译任务：立即返回任务 ID，完整流程在后台异步执行。"""
        try:
            self._sanitize_id(arxiv_id)
        except ValueError as e:
            return f"❌ {e}"
        arxiv_id = arxiv_id.strip()
        sid = self._get_sid(event)
        if not sid:
            return "❌ 无法确定当前会话，翻译任务无法提交。"
        user_id = self._get_user_id(event)

        # 并发安全：同一会话同一论文已有进行中任务则拒绝重复提交
        async with _translation_tasks_lock:
            for _tid, _t in _translation_tasks.items():
                if (
                    _t.get("sid") == sid
                    and _t.get("arxiv_id") == arxiv_id
                    and _t.get("status") in ("pending", "running")
                ):
                    return (
                        f"❌ 该会话已有同一论文的翻译任务进行中（任务ID：{_tid}）。\n"
                        f"可用 query_arxiv_translate_task(task_id=\"{_tid}\") 查询进度，"
                        f"或等待其完成后再提交。"
                    )

        task_id = self._new_task_id()
        record = {
            "task_id": task_id,
            "arxiv_id": arxiv_id,
            "sid": sid,
            "user_id": user_id,
            "status": "pending",
            "stage": "queued",
            "total_blocks": 0,
            "done_blocks": 0,
            "result_pdf": "",
            "result_tex": "",
            "note": "",
            "error": "",
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        async with _translation_tasks_lock:
            _translation_tasks[task_id] = record

        self._schedule_background(self._run_translate_latex_task(task_id, arxiv_id, sid))

        logger.info("翻译任务已提交: %s (arxiv=%s, sid=%s)", task_id, arxiv_id, sid)
        return (
            f"📖 翻译任务已提交，任务ID：{task_id}\n"
            f"🔖 arXiv ID：{arxiv_id}\n"
            f"⚙️ 后台流程：下载源码 → 解压 → 分块翻译 → 编译 PDF\n"
            f"📨 执行期间会推送翻译进度，完成后自动发送 PDF 路径。\n"
            f"🔎 查询进度：query_arxiv_translate_task(task_id=\"{task_id}\")"
        )

    @register.tool(
        "query_arxiv_translate_task",
        "查询 arXiv LaTeX 翻译后台任务的状态。返回任务状态（pending 排队中 / running 进行中 / done 已完成 / failed 已失败）、"
        "当前阶段（下载源码/解压源码/分块翻译/编译 PDF）、分块翻译进度（已翻译块数/总块数）、结果 PDF/TeX 路径或错误信息。"
        "task_id 由 arxiv_translate_latex 提交时返回。",
        {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "翻译任务 ID，由 arxiv_translate_latex 返回，如 TR1700000000A1B2C3"
                }
            },
            "required": ["task_id"]
        }
    )
    async def tool_query_arxiv_translate_task(self, event, task_id: str):
        """查询翻译后台任务状态。"""
        task_id = (task_id or "").strip()
        if not task_id:
            return "❌ 请提供任务 ID，例如：/arxiv translate-status TR1700000000A1B2C3"
        return self._format_translate_task(task_id)
