"""Optional memory reranking, provider boundaries, budgets, and fallback behavior."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.plugin.builtin_plugins.memory.rerank import MemoryReranker
from core.prompt_manager import Prompt
from core.provider import LLMRequest, ModelInfo, ModelType, RerankModelClient
from core.provider.llm_model import RerankResult
from tests.test_builtin_memory import event, plugin_at, scope


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRerank(RerankModelClient):
    def __init__(self):
        super().__init__(ModelInfo(ModelType.RERANK, "rank-id", "provider-id", "Remote provider"))
        self.rerank = AsyncMock(side_effect=self.reverse)

    @staticmethod
    def reverse(query, documents, top_n):
        return [RerankResult(index=i, score=float(i), text="Untrusted provider text")
                for i in reversed(range(len(documents)))]


def attach_client(plugin):
    client = FakeRerank()
    plugin.ctx.provider_mgr = SimpleNamespace(
        get_default_rerank=Mock(return_value=client), get_model_client=Mock(return_value=client),
    )
    return client


async def populate(plugin, count=5):
    for index in range(count):
        await plugin.store.add(scope(), text=f"coffee fact {index}")
    return await plugin.store.search(scope(), "coffee", limit=min(count, 50))


@pytest.mark.anyio
async def test_default_disabled_preserves_order_without_resolving_or_calling_provider(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    client = attach_client(plugin)
    original = await populate(plugin)
    assert not plugin.reranker.enabled
    assert await plugin.search(scope(), "coffee") == original
    result = await plugin.recall(scope(), ["coffee"])
    assert result["retrieval"]["rerank"]["phase"] == "disabled"
    plugin.ctx.provider_mgr.get_default_rerank.assert_not_called()
    plugin.ctx.provider_mgr.get_model_client.assert_not_called()
    client.rerank.assert_not_awaited()


@pytest.mark.anyio
async def test_keyword_rerank_is_shared_by_tools_chat_and_both_preview_entries(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "recall_limit": 2})
    client = attach_client(plugin)
    original = await populate(plugin)
    expected = [row["id"] for row in reversed(original)]
    assert not plugin.vectors.enabled
    assert [row["id"] for row in await plugin.search(scope(), "coffee", limit=2)] == expected[:2]
    tool = json.loads(await plugin.memory_search(event(), query="coffee", limit=2))
    assert [row["id"] for row in tool["records"]] == expected[:2]
    for result in (await plugin.recall(scope(), ["coffee"]),
                   await plugin.api_recall({"messages": ["coffee"]}),
                   await plugin.api_recall({"adapter": "test", "session_id": "test:dm:alice",
                                            "persona_id": "persona-one", "messages": ["coffee"]})):
        assert [row["id"] for row in result["recalled"]] == expected[:2]
        assert result["retrieval"]["mode"] == "keyword"
        assert result["retrieval"]["rerank"]["phase"] == "applied"
        assert result["retrieval"]["rerank"]["candidates"] == 5
        assert all(row["text"] != "Untrusted provider text" for row in result["recalled"])
    request = LLMRequest(system_prompt=[Prompt("base", name="memory")])
    await plugin.inject_memory(event(), request)
    assert original[-1]["id"] in request.system_prompt[0].content
    assert original[0]["id"] not in request.system_prompt[0].content
    assert client.rerank.await_count == 6
    plugin.ctx.provider_mgr.get_default_rerank.assert_called()
    plugin.ctx.provider_mgr.get_model_client.assert_not_called()


@pytest.mark.anyio
async def test_selected_model_uses_host_typed_interface_and_preserves_colons(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "rerank_model": "p:model:alias"})
    client = attach_client(plugin)
    await populate(plugin)
    await plugin.search(scope(), "coffee")
    plugin.ctx.provider_mgr.get_model_client.assert_called_once_with("p", "model:alias", ModelType.RERANK)
    plugin.ctx.provider_mgr.get_default_rerank.assert_not_called()
    assert client.rerank.await_count == 1


@pytest.mark.anyio
async def test_prefix_is_ranked_before_pagination_and_tail_keeps_its_original_order(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "rerank_candidates": 4})
    client = attach_client(plugin)
    original = await populate(plugin, 9)
    expected = list(reversed(original[:4])) + original[4:]
    pages = []
    for offset in range(0, 9, 3):
        pages.extend(await plugin.search(scope(), "coffee", limit=3, offset=offset))
    assert pages == expected
    assert len({row["id"] for row in pages}) == 9
    assert client.rerank.await_count == 2
    calls = client.rerank.await_args_list
    assert calls[0].kwargs["documents"] == calls[1].kwargs["documents"]
    assert len(calls[0].kwargs["documents"]) == 4


@pytest.mark.anyio
async def test_empty_query_single_candidate_core_and_id_lookup_skip_rerank(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    row, _ = await plugin.store.add(scope(), text="coffee core", core=True)
    await plugin.search(scope(), "coffee")
    await plugin.search(scope(), "")
    await plugin.search(scope(), "coffee", core_only=True)
    await plugin.memory_search(event(), memory_id=row["id"])
    result = await plugin.recall(scope(), [])
    assert result["core"][0]["id"] == row["id"]
    assert result["retrieval"]["rerank"]["phase"] == "skipped"
    plugin.ctx.provider_mgr.get_default_rerank.assert_not_called()
    client.rerank.assert_not_awaited()


@pytest.mark.anyio
async def test_rerank_cannot_receive_records_outside_visibility_status_and_filters(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    original = await populate(plugin, 3)
    for context in (scope(persona="other"), scope(adapter="other"),
                    scope(target="bob", users=("bob",))):
        await plugin.store.add(context, text="hidden coffee")
    await plugin.store.add(scope(), text="expired coffee", expires_at=1)
    inactive, _ = await plugin.store.add(scope(), text="inactive coffee")
    await plugin.store.update(scope(), inactive["id"], 1, text=inactive["text"], status="completed")
    await plugin.store.add(scope(), text="other kind coffee", kind="episodic")
    result = await plugin.search(scope(), "coffee", kind="semantic")
    assert {row["id"] for row in result} == {row["id"] for row in original}
    assert client.rerank.await_args.kwargs["documents"] == [row["text"] for row in original]


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["exception", "empty", "partial", "duplicate", "negative", "out_of_range",
                                      "nan", "infinite", "bool_index", "bool_score", "string_score", "object", "none"])
async def test_remote_failure_preserves_exact_order_and_cools_down(tmp_path, monkeypatch, failure):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    original = await populate(plugin, 3)
    valid = FakeRerank.reverse("coffee", [row["text"] for row in original], 3)
    bad = {"empty": [], "partial": valid[:1], "duplicate": [valid[0]] * 3,
           "object": {"results": valid}, "none": None}
    if failure == "exception":
        client.rerank.side_effect = RuntimeError("synthetic-private-content")
    else:
        if failure not in bad:
            index = {"negative": -1, "out_of_range": 3, "bool_index": True}.get(failure, 2)
            score = {"nan": float("nan"), "infinite": float("inf"), "bool_score": True,
                     "string_score": "0.9"}.get(failure, 1.0)
            bad[failure] = [RerankResult(index, score, "ignored"), *valid[1:]]
        client.rerank.side_effect = None
        client.rerank.return_value = bad[failure]
    report = {}
    assert await plugin.search(scope(), "coffee", rerank_report=report) == original
    assert report["phase"] == "fallback"
    assert report["reason"] == ("request_failed" if failure == "exception" else "invalid_response")
    assert "synthetic-private-content" not in str(report)
    assert await plugin.search(scope(), "coffee", rerank_report=report) == original
    assert report["reason"] == "cooldown"
    assert client.rerank.await_count == 1
    plugin.reranker._retry_at = 0
    client.rerank.side_effect = client.reverse
    assert await plugin.search(scope(), "coffee") == list(reversed(original))


@pytest.mark.anyio
@pytest.mark.parametrize("selected,wrong_type", [(None, False), (None, True), ("missing", False)])
async def test_missing_or_wrong_model_falls_back(tmp_path, monkeypatch, selected, wrong_type):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "rerank_model": selected})
    client = attach_client(plugin)
    plugin.ctx.provider_mgr.get_default_rerank.return_value = object() if wrong_type else None
    original = await populate(plugin)
    report = {}
    assert await plugin.search(scope(), "coffee", rerank_report=report) == original
    assert report["reason"] == "model_missing"
    client.rerank.assert_not_awaited()


@pytest.mark.anyio
async def test_timeout_including_concurrency_wait_retains_original_order_and_releases_slot(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "rerank_timeout": 1})
    client = attach_client(plugin)
    original = await populate(plugin)
    plugin.reranker._slots = asyncio.Semaphore(0)
    report = {}
    assert await plugin.search(scope(), "coffee", rerank_report=report) == original
    assert report["reason"] == "timeout"
    client.rerank.assert_not_awaited()
    plugin.reranker._slots = asyncio.Semaphore(1)
    plugin.reranker._retry_at = 0
    cancelled = asyncio.Event()
    async def blocked(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    client.rerank.side_effect = blocked
    assert await plugin.search(scope(), "coffee", rerank_report=report) == original
    assert report["reason"] == "timeout"
    assert cancelled.is_set()
    assert not plugin.reranker._slots.locked()


@pytest.mark.anyio
async def test_external_cancellation_propagates_and_releases_slot(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    await populate(plugin)
    started = asyncio.Event()
    async def blocked(**kwargs):
        started.set()
        await asyncio.Event().wait()
    client.rerank.side_effect = blocked
    plugin.reranker._slots = asyncio.Semaphore(1)
    pending = asyncio.create_task(plugin.search(scope(), "coffee"))
    await asyncio.wait_for(started.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert not plugin.reranker._slots.locked()
    assert plugin.reranker._retry_at == 0


@pytest.mark.anyio
async def test_document_budget_and_stable_ties_preserve_original_records():
    client = FakeRerank()
    ctx = SimpleNamespace(provider_mgr=SimpleNamespace(get_default_rerank=lambda: client))
    reranker = MemoryReranker(ctx, {"rerank_enabled": True, "rerank_candidates": 100})
    rows = [{"id": str(index), "text": "x" * 10000} for index in range(101)]
    client.rerank.side_effect = lambda query, documents, top_n: [
        RerankResult(i, 0.5, "ignored") for i in reversed(range(len(documents)))
    ]
    ranked, report = await reranker.rank("query", rows)
    assert ranked == rows
    assert all(a is b for a, b in zip(ranked, rows))
    assert report["candidates"] == 100
    request = client.rerank.await_args.kwargs
    assert sum(map(len, request["documents"])) <= 60000
    assert max(map(len, request["documents"])) <= 4000
    assert request["top_n"] == 100


@pytest.mark.anyio
async def test_hybrid_reranks_fused_candidates_and_preserves_hybrid_order_on_failure(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    original = await populate(plugin)
    semantic, _ = await plugin.store.add(scope(), text="semantic candidate with no lexical match")
    plugin.vectors.enabled = True
    plugin.vectors.search = AsyncMock(return_value=[semantic, original[-1]])
    plugin.plugin_cfg["rerank_enabled"] = False
    fused = await plugin.search(scope(), "coffee")
    plugin.plugin_cfg["rerank_enabled"] = True
    assert await plugin.search(scope(), "coffee") == list(reversed(fused))
    assert semantic["text"] in client.rerank.await_args.kwargs["documents"]
    client.rerank.side_effect = RuntimeError("failed")
    assert await plugin.search(scope(), "coffee") == fused


@pytest.mark.anyio
async def test_recall_diagnostics_are_per_request_under_concurrency(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    await populate(plugin)
    started, release = asyncio.Event(), asyncio.Event()
    async def blocked(query, documents, top_n):
        started.set()
        await release.wait()
        return client.reverse(query, documents, top_n)
    client.rerank.side_effect = blocked
    pending = asyncio.create_task(plugin.recall(scope(), ["coffee"]))
    await asyncio.wait_for(started.wait(), 2)
    empty = await plugin.recall(scope(), [])
    assert empty["retrieval"]["rerank"]["phase"] == "skipped"
    release.set()
    applied = await pending
    assert applied["retrieval"]["rerank"]["phase"] == "applied"
    assert empty["retrieval"]["rerank"]["phase"] == "skipped"


@pytest.mark.anyio
async def test_rerank_api_requires_auth_before_any_paid_request(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True})
    client = attach_client(plugin)
    await populate(plugin)
    plugin_id = "kira_plugin_simple_memory"
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin, is_plugin_enabled=lambda _: True,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        path = f"/api/plugin/{plugin_id}/memory/recall"
        assert (await http.post(path, json={"messages": ["coffee"]})).status_code == 401
        client.rerank.assert_not_awaited()
        app.dependency_overrides[require_auth] = lambda: {"sub": "operator"}
        assert (await http.post(path, json={"messages": "invalid"})).status_code == 400
        client.rerank.assert_not_awaited()
        response = await http.post(path, json={"messages": ["coffee"]})
        assert response.status_code == 200
        assert response.json()["retrieval"]["rerank"]["phase"] == "applied"
        assert client.rerank.await_count == 1


@pytest.mark.anyio
async def test_concurrent_requests_are_bounded_to_two_calls():
    client = FakeRerank()
    reranker = MemoryReranker(SimpleNamespace(provider_mgr=SimpleNamespace(get_default_rerank=lambda: client)),
                              {"rerank_enabled": True})
    active, peak = 0, 0
    started, release = asyncio.Event(), asyncio.Event()
    async def blocked(query, documents, top_n):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            started.set()
        try:
            await release.wait()
            return client.reverse(query, documents, top_n)
        finally:
            active -= 1
    client.rerank.side_effect = blocked
    rows = [{"text": str(i)} for i in range(3)]
    tasks = [asyncio.create_task(reranker.rank("query", rows)) for _ in range(3)]
    try:
        await asyncio.wait_for(started.wait(), 2)
        assert client.rerank.await_count == 2
        release.set()
        results = await asyncio.gather(*tasks)
        assert all(report["phase"] == "applied" for _, report in results)
        assert client.rerank.await_count == 3
        assert peak == 2
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_failure_preserves_paginated_result_and_core_context(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"rerank_enabled": True, "rerank_candidates": 4})
    client = attach_client(plugin)
    original = await populate(plugin, 9)
    client.rerank.side_effect = RuntimeError("failed")
    assert await plugin.search(scope(), "coffee", limit=3, offset=2) == original[2:5]
    core, _ = await plugin.store.add(scope(), text="Always remember this", core=True)
    result = await plugin.recall(scope(), ["coffee"])
    assert result["core"][0]["id"] == core["id"]
    assert result["retrieval"]["rerank"]["phase"] == "fallback"
    assert [row["id"] for row in result["recalled"]] == [row["id"] for row in original[:6]]


@pytest.mark.parametrize("value,expected", [(None, 30), (True, 30), ("50", 30), (-1, 2), (10000, 100), (20, 20)])
def test_candidate_setting_is_bounded_and_rejects_non_integers(value, expected):
    reranker = MemoryReranker(None, {"rerank_candidates": value})
    assert reranker.candidate_limit == expected
