"""Regressions for opt-in remote embeddings, isolation, and index lifecycle."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.plugin.builtin_plugins.memory import vector as module
from core.plugin.builtin_plugins.memory.vector import VectorMemory
from core.provider import EmbeddingModelClient, ModelInfo, ModelType
from tests.test_builtin_memory import event, plugin_at, scope


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def np():
    return pytest.importorskip("numpy")


class FakeEmbedding(EmbeddingModelClient):
    def __init__(self):
        super().__init__(ModelInfo(
            ModelType.EMBEDDING, "embedding-id", "provider-id", "Remote provider",
            provider_config={"api_key": "synthetic-secret", "base_url": "https://embedding.test"},
            model_name="semantic-test",
        ))
        self.embed = AsyncMock(side_effect=self.vectors)

    @staticmethod
    def vectors(texts):
        vectors = []
        for text in texts:
            if any(word in text for word in ("汽车", "车子", "vehicle", "car")):
                vectors.append([1.0, 0.0, 0.0])
            elif any(word in text for word in ("coffee", "咖啡", "latte")):
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


async def vector_plugin(tmp_path, monkeypatch, np, **config):
    plugin = await plugin_at(tmp_path, monkeypatch)
    client = FakeEmbedding()
    plugin.ctx.get_embedding_client = Mock(return_value=client)
    plugin.plugin_cfg.update({"vector_enabled": True, **config})
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    return plugin, client


@pytest.mark.anyio
async def test_disabled_memory_never_imports_numeric_dependency_or_calls_model(tmp_path, monkeypatch):
    loader = Mock(side_effect=AssertionError("Numeric dependency must remain lazy"))
    monkeypatch.setattr(module, "load_numpy", loader)
    monkeypatch.setattr(module, "dependency_available", lambda: False)
    installer = AsyncMock()
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.ctx.get_embedding_client = Mock(side_effect=AssertionError("Must not resolve model"))
    await plugin.memory_add(event(), text="coffee")
    assert (await plugin.recall(scope(), ["coffee"]))["recalled"]
    assert json.loads(await plugin.memory_search(event(), query="coffee"))["records"]
    assert (await plugin.api_vector_status())["phase"] == "disabled"
    await plugin.api_vector_install()
    await plugin.api_vector_rebuild()
    loader.assert_not_called()
    installer.assert_not_called()
    plugin.ctx.get_embedding_client.assert_not_called()
    assert plugin.vectors._task is None
    async with plugin.store.connection() as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE name='memory_vectors'") as cursor:
            assert await cursor.fetchone() is None
    await plugin.terminate()


@pytest.mark.anyio
async def test_missing_dependency_sync_falls_back_without_repeated_installs(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.plugin_cfg["vector_enabled"] = True
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    monkeypatch.setattr(module, "load_numpy", Mock(side_effect=ModuleNotFoundError("numpy")))
    installer = AsyncMock()
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    await plugin.vectors._sync()
    assert plugin.vectors.phase == "dependency_missing"
    assert json.loads(await plugin.memory_add(event(), text="coffee"))["ok"]
    assert (await plugin.recall(scope(), ["coffee"]))["recalled"]
    installer.assert_not_called()


@pytest.mark.anyio
async def test_missing_model_falls_back_and_uses_existing_model_selection(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np, embedding_model="remote:model")
    plugin.ctx.get_embedding_client.return_value = None
    await plugin.vectors._sync()
    assert plugin.vectors.phase == "model_missing"
    await plugin.store.add(scope(), text="coffee")
    assert (await plugin.search(scope(), "coffee"))[0]["text"] == "coffee"
    plugin.ctx.get_embedding_client.return_value = client
    await plugin.vectors._sync()
    plugin.ctx.get_embedding_client.assert_called_with("remote:model", default=False)
    assert plugin.vectors.ready


@pytest.mark.anyio
async def test_paraphrase_recalls_through_tools_preview_and_runtime(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="我最近买了一辆汽车")
    assert not await plugin.store.search(scope(), "车子")
    await plugin.vectors._sync()
    plugin.ctx.get_embedding_client.assert_called_with("", default=True)
    assert (await plugin.search(scope(), "车子"))[0]["id"] == row["id"]
    assert json.loads(await plugin.memory_search(event(), query="车子"))["records"][0]["id"] == row["id"]
    result = await plugin.api_recall({"messages": ["车子"]})
    assert result["recalled"][0]["id"] == row["id"]
    assert result["retrieval"]["mode"] == "hybrid"
    assert (await plugin.recall(scope(), ["车子"]))["recalled"][0]["id"] == row["id"]
    assert client.embed.await_count == 5


@pytest.mark.anyio
async def test_semantic_scope_status_expiry_and_group_speaker_filters(tmp_path, monkeypatch, np):
    plugin, _ = await vector_plugin(tmp_path, monkeypatch, np)
    own, _ = await plugin.store.add(scope(), text="own 汽车")
    for context in (scope(persona="other"), scope(adapter="other"),
                    scope(target="bob", users=("bob",))):
        await plugin.store.add(context, text="hidden 汽车")
    expired, _ = await plugin.store.add(scope(), text="expired 汽车", expires_at=1)
    completed, _ = await plugin.store.add(scope(), text="completed 汽车")
    await plugin.store.update(scope(), completed["id"], 1, text="completed 汽车", status="completed")
    group_context = scope(session="gm", target="group", users=("alice", "bob"))
    group, _ = await plugin.store.add(group_context, text="shared 汽车", owner_type="group",
                                      source_message_id="msg-0")
    alice, _ = await plugin.store.add(group_context, text="alice 汽车", user_id="alice",
                                      source_message_id="msg-0")
    bob, _ = await plugin.store.add(group_context, text="bob 汽车", user_id="bob",
                                    source_message_id="msg-1")
    await plugin.vectors._sync()
    assert {row["id"] for row in await plugin.search(scope(), "车子")} == {own["id"]}
    assert {row["id"] for row in await plugin.search(scope(), "车子", include_inactive=True)} == {
        own["id"], expired["id"], completed["id"],
    }
    assert {row["id"] for row in await plugin.search(
        scope(session="gm", target="group"), "车子",
    )} == {group["id"], alice["id"]}
    assert {row["id"] for row in await plugin.search(
        scope(session="gm", target="group", users=("bob",)), "车子",
    )} == {group["id"], bob["id"]}
    preview = await plugin.api_recall({"session_id": "test:gm:group", "messages": ["车子"]})
    assert {row["id"] for row in preview["recalled"]} == {group["id"], alice["id"], bob["id"]}
    assert not await plugin.search(scope(), "车子", kind="procedural")


@pytest.mark.anyio
async def test_stale_vectors_are_excluded_and_edit_delete_refresh_index(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    await plugin.store.update(scope(), row["id"], 1, text="coffee")
    assert not await plugin.search(scope(), "车子")
    await plugin.vectors._sync()
    assert (await plugin.search(scope(), "latte"))[0]["id"] == row["id"]
    await plugin.api_record_update(row["id"], {"revision": 2, "text": "汽车"})
    assert not plugin.vectors.ready
    await plugin.vectors._sync()
    assert (await plugin.search(scope(), "车子"))[0]["id"] == row["id"]
    await plugin.store.remove(scope(), row["id"], 3)
    assert not await plugin.search(scope(), "车子")
    async with plugin.store.connection() as db:
        async with db.execute("SELECT COUNT(*) FROM memory_vectors") as cursor:
            assert (await cursor.fetchone())[0] == 0
    assert client.embed.await_count >= 3


@pytest.mark.anyio
async def test_index_publish_rejects_edit_or_delete_during_embedding(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    async def edit_during_request(texts):
        if texts == ["汽车"]:
            await plugin.store.update(scope(), row["id"], 1, text="coffee")
        return client.vectors(texts)
    client.embed.side_effect = edit_during_request
    await plugin.vectors._sync()
    assert plugin.vectors.ready
    assert not await plugin.search(scope(), "车子")
    assert (await plugin.search(scope(), "latte"))[0]["revision"] == 2
    new, _ = await plugin.store.add(scope(), text="new 汽车")
    async def delete_during_request(texts):
        await plugin.store.remove(scope(), new["id"], 1)
        return client.vectors(texts)
    client.embed.side_effect = delete_during_request
    await plugin.vectors._sync()
    assert (await plugin.vectors.store.progress()) == {"indexed": 1, "total": 1}


@pytest.mark.anyio
async def test_dimension_mismatch_blocks_until_explicit_manual_rebuild(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    index_id = plugin.vectors.index_id
    client.model.model_name = "alias-for-the-same-model"
    assert (await plugin.search(scope(), "车子"))[0]["id"] == row["id"]
    await plugin.vectors._sync()
    assert plugin.vectors.index_id == index_id
    client.embed.side_effect = lambda texts: [[1, 0] for _ in texts]
    assert not await plugin.search(scope(), "车子")
    assert not plugin.vectors.ready and plugin.vectors.phase == "rebuild_required"
    assert not plugin.vectors._rebuild
    calls = client.embed.await_count
    await plugin.vectors._sync()
    await plugin.search(scope(), "车子")
    assert client.embed.await_count == calls
    status = await plugin.api_vector_status()
    assert status["index_dimensions"] == 3 and status["received_dimensions"] == 2
    assert "synthetic-secret" not in json.dumps(status)
    # The pause survives settings changes, reloads and additional memory writes.
    await plugin.store.add(scope(), text="another 汽车")
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    await plugin.vectors._sync()
    assert plugin.vectors.phase == "rebuild_required" and client.embed.await_count == calls
    assert (await plugin.vectors.store.progress()) == {"indexed": 1, "total": 2}
    monkeypatch.setattr(plugin.vectors, "start", Mock())
    await plugin.api_vector_rebuild()
    await plugin.vectors._sync()
    assert plugin.vectors.ready and plugin.vectors.dimension == 2
    assert plugin.vectors.index_id != index_id
    assert {item["id"] for item in await plugin.search(scope(), "车子")} >= {row["id"]}

@pytest.mark.anyio
async def test_remote_failure_and_timeout_fall_back_with_cooldown(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee")
    await plugin.vectors._sync()
    async def hanging_request(texts):
        await asyncio.Event().wait()
    client.embed.side_effect = hanging_request
    monkeypatch.setattr(plugin.vectors, "number", lambda *args: 0.02)
    result = await asyncio.wait_for(plugin.recall(scope(), ["coffee"]), 1)
    assert result["recalled"][0]["id"] == row["id"]
    assert result["retrieval"]["mode"] == "keyword"
    assert plugin.vectors.reason == "embedding_failed"
    calls = client.embed.await_count
    await plugin.search(scope(), "coffee")
    await plugin.vectors._sync()
    assert client.embed.await_count == calls


@pytest.mark.anyio
@pytest.mark.parametrize("values", [[], [[0, 0]], [[float("nan"), 1]], [[float("inf"), 1]],
                                   [[1, 0], [1, 0]], [[1], [1, 0]]])
async def test_malformed_remote_vectors_preserve_keyword_retrieval(tmp_path, monkeypatch, np, values):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    await plugin.store.add(scope(), text="coffee")
    await plugin.vectors._sync()
    client.embed.side_effect = None
    client.embed.return_value = values
    assert (await plugin.search(scope(), "coffee"))[0]["text"] == "coffee"
    assert plugin.vectors.phase == "degraded"


@pytest.mark.anyio
async def test_semantic_pagination_and_minimum_similarity(tmp_path, monkeypatch, np):
    plugin, _ = await vector_plugin(tmp_path, monkeypatch, np)
    expected = set()
    for index in range(7):
        row, _ = await plugin.store.add(scope(), text=f"汽车 {index}")
        expected.add(row["id"])
    await plugin.store.add(scope(), text="coffee")
    await plugin.vectors._sync()
    pages = [await plugin.search(scope(), "车子", limit=2, offset=offset) for offset in (0, 2, 4, 6)]
    found = [row["id"] for page in pages for row in page]
    assert len(found) == len(set(found)) == 7 and set(found) == expected
    # A keyword hit also returned by semantic search is emitted only once.
    assert len(await plugin.search(scope(), "汽车", limit=50)) == 7


@pytest.mark.anyio
async def test_index_batches_are_bounded_and_shutdown_cancels_remote_request(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    for index in range(19):
        await plugin.store.add(scope(), text=f"汽车 {index}")
    await plugin.vectors._sync()
    assert [len(call.args[0]) for call in client.embed.await_args_list] == [16, 3]
    assert plugin.vectors.indexed == plugin.vectors.total == 19
    await plugin.store.add(scope(), text="another 汽车")
    entered = asyncio.Event()
    async def blocked(texts):
        entered.set()
        await asyncio.Event().wait()
    client.embed.side_effect = blocked
    plugin.vectors.start()
    await asyncio.wait_for(entered.wait(), 2)
    # The remote request is outside a database write transaction.
    await asyncio.wait_for(plugin.store.add(scope(), text="still writable"), 1)
    await asyncio.wait_for(plugin.terminate(), 1)
    assert plugin.vectors._task.done() and not plugin.vectors.ready


@pytest.mark.anyio
async def test_manual_dependency_install_is_deduplicated_and_restarts_worker(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.plugin_cfg["vector_enabled"] = True
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    available = False
    monkeypatch.setattr(module, "dependency_available", lambda: available)
    entered, release = asyncio.Event(), asyncio.Event()
    async def install(directory, pypi_mirror=None):
        nonlocal available
        assert directory.name == "vector_dependencies"
        assert (directory / "requirements.txt").read_text().strip() == "numpy>=1.24,<3"
        entered.set()
        await release.wait()
        available = True
        return []
    installer = AsyncMock(side_effect=install)
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    monkeypatch.setattr(plugin.vectors, "start", Mock())
    result = await plugin.api_vector_install()
    assert result["phase"] == "installing"
    await asyncio.wait_for(entered.wait(), 1)
    await plugin.api_vector_install()
    assert installer.await_count == 1
    release.set()
    await plugin.vectors._install_task
    plugin.vectors.start.assert_called_once()
    assert (await plugin.api_vector_status())["dependency_available"]
    await plugin.terminate()


@pytest.mark.anyio
async def test_install_failure_is_sanitized(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.vectors.enabled = True
    monkeypatch.setattr(module, "dependency_available", lambda: False)
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements",
                        AsyncMock(return_value=["synthetic-secret provider-token"]))
    await plugin.api_vector_install()
    await plugin.vectors._install_task
    status = await plugin.api_vector_status()
    assert status["reason"] == "install_failed" and "synthetic-secret" not in json.dumps(status)
    await plugin.terminate()


@pytest.mark.anyio
async def test_vector_apis_require_auth_and_enabled_plugin(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient
    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch)
    enabled = True
    plugin_id = "kira_plugin_simple_memory"
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin, is_plugin_enabled=lambda _: enabled,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        for method, endpoint in (("GET", "status"), ("POST", "install"), ("POST", "rebuild")):
            path = f"/api/plugin/{plugin_id}/memory/vector/{endpoint}"
            assert (await client.request(method, path)).status_code == 401
            app.dependency_overrides[require_auth] = lambda: {"sub": "operator"}
            response = await client.request(method, path)
            assert response.status_code == 200 and response.json()["enabled"] is False
            enabled = False
            assert (await client.request(method, path)).status_code == 404
            enabled = True
            plugin._ready = False
            assert (await client.request(method, path)).status_code == 503
            plugin._ready = True
            app.dependency_overrides.clear()

@pytest.mark.anyio
async def test_manual_rebuild_during_query_rejects_previous_index_result(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    original = plugin.vectors.index_id
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_query(texts):
        if texts == ["车子"]:
            entered.set()
            await release.wait()
        return client.vectors(texts)

    client.embed.side_effect = delayed_query
    query = asyncio.create_task(plugin.search(scope(), "车子"))
    await asyncio.wait_for(entered.wait(), 1)
    client.model.model_name = "new-embedding-space"
    monkeypatch.setattr(plugin.vectors, "start", Mock())
    await plugin.api_vector_rebuild()
    await plugin.vectors._sync()
    assert plugin.vectors.ready and plugin.vectors.index_id != original
    release.set()
    assert not await query
    assert plugin.vectors.ready


@pytest.mark.anyio
async def test_background_start_and_resume_reuse_existing_vectors(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    await plugin.store.add(scope(), text="汽车")
    plugin.vectors.start()

    async def ready():
        while not plugin.vectors.ready:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(ready(), 2)
    assert client.embed.await_count == 1
    await plugin.vectors.close()
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    await plugin.vectors._sync()
    assert plugin.vectors.ready and client.embed.await_count == 1
    assert (await plugin.search(scope(), "车子"))[0]["text"] == "汽车"
    await plugin.terminate()


@pytest.mark.anyio
async def test_same_model_uses_new_provider_without_reembedding_memory(tmp_path, monkeypatch, np):
    plugin, first = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    index_id = plugin.vectors.index_id
    second = FakeEmbedding()
    second.model.model_name = "different-channel-alias"
    second.model.provider_id = "another-provider"
    second.model.provider_name = "Another channel"
    second.model.model_id = "another-local-model-id"
    second.model.provider_config = {
        "api_key": "another-synthetic-secret", "base_url": "https://other-channel.test",
        "section_advanced": {"headers": {"X-Channel": "second"}},
    }
    second.model.model_config = {
        "embedding": {"timeout": 120, "slow_request_threshold": 10}, "dimensions": None,
    }
    plugin.ctx.get_embedding_client.return_value = second
    assert (await plugin.search(scope(), "车子"))[0]["id"] == row["id"]
    assert plugin.vectors.ready and first.embed.await_count == 1
    assert [call.args[0] for call in second.embed.await_args_list] == [["车子"]]
    # Saving a new provider selection recreates the plugin, but persisted vectors remain reusable.
    await plugin.vectors.close()
    plugin.plugin_cfg["embedding_model"] = "another-provider:another-local-model-id"
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    await plugin.vectors._sync()
    assert plugin.vectors.ready and plugin.vectors.index_id == index_id
    assert second.embed.await_count == 1
    plugin.ctx.get_embedding_client.assert_called_with(
        "another-provider:another-local-model-id", default=False,
    )


@pytest.mark.anyio
async def test_same_model_provider_switch_during_query_keeps_result_valid(tmp_path, monkeypatch, np):
    plugin, first = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_query(texts):
        entered.set()
        await release.wait()
        return first.vectors(texts)

    first.embed.side_effect = delayed_query
    query = asyncio.create_task(plugin.search(scope(), "车子"))
    await asyncio.wait_for(entered.wait(), 1)
    second = FakeEmbedding()
    second.model.provider_id = "second-channel"
    second.model.model_id = "second-reference"
    plugin.ctx.get_embedding_client.return_value = second
    await plugin.vectors._sync()
    release.set()
    assert (await query)[0]["id"] == row["id"]
    assert plugin.vectors.ready
    second.embed.assert_not_awaited()


@pytest.mark.anyio
async def test_incremental_dimension_mismatch_preserves_index_and_stops_background_calls(tmp_path, monkeypatch, np):
    plugin, first = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    original = plugin.vectors.index_id
    second = FakeEmbedding()
    second.model.provider_id = "second-channel"
    second.model.model_name = "unrelated-alias"
    second.model.model_config = {"dimensions": 2}
    second.embed.side_effect = lambda texts: [[1, 0] for _ in texts]
    plugin.ctx.get_embedding_client.return_value = second
    # A configuration change alone never re-embeds stored memories.
    await plugin.vectors._sync()
    assert plugin.vectors.ready and plugin.vectors.index_id == original
    second.embed.assert_not_awaited()
    await plugin.store.add(scope(), text="new 汽车")
    await plugin.vectors._sync()
    assert plugin.vectors.phase == "rebuild_required" and plugin.vectors.index_id == original
    assert [call.args[0] for call in second.embed.await_args_list] == [["new 汽车"]]
    state = await plugin.vectors.store.state()
    assert state["dimensions"] == 3 and state["rebuild_required"]
    assert (await plugin.vectors.store.progress()) == {"indexed": 1, "total": 2}
    for _ in range(3):
        plugin.vectors.changed()
        await plugin.vectors._sync()
    assert second.embed.await_count == 1
    assert (await plugin.store.admin_get(row["id"]))["text"] == "汽车"


@pytest.mark.anyio
async def test_existing_vectors_are_adopted_without_model_signature_rebuild(tmp_path, monkeypatch, np):
    from core.plugin.builtin_plugins.memory.vector_store import INDEX_STATE_KEY

    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    calls = client.embed.await_count
    async with plugin.store.connection(write=True) as db:
        await db.execute("DELETE FROM memory_meta WHERE key=?", (INDEX_STATE_KEY,))
        await db.execute("UPDATE memory_vectors SET fingerprint='unrelated-model-signature'")
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    client.model.model_name = "another-name-for-the-same-model"
    await plugin.vectors._sync()
    assert plugin.vectors.ready and plugin.vectors.dimension == 3
    assert client.embed.await_count == calls
    assert (await plugin.search(scope(), "车子"))[0]["id"] == row["id"]


@pytest.mark.anyio
async def test_pending_batch_cannot_publish_after_manual_index_reset(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    old_id = plugin.vectors.index_id
    await plugin.store.add(scope(), text="new 汽车")
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed_batch(texts):
        entered.set()
        await release.wait()
        return client.vectors(texts)

    client.embed.side_effect = delayed_batch
    task = asyncio.create_task(plugin.vectors._sync())
    await asyncio.wait_for(entered.wait(), 1)
    state = await plugin.vectors.store.reset()
    assert state["id"] != old_id
    release.set()
    await task
    assert (await plugin.vectors.store.progress()) == {"indexed": 0, "total": 2}


@pytest.mark.anyio
async def test_operator_delete_cascades_vectors_without_reembedding_other_memories(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    removed, _ = await plugin.store.add(scope(), text="coffee to delete")
    kept, _ = await plugin.store.add(scope(persona="other"), text="keep vehicle")
    await plugin.vectors._sync()
    calls = client.embed.await_count
    index_id = plugin.vectors.index_id
    await plugin.api_record_remove(removed["id"], 1)
    async with plugin.store.connection() as db:
        async with db.execute("SELECT memory_id FROM memory_vectors") as cursor:
            assert {row[0] for row in await cursor.fetchall()} == {kept["id"]}
    await plugin.vectors._sync()
    assert plugin.vectors.index_id == index_id
    assert plugin.vectors.indexed == 1 and plugin.vectors.ready
    assert client.embed.await_count == calls
    assert not await plugin.search(scope(), "latte")
    assert (await plugin.search(scope(persona="other"), "car"))[0]["id"] == kept["id"]
    await plugin.terminate()


async def indexed_vector(plugin, memory_id):
    async with plugin.store.connection() as db:
        async with db.execute("SELECT * FROM memory_vectors WHERE memory_id=?", (memory_id,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None


@pytest.mark.anyio
@pytest.mark.parametrize("entry", ["tool", "webui"])
@pytest.mark.parametrize("changes", [
    {"importance": 5}, {"core": True}, {"kind": "episodic"}, {"status": "completed"},
    {"expires_at": 2100000000}, {"expires_at": None}, {}, {"text": "  coffee preference \n"},
])
async def test_metadata_edits_reuse_current_vector_and_keep_retrieval_ready(tmp_path, monkeypatch, np, entry, changes):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference", expires_at=2000000000)
    await plugin.vectors._sync()
    before = await indexed_vector(plugin, row["id"])
    payload = {"revision": 1, "text": row["text"], **changes}
    if entry == "webui":
        updated = await plugin.api_record_update(row["id"], payload)
        assert updated["revision"] == 2
    else:
        if payload.get("expires_at", 1) is None:
            payload["clear_expiry"] = True
        result = json.loads(await plugin.memory_update(event(), row["id"], **payload))
        assert result["ok"] and result["revision"] == 2
    assert plugin.vectors.ready and plugin.vectors.phase == "ready"
    after = await indexed_vector(plugin, row["id"])
    assert after == {**before, "revision": 2}
    assert await plugin.vectors.store.pending() == []
    await plugin.vectors._sync()
    assert client.embed.await_count == 1
    assert plugin.vectors.index_id == before["fingerprint"]
    assert (await plugin.store.admin_get(row["id"]))["text"] == row["text"]
    await plugin.terminate()


@pytest.mark.anyio
async def test_source_message_change_does_not_reembed_unchanged_text(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    turn = event()
    turn.messages[0].message_id = "new-source"
    result = json.loads(await plugin.memory_update(turn, row["id"], 1, row["text"]))
    assert result["ok"]
    assert (await plugin.store.admin_get(row["id"]))["source_message_id"] == "new-source"
    assert plugin.vectors.ready
    await plugin.vectors._sync()
    assert client.embed.await_count == 1
    await plugin.terminate()


@pytest.mark.anyio
@pytest.mark.parametrize("entry", ["tool", "webui"])
async def test_metadata_edits_during_embedding_publish_latest_revision_without_another_call(tmp_path, monkeypatch, np, entry):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")

    async def edit_metadata(texts):
        for revision, changes in ((1, {"core": True}), (2, {"importance": 5})):
            payload = {"revision": revision, "text": row["text"], **changes}
            if entry == "webui":
                await plugin.api_record_update(row["id"], payload)
            else:
                result = json.loads(await plugin.memory_update(event(), row["id"], **payload))
                assert result["ok"]
        return client.vectors(texts)

    client.embed.side_effect = edit_metadata
    await plugin.vectors._sync()
    assert client.embed.await_count == 1
    assert plugin.vectors.ready and await plugin.vectors.store.pending() == []
    assert (await indexed_vector(plugin, row["id"]))["revision"] == 3
    current = await plugin.store.admin_get(row["id"])
    assert current["revision"] == 3 and current["core"] == 1 and current["importance"] == 5
    await plugin.terminate()


@pytest.mark.anyio
async def test_metadata_edit_never_promotes_a_vector_for_previous_text(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="汽车")
    await plugin.vectors._sync()
    old_vector = await indexed_vector(plugin, row["id"])
    await plugin.api_record_update(row["id"], {"revision": 1, "text": "coffee"})
    await plugin.api_record_update(row["id"], {"revision": 2, "text": "coffee", "importance": 5})
    assert await indexed_vector(plugin, row["id"]) == old_vector
    assert (await plugin.vectors.store.progress()) == {"indexed": 0, "total": 1}
    assert not plugin.vectors.ready
    await plugin.vectors._sync()
    assert client.embed.await_count == 2
    current = await indexed_vector(plugin, row["id"])
    assert current["revision"] == 3 and current["vector"] != old_vector["vector"]
    await plugin.terminate()


@pytest.mark.anyio
async def test_metadata_update_and_vector_revision_roll_back_together(tmp_path, monkeypatch, np):
    from core.plugin.builtin_plugins.memory.vector_store import VectorStore

    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    old_vector = await indexed_vector(plugin, row["id"])
    advance = VectorStore.advance_revision

    async def fail_after_advancing(db, memory_id, revision):
        await advance(db, memory_id, revision)
        raise RuntimeError("synthetic rollback")

    monkeypatch.setattr(VectorStore, "advance_revision", staticmethod(fail_after_advancing))
    with pytest.raises(RuntimeError, match="synthetic rollback"):
        await plugin.store.admin_update(row["id"], 1, text=row["text"], importance=5)
    current = await plugin.store.admin_get(row["id"])
    assert current["revision"] == 1 and current["importance"] == 3
    assert await indexed_vector(plugin, row["id"]) == old_vector
    assert client.embed.await_count == 1
    await plugin.terminate()


@pytest.mark.anyio
async def test_metadata_edit_without_vector_table_keeps_optional_feature_uninitialized(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.ctx.get_embedding_client = Mock(side_effect=AssertionError("Embedding must remain disabled"))
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "core": True})
    async with plugin.store.connection() as db:
        async with db.execute("SELECT name FROM sqlite_master WHERE name='memory_vectors'") as cursor:
            assert await cursor.fetchone() is None
    plugin.ctx.get_embedding_client.assert_not_called()
    await plugin.terminate()


@pytest.mark.anyio
async def test_cached_vector_stays_current_while_feature_is_disabled(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    original = await indexed_vector(plugin, row["id"])
    plugin.plugin_cfg["vector_enabled"] = False
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "core": True})
    assert await indexed_vector(plugin, row["id"]) == {**original, "revision": 2}
    plugin.plugin_cfg["vector_enabled"] = True
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    plugin.vectors.np = np
    await plugin.vectors._sync()
    assert plugin.vectors.ready and client.embed.await_count == 1
    await plugin.terminate()


@pytest.mark.anyio
async def test_optional_index_check_failure_does_not_fail_committed_metadata_edit(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    monkeypatch.setattr(plugin.vectors.store, "is_current", AsyncMock(side_effect=OSError("synthetic index check failure")))
    updated = await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "importance": 5})
    assert updated["revision"] == 2 and updated["importance"] == 5
    assert not plugin.vectors.ready
    await plugin.vectors._sync()
    assert plugin.vectors.ready and client.embed.await_count == 1
    await plugin.terminate()


@pytest.mark.anyio
@pytest.mark.parametrize("text", ["COFFEE preference", "coffee  preference"])
async def test_actual_text_changes_reembed_even_when_normalized_text_matches(tmp_path, monkeypatch, np, text):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    updated = await plugin.api_record_update(row["id"], {"revision": 1, "text": text})
    assert updated["text"] == text
    assert (await plugin.store.admin_get(row["id"]))["normalized"] == row["normalized"]
    assert not plugin.vectors.ready
    await plugin.vectors._sync()
    assert client.embed.await_count == 2
    assert (await indexed_vector(plugin, row["id"]))["revision"] == 2
    await plugin.terminate()


@pytest.mark.anyio
async def test_metadata_edit_still_rejects_outdated_revisions(tmp_path, monkeypatch, np):
    from fastapi import HTTPException

    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "core": True})
    with pytest.raises(HTTPException) as conflict:
        await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "importance": 5})
    assert conflict.value.status_code == 400 and conflict.value.detail == "conflict"
    result = json.loads(await plugin.memory_update(event(), row["id"], 1, row["text"], importance=5))
    assert result["ok"] is False
    current = await plugin.store.admin_get(row["id"])
    assert current["revision"] == 2 and current["importance"] == 3
    assert (await indexed_vector(plugin, row["id"]))["revision"] == 2
    assert plugin.vectors.ready and client.embed.await_count == 1
    await plugin.terminate()


@pytest.mark.anyio
async def test_metadata_edit_preserves_dimension_mismatch_pause_and_requires_manual_rebuild(tmp_path, monkeypatch, np):
    plugin, client = await vector_plugin(tmp_path, monkeypatch, np)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    await plugin.vectors._sync()
    index_id = plugin.vectors.index_id
    client.embed.side_effect = lambda texts: [[1, 0] for _ in texts]
    await plugin.search(scope(), "latte")
    assert plugin.vectors.phase == "rebuild_required"
    calls = client.embed.await_count
    await plugin.api_record_update(row["id"], {"revision": 1, "text": row["text"], "core": True})
    await plugin.vectors._sync()
    assert plugin.vectors.phase == "rebuild_required" and not plugin.vectors.ready
    assert not plugin.vectors._rebuild and plugin.vectors.index_id == index_id
    assert (await indexed_vector(plugin, row["id"]))["revision"] == 2
    assert client.embed.await_count == calls
    await plugin.terminate()


async def wait_vector_phase(vectors, phase):
    async def wait():
        while vectors.phase != phase:
            if vectors._task.done():
                vectors._task.result()
            await asyncio.sleep(0.01)
    await asyncio.wait_for(wait(), 3)


@pytest.mark.anyio
async def test_startup_auto_installs_missing_numpy_and_resumes_indexing(tmp_path, monkeypatch, np):
    plugin = await plugin_at(tmp_path, monkeypatch)
    row, _ = await plugin.store.add(scope(), text="coffee preference")
    plugin.plugin_cfg["vector_enabled"] = True
    plugin.vectors = VectorMemory(plugin.store, plugin.ctx, plugin.plugin_cfg)
    client = FakeEmbedding()
    plugin.ctx.get_embedding_client = Mock(return_value=client)
    plugin.ctx.config = {"network": {"pypi_mirror": "https://mirror.example/simple"}}
    available = False
    entered, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(module, "dependency_available", lambda: available)

    def load():
        if not available:
            raise ModuleNotFoundError("numpy")
        return np

    monkeypatch.setattr(module, "load_numpy", load)

    async def install(directory, pypi_mirror=None):
        nonlocal available
        assert directory.name == "vector_dependencies"
        assert pypi_mirror == "https://mirror.example/simple"
        entered.set()
        await release.wait()
        available = True
        return []

    installer = AsyncMock(side_effect=install)
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    try:
        await plugin.initialize()
        await asyncio.wait_for(entered.wait(), 2)
        assert (await plugin.api_vector_status())["phase"] == "installing"
        # A manual request and repeated starts must share the startup installation.
        await plugin.api_vector_install()
        plugin.vectors.start()
        installer.assert_awaited_once()
        assert (await plugin.recall(scope(), ["coffee"]))["recalled"][0]["id"] == row["id"]
        client.embed.assert_not_awaited()
        release.set()
        await wait_vector_phase(plugin.vectors, "ready")
        assert plugin.vectors.ready and plugin.vectors.indexed == 1
        assert plugin.vectors._install_task.done()
        installer.assert_awaited_once()
        assert (await plugin.search(scope(), "latte"))[0]["id"] == row["id"]
    finally:
        await plugin.terminate()


@pytest.mark.anyio
async def test_startup_uses_existing_numpy_without_installing(tmp_path, monkeypatch, np):
    monkeypatch.setattr(module, "dependency_available", lambda: True)
    monkeypatch.setattr(module, "load_numpy", lambda: np)
    installer = AsyncMock()
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"vector_enabled": True})
    plugin.ctx.get_embedding_client = Mock(return_value=FakeEmbedding())
    try:
        await wait_vector_phase(plugin.vectors, "ready")
        installer.assert_not_awaited()
        assert plugin.vectors._install_task is None
    finally:
        await plugin.terminate()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["warnings", "exception", "still_missing"])
async def test_startup_install_failure_preserves_keyword_recall_and_allows_manual_retry(
        tmp_path, monkeypatch, np, failure):
    available = False
    monkeypatch.setattr(module, "dependency_available", lambda: available)

    def load():
        if not available:
            raise ModuleNotFoundError("numpy")
        return np

    monkeypatch.setattr(module, "load_numpy", load)
    installer = AsyncMock(
        side_effect=RuntimeError("synthetic-secret") if failure == "exception" else None,
        return_value=["synthetic-secret"] if failure == "warnings" else [],
    )
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"vector_enabled": True})
    plugin.ctx.get_embedding_client = Mock(return_value=FakeEmbedding())
    try:
        await wait_vector_phase(plugin.vectors, "dependency_missing")
        status = await plugin.api_vector_status()
        assert status["reason"] == "install_failed"
        assert "synthetic-secret" not in json.dumps(status)
        row, _ = await plugin.store.add(scope(), text="coffee preference")
        assert (await plugin.recall(scope(), ["coffee"]))["recalled"][0]["id"] == row["id"]
        # Normal worker wakeups must not create an installation retry loop.
        await plugin.vectors._sync()
        installer.assert_awaited_once()

        async def succeed(*args, **kwargs):
            nonlocal available
            available = True
            return []

        installer.side_effect = succeed
        await plugin.api_vector_install()
        await plugin.vectors._install_task
        await wait_vector_phase(plugin.vectors, "ready")
        assert installer.await_count == 2 and plugin.vectors.reason is None
    finally:
        await plugin.terminate()


@pytest.mark.anyio
async def test_shutdown_cancels_and_reaps_startup_dependency_install(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "dependency_available", lambda: False)
    entered, cancelled = asyncio.Event(), asyncio.Event()

    async def install(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    installer = AsyncMock(side_effect=install)
    monkeypatch.setattr("core.plugin.plugin_installer.install_requirements", installer)
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"vector_enabled": True})
    try:
        await asyncio.wait_for(entered.wait(), 2)
    finally:
        await asyncio.wait_for(plugin.terminate(), 2)
    assert cancelled.is_set()
    assert plugin.vectors._task.done() and plugin.vectors._install_task.done()
    assert not plugin.vectors.ready
    installer.assert_awaited_once()
