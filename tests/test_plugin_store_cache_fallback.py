import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from core.plugin import store as store_module
from core.plugin.store import extract_plugins
from webui.models import PluginStoreFetchRequest, PluginStoreItemResponse, PluginStoreSourceCreateRequest
from webui.routes.auth import require_auth
from webui.app import KiraWebUI
from webui.routes.plugins import PluginsRoutes
from webui.routes.plugin_store import PluginStoreRoutes


class FakeDatabaseService:
    def __init__(self, source):
        self.source = source

    async def get_plugin_store_source(self, source_id):
        return dict(self.source) if self.source and source_id == self.source["id"] else None

    async def list_plugin_store_sources(self):
        return [dict(self.source)] if self.source else []

    async def add_plugin_store_source(self, source_id, **values):
        self.source = {"id": source_id, "cache_file": None, **values}

    async def delete_plugin_store_source(self, source_id):
        if self.source and source_id == self.source["id"]:
            self.source = None

    async def update_plugin_store_source(self, source_id, **changes):
        if source_id == self.source["id"]:
            self.source.update(changes)


@pytest.mark.anyio
async def test_fetch_plugin_store_uses_cache_when_refresh_fails(tmp_path, monkeypatch):
    cache_dir = tmp_path / "plugin_src"
    cache_dir.mkdir()
    (cache_dir / "plugins.json").write_text(
        '{"plugins": {"cached-plugin": {"plugin_id": "cached-plugin", "display_name": "Cached Plugin"}}}',
        encoding="utf-8",
    )
    source = {
        "id": "source-1",
        "url": "https://store.example/plugins.json",
        "cache_file": "plugins.json",
        "updated_at": 0,
    }

    async def fail_fetch(url, timeout):
        raise ConnectionError("store is unavailable")

    monkeypatch.setattr(store_module, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(store_module, "get_json", fail_fetch)
    routes = PluginStoreRoutes(FastAPI(), SimpleNamespace(db_service=FakeDatabaseService(source)))
    response = Response()

    result = await routes.fetch_plugin_store(
        PluginStoreFetchRequest(source_id="source-1", force_refresh=True), response,
    )

    assert [item.id for item in result] == ["cached-plugin"]
    assert response.headers["X-Plugin-Store-Cache-Fallback"] == "true"
    assert response.headers["X-Plugin-Store-Cache-Fallback-Status"] == "422"


def test_plugin_store_error_status_uses_remote_response_status():
    error = RuntimeError("store returned an error")
    error.response = SimpleNamespace(status_code=500)

    assert PluginStoreRoutes._plugin_store_error_status(error) == 500


def test_extract_plugins_reads_nested_github_stars():
    plugins = extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "display_name": "Example",
                "github_data": {"stars": 12},
            },
        },
    })

    assert plugins[0].stars == 12


def test_extract_plugins_preserves_store_icon_urls():
    plugins = extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "display_name": "Example",
                "icon": "https://store.example/icons/example.svg",
                "icon_dark": "https://store.example/icons/example-dark.svg",
            },
        },
    })

    assert plugins[0].icon == "https://store.example/icons/example.svg"
    assert plugins[0].icon_dark == "https://store.example/icons/example-dark.svg"


def test_extract_plugins_preserves_tags_and_core_version():
    plugins = extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "tags": ["utility", "network"],
                "core_version": ">=2.29.0",
            },
        },
    })

    assert plugins[0].tags == ["utility", "network"]
    assert plugins[0].core_version == ">=2.29.0"


def test_extract_plugins_preserves_pinned_source_fields():
    commit_sha = "a" * 40
    plugins = extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "commit_sha": f" {commit_sha.upper()} ",
                "release_tag": "v1.2.3",
            },
        },
    })

    assert plugins[0].commit_sha == commit_sha
    assert plugins[0].release_tag == "v1.2.3"


def test_extract_plugins_falls_back_to_head_for_invalid_commit_sha():
    plugins = extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "commit_sha": "v1.2.3",
            },
        },
    })

    assert plugins[0].commit_sha is None


@pytest.mark.asyncio
async def test_update_check_falls_back_to_head_for_invalid_catalog_commit_sha(tmp_path, monkeypatch):
    source = {
        "id": "source-1",
        "url": "https://store.example/plugins.json",
        "cache_file": None,
        "updated_at": 0,
        "is_current": True,
    }

    async def fetch_store(url, timeout):
        return {
            "plugins": {
                "example": {
                    "plugin_id": "example",
                    "version": "2.0.0",
                    "commit_sha": "not-a-commit",
                },
            },
        }

    plugin_manager = SimpleNamespace(
        list_plugins=lambda: [SimpleNamespace(
            builtin=False,
            hidden=False,
            status="ready",
            plugin_id="example",
            version="1.0.0",
        )],
    )
    monkeypatch.setattr(store_module, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(store_module, "get_json", fetch_store)
    routes = PluginsRoutes(
        FastAPI(),
        SimpleNamespace(plugin_manager=plugin_manager, db_service=FakeDatabaseService(source)),
    )

    result = await routes.check_plugin_updates()

    assert result[0].has_update is True
    assert result[0].commit_sha is None

@pytest.mark.parametrize("refresh_fails", [False, True])
def test_registered_store_routes_preserve_source_and_cache_lifecycle(tmp_path, monkeypatch, refresh_fails):
    monkeypatch.setattr(store_module, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(store_module.time, "time", lambda: 1000)
    database = FakeDatabaseService(None)
    raw = {"meta": {"format": 1}, "plugins": [{"plugin_id": "example", "display_name": "Example", "version": "2.0.0"}]}
    requests = []

    async def fetch(url, timeout):
        requests.append((url, timeout))
        if refresh_fails and len(requests) > 1:
            raise ConnectionError("source unavailable")
        return raw

    monkeypatch.setattr(store_module, "get_json", fetch)
    lifecycle = SimpleNamespace(db_service=database, plugin_manager=SimpleNamespace(list_plugins=lambda: []))
    app = KiraWebUI(lifecycle, dist_dir=tmp_path / "dist", disable_auth=True).get_app()
    actual = [(route.path, method) for route in app.routes if route.path.startswith("/api/plugin-store/") for method in route.methods]
    assert len(actual) == len(set(actual)) == 5
    with TestClient(app) as client:
        assert client.get("/api/plugin-store/sources").status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        created = client.post("/api/plugin-store/sources", json={"name": "Example", "url": "https://example.test/catalog"})
        assert created.status_code == 200
        source = created.json()
        source_id = source["id"]
        cache_file = source["cache_file"]
        cache_path = tmp_path / "plugin_src" / cache_file
        assert json.loads(cache_path.read_text(encoding="utf-8")) == raw
        assert client.get("/api/plugin-store/sources").json() == [source]
        assert client.post(f"/api/plugin-store/sources/{source_id}/current").json() == {"success": True}
        assert database.source["is_current"] is True
        assert len(requests) == 1

        fresh = client.post("/api/plugin-store/fetch", json={"source_id": source_id})
        assert fresh.status_code == 200
        assert fresh.json()[0]["id"] == "example"
        assert "X-Plugin-Store-Cache-Fallback" not in fresh.headers
        assert len(requests) == 1

        database.source["updated_at"] = 0
        switched = client.post(f"/api/plugin-store/sources/{source_id}/current")
        assert switched.status_code == 200
        assert switched.json() == {"success": True}
        assert database.source["updated_at"] == (0 if refresh_fails else 1000)
        assert database.source["cache_file"] == cache_file

        database.source["updated_at"] = 0
        refreshed = client.post("/api/plugin-store/fetch", json={"source_id": source_id, "force_refresh": True})
        assert refreshed.status_code == 200
        assert database.source["cache_file"] == cache_file
        assert database.source["updated_at"] == (0 if refresh_fails else 1000)
        if refresh_fails:
            assert refreshed.headers["X-Plugin-Store-Cache-Fallback"] == "true"
            assert refreshed.headers["X-Plugin-Store-Cache-Fallback-Status"] == "422"
        else:
            assert "X-Plugin-Store-Cache-Fallback" not in refreshed.headers
        assert json.loads(cache_path.read_text(encoding="utf-8")) == raw

        removed = client.delete(f"/api/plugin-store/sources/{source_id}")
        assert removed.status_code == 200
        assert removed.json() == {"success": True}
        assert not cache_path.exists()
        assert client.get("/api/plugin-store/sources").json() == []
        assert client.post("/api/plugin-store/fetch", json={"source_id": source_id}).status_code == 404
        assert client.post("/api/plugin-store/fetch", json={}).status_code == 400


@pytest.mark.asyncio
async def test_update_check_does_not_use_stale_cache_after_remote_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(store_module.time, "time", lambda: 1000)
    cache_dir = tmp_path / "plugin_src"
    cache_dir.mkdir()
    (cache_dir / "catalog.json").write_text('{"plugins": [{"plugin_id": "example", "version": "2.0.0"}]}', encoding="utf-8")
    source = {"id": "source", "url": "https://example.test/catalog", "is_current": True, "updated_at": 0, "cache_file": "catalog.json"}

    async def fail_fetch(url, timeout):
        raise ConnectionError("source unavailable")

    monkeypatch.setattr(store_module, "get_json", fail_fetch)
    manager = SimpleNamespace(list_plugins=lambda: [SimpleNamespace(
        plugin_id="example", version="1.0.0", builtin=False, hidden=False, status="ready",
    )])
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(db_service=FakeDatabaseService(source), plugin_manager=manager))
    result = await routes.check_plugin_updates()
    assert not result[0].has_update
    assert result[0].latest_version is None
    assert "source unavailable" in result[0].error
    assert source["updated_at"] == 0

@pytest.mark.asyncio
async def test_source_creation_and_selection_succeed_when_initial_fetch_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(store_module.time, "time", lambda: 1000)

    async def fail_fetch(url, timeout):
        raise ConnectionError("source unavailable")

    monkeypatch.setattr(store_module, "get_json", fail_fetch)
    database = FakeDatabaseService(None)
    routes = PluginStoreRoutes(FastAPI(), SimpleNamespace(db_service=database))
    created = await routes.create_plugin_source(
        PluginStoreSourceCreateRequest(name="Example", url="https://example.test/catalog")
    )
    assert created.cache_file is None
    assert database.source["id"] == created.id
    database.source["updated_at"] = 0
    assert await routes.set_current_source(created.id) == {"success": True}
    assert database.source["is_current"] is True
    assert database.source["updated_at"] == 0
    assert not (tmp_path / "plugin_src").exists()

@pytest.mark.parametrize("catalog_format", ["standard", "wrapped_array", "array"])
def test_extract_plugins_returns_normalized_response_models(catalog_format):
    raw = {
        "plugin_id": "canonical-id",
        "id": "legacy-id",
        "display_name": "Display Name",
        "name": "legacy-name",
        "version": None,
        "repo_url": "https://example.test/repository",
        "icon-dark": "https://example.test/dark.svg",
        "star_count": "7",
        "updatedAt": "2026-09-30",
    }
    if catalog_format == "standard":
        catalog = {"plugins": {"entry": raw, "ignored": None}}
    elif catalog_format == "wrapped_array":
        catalog = {"plugins": [raw, None]}
    else:
        catalog = [raw, None]

    items = extract_plugins(catalog)
    assert len(items) == 1
    item = items[0]
    assert isinstance(item, PluginStoreItemResponse)
    assert item.id == "canonical-id"
    assert item.name == "Display Name"
    assert item.version == ""
    assert item.repo == "https://example.test/repository"
    assert item.icon_dark == "https://example.test/dark.svg"
    assert item.stars == 7
    assert item.updated_at == "2026-09-30"
    assert item.tags == []
    assert item.locales == {}
    assert item.category_locales == {}
