"""Compatibility coverage for extracted plugin models and WebUI bindings."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import core.plugin as public_api
from core.plugin import manager as manager_module
from core.plugin.components import PluginComponents
from core.plugin.metadata import PluginInfo
from core.plugin.pages import PageMenu, PluginPage, PluginPageSource
from core.plugin.plugin_handlers import event_handler_reg
from core.tag import tag_registry


PLUGIN_ID = "web_migration_test"
PLUGIN_SOURCE = '''
from __future__ import annotations

from core.plugin import PageMenu, logger, get_logger
from core.plugin.pages import PluginPage
from core.plugin.base import BasePlugin
from core.plugin.manager import register, _plugin_components

OBJECT_FOLDER = register.page("/object-folder", auth=False)(PluginPage.from_folder("web"))
OBJECT_HTML = register.page("/object-html", auth=False)(PluginPage.from_html("object html"))
OBJECT_URL = register.page("/object-url", auth=False)(PluginPage.from_url("/object-target"))
OBJECT_ESCAPE = register.page("/object-escape", auth=False)(PluginPage.from_folder("../outside"))
OBJECT_SECURE = register.page("/object-secure", auth=True)(PluginPage.from_folder("web"))


class WebPlugin(BasePlugin):
    async def initialize(self):
        self.value = "ready"
        manager = self.ctx.plugin_mgr
        plugin_id = manager.get_plugin_id_for_module(__name__)
        comp = manager.get_plugin_components()[plugin_id]
        assert comp is _plugin_components[plugin_id]
        for tag in comp.tags:
            tag["description"] = "configured description"

    async def terminate(self):
        pass

    @register.tag("migration_tag", "original description")
    async def tag(self, value, **kwargs):
        return value

    @register.page("/method-folder", auth=False)
    def folder(self):
        return PluginPage.from_folder("web")

    @register.page("/method-html", auth=False)
    def html(self):
        return PluginPage.from_html(self.value)

    @register.page("/method-url", auth=False)
    def url(self):
        return PluginPage.from_url("/method-target")

    @register.page("/method-escape", auth=False)
    def escape(self):
        return PluginPage.from_folder("../outside")

    @register.page("/method-secure", auth=True)
    def secure(self):
        return PluginPage.from_folder("web")

    @register.page("/secure-html", auth=True)
    def secure_html(self):
        return PluginPage.from_html("secure html")

    @register.page("/secure-url", auth=True)
    def secure_url(self):
        return PluginPage.from_url("/secure-target")

    @register.api("GET", "/status", auth=False)
    async def status(self, count: int = 1):
        return {"value": self.value, "count": count}

    @register.api("GET", "/private-status", auth=True)
    async def private_status(self):
        return {"value": self.value}

    @register.ws("/stream", auth=False)
    async def stream(self, ws):
        await ws.accept()
        await ws.send_text(self.value)
        await ws.close()

    @register.ws("/private-stream", auth=True)
    async def private_stream(self, ws):
        await ws.accept()
        await ws.send_text(self.value)
        await ws.close()

    @register.static("/assets", "web")
    def assets(self):
        pass

    @register.widget(label="Status")
    def status_widget(self):
        return self.value
'''


@pytest.fixture
def load_plugin(tmp_path, monkeypatch):
    for name in (
        "_plugin_classes", "_plugin_components", "_plugin_load_errors",
        "_plugin_manifests", "_plugin_module_dirs", "_plugin_module_paths",
        "_plugin_schemas", "_plugin_infos", "_module_to_plugin",
    ):
        monkeypatch.setattr(manager_module, name, {})
    monkeypatch.setattr(manager_module, "PLUGINS_DIR", tmp_path)
    monkeypatch.setattr(manager_module, "PLUGIN_DATA_DIR", tmp_path / "plugin_data")
    monkeypatch.setattr(manager_module, "PLUGIN_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(manager_module, "PLUGIN_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(event_handler_reg, "_handlers", {})
    monkeypatch.setattr(tag_registry, "_tags", [])
    monkeypatch.setattr(tag_registry, "_root_tags", [])

    root = tmp_path / PLUGIN_ID
    web = root / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("folder content", encoding="utf-8")
    (root / "manifest.json").write_text(json.dumps({"plugin_id": PLUGIN_ID}), encoding="utf-8")
    (root / "main.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "index.html").write_text("outside content", encoding="utf-8")
    context = SimpleNamespace(plugin_mgr=None)
    manager = manager_module.PluginManager(context)
    context.plugin_mgr = manager

    def load(app_first=False):
        app = FastAPI()
        if app_first:
            manager.set_web_app(app)
        loaded = asyncio.run(manager.load_plugin_from_dir(root, auto_install=False))
        assert loaded == PLUGIN_ID, manager.get_plugin_load_errors()
        if not app_first:
            manager.set_web_app(app)
        return manager, TestClient(app)

    yield load
    asyncio.run(manager.terminate(PLUGIN_ID))
    manager._cleanup_plugin_modules(PLUGIN_ID)


def test_old_and_new_model_imports_share_identity():
    for model in (PluginInfo, PageMenu, PluginPage, PluginPageSource, PluginComponents):
        assert getattr(manager_module, model.__name__) is model
    for model in (PluginInfo, PageMenu, PluginPage):
        assert getattr(public_api, model.__name__) is model
    assert public_api.register is manager_module.register
    assert public_api.on is manager_module.on
    assert public_api.register_tool is manager_module.register_tool
    assert callable(public_api.get_logger)


@pytest.mark.parametrize("app_first", [False, True])
def test_plugin_imports_mutable_tags_and_all_web_bindings(load_plugin, app_first):
    manager, client = load_plugin(app_first)
    comp = manager.get_plugin_components()[PLUGIN_ID]
    assert comp is manager_module._plugin_components[PLUGIN_ID]
    assert tag_registry.get("migration_tag").description == "configured description"
    assert manager.get_all_widgets()[0].content == "ready"
    paths = client.app.openapi()["paths"]
    for kind, prefix in (("object", ""), ("method", "deferred_")):
        for source, endpoint in (("html", "html_endpoint"), ("url", "redirect_endpoint")):
            operation = paths[f"/page/plugin/{PLUGIN_ID}/{kind}-{source}"]["get"]
            assert operation["operationId"].startswith(f"{prefix}{endpoint}_")

    for kind in ("object", "method"):
        response = client.get(f"/page/plugin/{PLUGIN_ID}/{kind}-folder/")
        assert response.text == "folder content"
        assert response.headers["cache-control"] == "no-store"
        expected_html = "object html" if kind == "object" else "ready"
        assert client.get(f"/page/plugin/{PLUGIN_ID}/{kind}-html").text == expected_html
        response = client.get(f"/page/plugin/{PLUGIN_ID}/{kind}-url", follow_redirects=False)
        assert response.status_code == 307
        assert response.headers["location"] == f"/{kind}-target"
        assert client.get(f"/page/plugin/{PLUGIN_ID}/{kind}-escape/").status_code == 404
    assert client.get(f"/static/plugin/{PLUGIN_ID}/assets/index.html").text == "folder content"
    assert client.get(f"/api/plugin/{PLUGIN_ID}/status?count=3").json() == {"value": "ready", "count": 3}
    assert client.get(f"/api/plugin/{PLUGIN_ID}/status?count=bad").status_code == 422
    with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream") as ws:
        assert ws.receive_text() == "ready"

    # Endpoints must look up the current instance rather than retain a bound method.
    old_instance = manager.get_plugin_inst(PLUGIN_ID)
    replacement = type(old_instance)(manager.ctx, {})
    replacement.value = "replacement"
    manager.plugin_instances[PLUGIN_ID] = replacement
    assert client.get(f"/api/plugin/{PLUGIN_ID}/status").json()["value"] == "replacement"
    with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream") as ws:
        assert ws.receive_text() == "replacement"
    assert manager.get_all_widgets()[0].content == "replacement"


def test_auth_dependencies_and_folder_auth_survive_extraction(load_plugin, monkeypatch):
    import webui.routes.auth as auth
    import webui.utils as utils

    manager, client = load_plugin()

    def verify(token, app_state):
        assert app_state.plugin_manager is manager
        if token != "test-token":
            raise HTTPException(status_code=401)
        return {"sub": "test-user"}

    monkeypatch.setattr(auth, "verify_session_token", verify)
    monkeypatch.setattr(utils, "verify_session_token", verify)
    secure_paths = [
        f"/page/plugin/{PLUGIN_ID}/object-secure/",
        f"/page/plugin/{PLUGIN_ID}/method-secure/",
        f"/page/plugin/{PLUGIN_ID}/secure-html",
        f"/page/plugin/{PLUGIN_ID}/secure-url",
        f"/api/plugin/{PLUGIN_ID}/private-status",
    ]
    for path in secure_paths:
        assert client.get(path, follow_redirects=False).status_code == 401
        assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        expected = 307 if path.endswith("secure-url") else 200
        assert client.get(path, headers={"Authorization": "Bearer test-token"}, follow_redirects=False).status_code == expected
        client.cookies.set("kira_token", "test-token")
        assert client.get(path, follow_redirects=False).status_code == expected
        client.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as denied:
        with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/private-stream"):
            pass
    assert denied.value.code == 4003
    with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/private-stream?token=test-token") as ws:
        assert ws.receive_text() == "ready"


def test_disable_enable_removes_and_restores_routes_without_duplicates(load_plugin):
    manager, client = load_plugin()
    app = client.app
    route_count = len(app.routes)
    manager.set_web_app(app)
    assert len(app.routes) == route_count
    schema = app.openapi()
    assert f"/api/plugin/{PLUGIN_ID}/status" in schema["paths"]

    asyncio.run(manager.set_plugin_enabled(PLUGIN_ID, False))
    assert app.openapi_schema is None
    assert manager.get_all_widgets() == []
    for path in (
        f"/api/plugin/{PLUGIN_ID}/status",
        f"/page/plugin/{PLUGIN_ID}/method-html",
        f"/page/plugin/{PLUGIN_ID}/object-folder/",
        f"/static/plugin/{PLUGIN_ID}/assets/index.html",
    ):
        assert client.get(path).status_code == 404
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream"):
            pass

    asyncio.run(manager.set_plugin_enabled(PLUGIN_ID, True))
    assert len(app.routes) == route_count
    assert manager.get_all_widgets()[0].content == "ready"
    assert client.get(f"/api/plugin/{PLUGIN_ID}/status").status_code == 200
    assert client.get(f"/page/plugin/{PLUGIN_ID}/object-folder/").text == "folder content"
    assert client.get(f"/static/plugin/{PLUGIN_ID}/assets/index.html").text == "folder content"
    with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream") as ws:
        assert ws.receive_text() == "ready"


def test_registration_tracking_is_scoped_to_the_app(load_plugin):
    manager, first_client = load_plugin()
    second_app = FastAPI()
    manager.set_web_app(second_app)
    second_client = TestClient(second_app)
    assert len(second_app.routes) == len(first_client.app.routes)
    assert second_client.get(f"/api/plugin/{PLUGIN_ID}/status").status_code == 200
    assert second_client.get(f"/page/plugin/{PLUGIN_ID}/object-folder/").text == "folder content"
    with second_client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream") as ws:
        assert ws.receive_text() == "ready"

def test_web_endpoints_check_current_plugin_availability(load_plugin):
    manager, client = load_plugin()
    manager.plugin_enabled[PLUGIN_ID] = False
    for path in (
        f"/api/plugin/{PLUGIN_ID}/status",
        f"/page/plugin/{PLUGIN_ID}/object-folder/",
        f"/page/plugin/{PLUGIN_ID}/method-folder/",
        f"/static/plugin/{PLUGIN_ID}/assets/index.html",
    ):
        assert client.get(path).status_code == 404
    assert manager.get_all_widgets() == []
    with pytest.raises(WebSocketDisconnect) as disabled:
        with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream"):
            pass
    assert disabled.value.code == 1011

    manager.plugin_enabled[PLUGIN_ID] = True
    manager.plugin_instances.pop(PLUGIN_ID)
    assert client.get(f"/api/plugin/{PLUGIN_ID}/status").status_code == 503
    with pytest.raises(WebSocketDisconnect) as unavailable:
        with client.websocket_connect(f"/ws/plugin/{PLUGIN_ID}/stream"):
            pass
    assert unavailable.value.code == 1011
