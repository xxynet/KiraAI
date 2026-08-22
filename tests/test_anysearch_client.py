import json

import httpx
import pytest

from core.plugin.builtin_plugins.search.anysearch import AnySearchClient


@pytest.mark.asyncio
async def test_search_normalizes_results_and_sends_configured_credentials():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://anysearch.test/v1/search"
        assert request.headers["Authorization"] == "Bearer configured-key"
        assert json.loads(request.content) == {
            "query": "KiraAI",
            "tag": "code.github",
            "params": {"language": "python"},
            "max_results": 3,
        }
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {"results": [{"title": "KiraAI", "score": "0.8"}]},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnySearchClient(
        "https://anysearch.test",
        api_key="configured-key",
        http_client=http_client,
    )
    try:
        result = await client.search(
            "KiraAI",
            max_results=3,
            sub_domain="code.github",
            params={"language": "python"},
        )
    finally:
        await http_client.aclose()

    assert result == {
        "results": [{"title": "KiraAI", "score": 0.8, "source": "anysearch"}],
        "error": None,
    }


@pytest.mark.asyncio
async def test_search_retries_with_and_caches_anonymous_key(tmp_path):
    authorization_headers = []

    async def handler(request: httpx.Request) -> httpx.Response:
        authorization_headers.append(request.headers.get("Authorization"))
        if len(authorization_headers) == 1:
            return httpx.Response(401, json={"code": 401, "message": "api_key=anonymous-key."})
        return httpx.Response(200, json={"code": 0, "data": {"results": []}})

    cache_path = tmp_path / "anysearch_auto_key.txt"
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AnySearchClient(
        "https://anysearch.test",
        auto_key_path=cache_path,
        http_client=http_client,
    )
    try:
        result = await client.search("KiraAI")
    finally:
        await http_client.aclose()

    assert result == {"results": [], "error": None}
    assert authorization_headers == [None, "Bearer anonymous-key"]
    assert cache_path.read_text(encoding="utf-8") == "anonymous-key"
