from core.plugin.builtin_plugins.search.utils import (
    format_anysearch_domains,
    format_anysearch_extract,
    format_anysearch_search,
    format_hybrid_results,
)


def test_format_anysearch_search_preserves_tavily_compatible_shape():
    assert format_anysearch_search({"results": [{"title": "Result", "url": "https://example.com", "snippet": "Text"}]}) == (
        '{"title": "Result", "url": "https://example.com", "content": "Text", '
        '"score": 0.0, "source": "anysearch"}'
    )


def test_format_hybrid_results_includes_sorted_sources_and_fusion_score():
    assert format_hybrid_results([{
        "title": "Result",
        "url": "https://example.com",
        "content": "Text",
        "fusion_score": 0.12345,
        "sources": {"tavily", "anysearch"},
    }]) == (
        '{"title": "Result", "url": "https://example.com", "content": "Text", '
        '"score": 0.1235, "source": "anysearch,tavily", "fusion_score": 0.1235}'
    )


def test_format_anysearch_extract_includes_source_header_when_available():
    assert format_anysearch_extract({"title": "Result", "url": "https://example.com", "content": "Text"}) == (
        "## Result\n\n**来源**: https://example.com\n\n---\n\nText"
    )


def test_format_anysearch_domains_includes_required_parameter_metadata():
    assert format_anysearch_domains({
        "domains": [{
            "domain": "finance",
            "sub_domains": [{
                "sub_domain": "finance.quote",
                "description": "Quote lookup",
                "params": {"symbol": {"required": True, "description": "Ticker", "sort_order": 1}},
            }],
        }],
    }) == "## finance（1 个子域）\n### finance.quote\nQuote lookup\n\n**参数：**\n- `symbol`（必填）: Ticker"
