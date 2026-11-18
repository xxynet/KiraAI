from datetime import timedelta, timezone

from core.plugin.builtin_plugins.search.utils import (
    format_anysearch_domains,
    format_extracted_page,
    format_search_results,
)


def test_format_search_results_uses_separate_entries_and_source_fallback():
    assert format_search_results(
        [{"title": "Result", "url": "https://example.com", "snippet": "Text"}, {"title": "Another result"}],
        source="anysearch",
    ) == (
        "### 1. Result\nURL: https://example.com\nSource: anysearch\n\nText"
        "\n\n### 2. Another result\nSource: anysearch"
    )


def test_format_search_results_includes_sorted_sources_and_readable_publication_date():
    assert format_search_results([{
        "title": "Result",
        "url": "https://example.com",
        "content": "Text",
        "sources": {"tavily", "anysearch"},
        "published_date": 0,
    }], timezone=timezone(timedelta(hours=8))) == (
        "### 1. Result\nURL: https://example.com\nSource: anysearch, tavily"
        "\nPublished: 1970-01-01 08:00:00+08:00\n\nText"
    )


def test_format_extracted_page_includes_source_header_and_retains_tavily_body():
    assert format_extracted_page({"title": "Result", "url": "https://example.com", "raw_content": "Text"}) == (
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
