"""Regression tests for per-page auth binding on plugin folder pages.

``PluginPageStaticFiles`` / ``DeferredPluginPageStaticFiles`` are defined
inside the page-registration loop; the auth flag must be bound per instance,
not captured from the loop variable (which late-binds to the LAST page's
value at request time).
"""
import asyncio
import json

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from core.plugin import plugin_registry
from core.plugin.plugin_handlers import event_handler_reg

PLUGIN_ID = "auth_binding_test_plugin"


def _reset_plugin_state(monkeypatch):
    """Clear module-level plugin registries so each test loads in isolation."""
    for attr in (
        "_plugin_classes", "_plugin_components", "_plugin_load_errors",
        "_plugin_manifests", "_plugin_module_dirs", "_plugin_module_paths",
        "_plugin_schemas", "_plugin_infos", "_module_to_plugin",
    ):
        monkeypatch.setattr(plugin_registry, attr, {})
    monkeypatch.setattr(event_handler_reg, "_handlers", {})


def _write_plugin(plugin_root, page_specs):
    """Write a plugin whose folder pages are registered in the given order.

    page_specs: list of ``(route, auth)`` tuples, all served from ./web.
    """
    web = plugin_root / "web"
    web.mkdir(parents=True)
    (web / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (plugin_root / "manifest.json").write_text(
        json.dumps({"plugin_id": PLUGIN_ID}), encoding="utf-8"
    )

    main_lines = [
        "from core.plugin.plugin_registry import PluginPage, register",
        "from core.plugin.plugin import BasePlugin",
        "",
    ]
    for i, (route, auth) in enumerate(page_specs):
        main_lines.append(
            f"PAGE_{i} = register.page({route!r}, auth={auth})"
            "(PluginPage.from_folder('./web'))"
        )
    main_lines += [
        "",
        "",
        "class AuthBindingPlugin(BasePlugin):",
        '    generation = "v1"',
        "",
        "    async def initialize(self):",
        "        pass",
        "",
        "    async def terminate(self):",
        "        pass",
    ]
    (plugin_root / "main.py").write_text("\n".join(main_lines), encoding="utf-8")


def _load_client(tmp_path, monkeypatch, page_specs):
    """Load the test plugin with the given folder pages; return its TestClient."""
    _reset_plugin_state(monkeypatch)
    plugin_root = tmp_path / PLUGIN_ID
    _write_plugin(plugin_root, page_specs)

    async def setup():
        """Load the plugin and mount its page routes on a fresh app."""
        manager = plugin_registry.PluginManager()
        manager.plugin_dir = tmp_path
        loaded = await manager.load_plugin_from_dir(plugin_root)
        assert loaded == PLUGIN_ID, manager.get_plugin_load_errors()
        manager._web_app = FastAPI()
        manager._register_plugin_pages_for(PLUGIN_ID)
        return manager

    manager = asyncio.run(setup())
    return TestClient(manager._web_app)


def test_object_folder_pages_bind_auth_per_page(monkeypatch, tmp_path):
    """Secure first, open last: the secure page must keep auth=True even
    though the LAST registered page is open (late-binding bug -> 200)."""
    client = _load_client(tmp_path, monkeypatch,
                          [("/secure", True), ("/open", False)])

    r = client.get(f"/page/plugin/{PLUGIN_ID}/secure")
    assert r.status_code == 401, dict(r.headers)

    r = client.get(f"/page/plugin/{PLUGIN_ID}/open/")
    assert r.status_code == 200
    assert r.text == "<html>ok</html>"
    assert r.headers["cache-control"] == "no-store"


def test_deferred_folder_pages_bind_auth_per_page(monkeypatch, tmp_path):
    """Same order dependence for pages returned by plugin methods."""
    _reset_plugin_state(monkeypatch)
    plugin_root = tmp_path / PLUGIN_ID
    plugin_root.mkdir(parents=True)
    web = plugin_root / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (plugin_root / "manifest.json").write_text(
        json.dumps({"plugin_id": PLUGIN_ID}), encoding="utf-8"
    )
    (plugin_root / "main.py").write_text('''
from core.plugin.plugin_registry import PluginPage, register
from core.plugin.plugin import BasePlugin


class AuthBindingPlugin(BasePlugin):
    generation = "v1"

    async def initialize(self):
        pass

    async def terminate(self):
        pass

    @register.page("/secure", auth=True)
    def secure_page(self):
        return PluginPage.from_folder("./web")

    @register.page("/open", auth=False)
    def open_page(self):
        return PluginPage.from_folder("./web")
''', encoding="utf-8")

    async def setup():
        """Load the plugin and mount its page routes on a fresh app."""
        manager = plugin_registry.PluginManager()
        manager.plugin_dir = tmp_path
        loaded = await manager.load_plugin_from_dir(plugin_root)
        assert loaded == PLUGIN_ID, manager.get_plugin_load_errors()
        manager._web_app = FastAPI()
        manager._register_plugin_pages_for(PLUGIN_ID)
        return manager

    client = TestClient(asyncio.run(setup())._web_app)

    r = client.get(f"/page/plugin/{PLUGIN_ID}/secure")
    assert r.status_code == 401, dict(r.headers)

    r = client.get(f"/page/plugin/{PLUGIN_ID}/open/")
    assert r.status_code == 200
    assert r.text == "<html>ok</html>"
    assert r.headers["cache-control"] == "no-store"


def test_open_first_keeps_open_page_public(monkeypatch, tmp_path):
    """Mirror direction: open first, secure last. The open page must stay
    publicly reachable (late-binding bug -> 401 from the last page's flag)."""
    client = _load_client(tmp_path, monkeypatch,
                          [("/open", False), ("/secure", True)])

    r = client.get(f"/page/plugin/{PLUGIN_ID}/open/")
    assert r.status_code == 200
    assert r.text == "<html>ok</html>"
    assert r.headers["cache-control"] == "no-store"

    r = client.get(f"/page/plugin/{PLUGIN_ID}/secure")
    assert r.status_code == 401
