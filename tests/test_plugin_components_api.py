"""HTTP regression coverage for registered plugin component summaries."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.plugin import PageMenu, PluginInfo, PluginManager, registry
from core.plugin.components import PluginComponents
from core.plugin.handlers import EventType, Priority
from webui.routes.auth import require_auth
from webui.routes.plugins import PluginsRoutes


@pytest.fixture
def components_client(monkeypatch):
    monkeypatch.setattr(registry, "_plugin_infos", {
        "test-plugin": PluginInfo(plugin_id="test-plugin", display_name="Test Plugin"),
    })
    monkeypatch.setattr(registry, "_plugin_components", {})
    app = FastAPI()
    routes = PluginsRoutes(app, SimpleNamespace(plugin_manager=PluginManager()))
    routes.register()
    app.dependency_overrides[require_auth] = lambda: "admin"
    with TestClient(app) as client:
        yield client


def test_summaries_cover_registered_types_without_runtime_data(components_client, monkeypatch):
    async def handler(*args, **kwargs):
        """Handle plugin events."""

    async def custom_handler(*args, **kwargs):
        pass

    custom_handler._custom_event_name = "plugin_ready"

    class Capability:
        pass

    components = PluginComponents()
    components.register_tool("search", "Search the web", {"private_default": "hidden"}, handler)
    components.register_tag("image", "Generate an image", handler)
    components.register_hook(handler, Priority.MEDIUM, EventType.ON_LOADED)
    components.register_hook(custom_handler, Priority.LOW, EventType.ON_CUSTOM_EVENT)
    components.register_page("/dashboard", handler, menu=PageMenu(
        label={"en": "Dashboard", "zh": "仪表盘"},
    ))
    components.register_page("/plain", handler)
    components.register_api("post", "/action", handler, internal_option="hidden")
    components.register_ws("/stream", handler)
    components.register_static("/assets", "/private/plugin/assets")
    components.register_widget(
        "test-plugin:status", {"en": "Status", "zh": "状态"},
        "", "blue", 0, "small", handler,
    )
    components.register_provider("model-format", {"class": object, "path": "/private/provider"})
    components.register_adapter("chat-platform", {"class": object, "path": "/private/adapter"})
    components.adapter_capabilities.add(("chat-platform", Capability))
    monkeypatch.setitem(registry._plugin_components, "test-plugin", components)

    response = components_client.get("/api/plugins/test-plugin/components")
    assert response.status_code == 200
    items = response.json()
    assert {item["type"] for item in items} == {
        "tool", "tag", "hook", "page", "api", "websocket", "static",
        "widget", "provider", "adapter", "adapter_capability",
    }
    by_name = {item["name"]: item for item in items}
    assert by_name["search"]["description"] == "Search the web"
    assert by_name["on_loaded: handler"]["description"] == "Handle plugin events."
    assert "plugin_ready: custom_handler" in by_name
    assert by_name["/dashboard"]["description"] == {"en": "Dashboard", "zh": "仪表盘"}
    assert by_name["test-plugin:status"]["description"] == {"en": "Status", "zh": "状态"}
    assert "POST /action" in by_name
    assert "chat-platform: Capability" in by_name
    assert all(set(item) == {"type", "name", "description"} for item in items)
    assert "/private" not in response.text
    assert "hidden" not in response.text


@pytest.mark.parametrize("registered", [False, True])
def test_installed_plugin_without_components_returns_empty(components_client, monkeypatch, registered):
    if registered:
        monkeypatch.setitem(registry._plugin_components, "test-plugin", PluginComponents())
    assert components_client.get("/api/plugins/test-plugin/components").json() == []


def test_components_reject_unknown_plugin(components_client):
    assert components_client.get("/api/plugins/missing/components").status_code == 404


def test_components_require_authentication(components_client):
    components_client.app.dependency_overrides.clear()
    assert components_client.get("/api/plugins/test-plugin/components").status_code == 401


def test_components_report_unavailable_manager():
    app = FastAPI()
    PluginsRoutes(app).register()
    app.dependency_overrides[require_auth] = lambda: "admin"
    with TestClient(app) as client:
        assert client.get("/api/plugins/test-plugin/components").status_code == 503
