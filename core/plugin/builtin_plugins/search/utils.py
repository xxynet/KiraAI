import json


def format_hybrid_results(results: list) -> str:
    """Format fused search results in the established Tavily-compatible JSON style."""
    if not results:
        return "[]"
    output = []
    for result in results:
        output.append({
            "title": result["title"],
            "url": result["url"],
            "content": result["content"],
            "score": round(result["fusion_score"], 4),
            "source": ",".join(sorted(result["sources"])),
            "fusion_score": round(result["fusion_score"], 4),
        })
    return "".join(json.dumps(item, ensure_ascii=False) for item in output)


def format_anysearch_search(data: dict) -> str:
    """Format AnySearch results in the established Tavily-compatible JSON style."""
    results = data.get("results") or []
    if not results:
        return "[]"
    output = []
    for result in results:
        output.append({
            "title": result.get("title") or "",
            "url": result.get("url") or "",
            "content": result.get("content") or result.get("snippet") or "",
            "score": result.get("score") or 0.0,
            "source": result.get("source") or "anysearch",
        })
    return "".join(json.dumps(item, ensure_ascii=False) for item in output)


def format_anysearch_extract(data: dict) -> str:
    """Format extracted AnySearch page content for tool output."""
    title = data.get("title") or ""
    url = data.get("url") or ""
    content = data.get("content") or ""
    header = f"## {title}\n\n**来源**: {url}\n\n---\n\n" if title or url else ""
    return header + content


def format_anysearch_domains(data: dict) -> str:
    """Format the AnySearch vertical-domain catalog for tool output."""
    domains = data.get("domains") or []
    if not domains:
        return "该领域暂无可用的垂直子域"
    lines = []
    for domain in domains:
        sub_domains = domain.get("sub_domains") or []
        if not sub_domains:
            continue
        lines.append(f"## {domain.get('domain', '')}（{len(sub_domains)} 个子域）")
        for sub_domain in sub_domains:
            lines.append(f"### {sub_domain.get('sub_domain', '')}")
            lines.append(sub_domain.get("description", ""))
            params = sub_domain.get("params") or {}
            if params:
                lines.append("")
                lines.append("**参数：**")
                entries = sorted(params.items(), key=lambda item: (item[1] or {}).get("sort_order", 0))
                for name, info in entries:
                    info = info or {}
                    required = "（必填）" if info.get("required") else ""
                    lines.append(f"- `{name}`{required}: {info.get('description', '')}")
            lines.append("")
    return "\n".join(lines).rstrip()
