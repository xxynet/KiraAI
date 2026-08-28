from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Response

import webui.routes.plugins as plugin_routes
from core.plugin.plugin_registry import PluginManager
from webui.models import PluginStoreFetchRequest
from webui.routes.plugins import PluginsRoutes


class FakeDatabaseService:
    def __init__(self, source):
        self.source = source

    async def get_plugin_store_source(self, source_id):
        return self.source if source_id == self.source["id"] else None

    async def list_plugin_store_sources(self):
        return [self.source]

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

    async def fail_fetch(url):
        raise ConnectionError("store is unavailable")

    monkeypatch.setattr(plugin_routes, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(PluginManager, "fetch_plugin_store_data", fail_fetch)
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(db_service=FakeDatabaseService(source)))
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

    assert PluginsRoutes._plugin_store_error_status(error) == 500


def test_extract_plugins_reads_nested_github_stars():
    plugins = PluginsRoutes._extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "display_name": "Example",
                "github_data": {"stars": 12},
            },
        },
    })

    assert plugins[0]["stars"] == 12


def test_extract_plugins_preserves_store_icon_urls():
    plugins = PluginsRoutes._extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "display_name": "Example",
                "icon": "https://store.example/icons/example.svg",
                "icon_dark": "https://store.example/icons/example-dark.svg",
            },
        },
    })

    assert plugins[0]["icon"] == "https://store.example/icons/example.svg"
    assert plugins[0]["icon_dark"] == "https://store.example/icons/example-dark.svg"


def test_extract_plugins_preserves_tags_and_core_version():
    plugins = PluginsRoutes._extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "tags": ["utility", "network"],
                "core_version": ">=2.29.0",
            },
        },
    })

    assert plugins[0]["tags"] == ["utility", "network"]
    assert plugins[0]["core_version"] == ">=2.29.0"


def test_extract_plugins_preserves_pinned_source_fields():
    commit_sha = "a" * 40
    plugins = PluginsRoutes._extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "commit_sha": f" {commit_sha.upper()} ",
                "release_tag": "v1.2.3",
            },
        },
    })

    assert plugins[0]["commit_sha"] == commit_sha
    assert plugins[0]["release_tag"] == "v1.2.3"


def test_extract_plugins_falls_back_to_head_for_invalid_commit_sha():
    plugins = PluginsRoutes._extract_plugins({
        "plugins": {
            "example": {
                "plugin_id": "example",
                "commit_sha": "v1.2.3",
            },
        },
    })

    assert plugins[0]["commit_sha"] is None


@pytest.mark.asyncio
async def test_update_check_falls_back_to_head_for_invalid_catalog_commit_sha(tmp_path, monkeypatch):
    source = {
        "id": "source-1",
        "url": "https://store.example/plugins.json",
        "cache_file": None,
        "updated_at": 0,
        "is_current": True,
    }

    async def fetch_store(url):
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
    monkeypatch.setattr(plugin_routes, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(PluginManager, "fetch_plugin_store_data", fetch_store)
    routes = PluginsRoutes(
        FastAPI(),
        SimpleNamespace(plugin_manager=plugin_manager, db_service=FakeDatabaseService(source)),
    )

    result = await routes.check_plugin_updates()

    assert result[0].has_update is True
    assert result[0].commit_sha is None
