from core.utils.time_utils import format_timestamp


def format_search_results(results: list, *, source: str = "", timezone=None) -> str:
    if not results:
        return "No web results found."
    blocks = []
    for index, result in enumerate(results, 1):
        title = result.get("title") or result.get("url") or "Untitled"
        lines = [f"### {index}. {title}"]
        providers = ", ".join(sorted(result.get("sources", ()))) or result.get("source") or source
        published = result.get("published_date")
        if isinstance(published, (int, float)):
            published = format_timestamp(published, timezone)
        for label, value in (("URL", result.get("url")), ("Source", providers), ("Published", published)):
            if value:
                lines.append(f"{label}: {value}")
        if result.get("fusion_score") is not None:
            lines.append(f"Fusion score: {result['fusion_score']:.4f}")
        elif result.get("score") is not None:
            lines.append(f"Score: {result['score']}")
        content = result.get("content") or result.get("snippet")
        if content:
            lines.extend(("", content))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_extracted_page(data: dict) -> str:
    """Format the extracted page content from either provider."""
    title = data.get("title") or ""
    url = data.get("url") or ""
    content = data.get("content") or data.get("raw_content") or ""
    header = f"## {title}\n\n**来源**: {url}\n\n---\n\n" if title or url else ""
    images = data.get("images") or []
    image_links = "\n".join(f"- {image}" for image in images if isinstance(image, str))
    return header + content + (f"\n\nImages:\n{image_links}" if image_links else "")


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
