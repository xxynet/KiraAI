import pytest
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI

from core.plugin import plugin_registry
from core.plugin.plugin_registry import PageMenu, PluginComponents, PluginInfo, PluginManager
from webui.routes.plugins import PluginsRoutes


def _register_page(monkeypatch, tmp_path, icon, route="/dashboard"):
    components = PluginComponents()
    components.register_page(route, None, menu=PageMenu(label="Dashboard", icon=icon))
    monkeypatch.setattr(plugin_registry, "_plugin_components", {"test-plugin": components})
    monkeypatch.setattr(plugin_registry, "_plugin_module_paths", {"test-plugin": tmp_path})


def test_page_menu_icon_resolves_svg_inside_plugin_root(monkeypatch, tmp_path):
    icon = tmp_path / "assets" / "menu.svg"
    icon.parent.mkdir()
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "assets/menu.svg")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") == icon.resolve()
    # Route normalization: the endpoint passes the route without the leading slash
    assert manager.get_page_menu_icon_path("test-plugin", "/dashboard") == icon.resolve()


def test_page_menu_icon_resolves_nested_page_routes(monkeypatch, tmp_path):
    icon = tmp_path / "icon.svg"
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "icon.svg", route="/sub/page")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "sub/page") == icon.resolve()


def test_page_menu_icon_tolerates_leading_slash(monkeypatch, tmp_path):
    icon = tmp_path / "assets" / "menu.svg"
    icon.parent.mkdir()
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "/assets/menu.svg")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") == icon.resolve()


def test_page_menu_icon_keeps_element_plus_names_unresolved(monkeypatch, tmp_path):
    _register_page(monkeypatch, tmp_path, "Monitor")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") is None


def test_page_menu_icon_rejects_paths_outside_plugin_root(monkeypatch, tmp_path):
    outside = tmp_path.parent / "outside.svg"
    outside.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "../outside.svg")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") is None


def test_page_menu_icon_rejects_non_svg_images(monkeypatch, tmp_path):
    png = tmp_path / "icon.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    _register_page(monkeypatch, tmp_path, "icon.png")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") is None


def test_page_menu_icon_rejects_non_image_files(monkeypatch, tmp_path):
    script = tmp_path / "main.py"
    script.write_text("print('not an icon')", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "main.py")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "dashboard") is None


def test_page_menu_icon_unknown_page_returns_none(monkeypatch, tmp_path):
    icon = tmp_path / "icon.svg"
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "icon.svg")
    manager = PluginManager()

    assert manager.get_page_menu_icon_path("test-plugin", "missing") is None
    assert manager.get_page_menu_icon_path("unknown-plugin", "dashboard") is None


@pytest.mark.anyio
async def test_menu_icon_endpoint_serves_svg(monkeypatch, tmp_path):
    icon = tmp_path / "assets" / "menu.svg"
    icon.parent.mkdir()
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "assets/menu.svg")

    lifecycle = SimpleNamespace(plugin_manager=PluginManager())
    routes = PluginsRoutes(FastAPI(), lifecycle)

    response = await routes.get_plugin_menu_icon("test-plugin", "dashboard")

    assert response.status_code == 200
    assert response.media_type == "image/svg+xml"
    assert Path(response.path).resolve() == icon.resolve()


@pytest.mark.anyio
async def test_menu_icon_endpoint_returns_404_without_icon(monkeypatch, tmp_path):
    from fastapi import HTTPException

    _register_page(monkeypatch, tmp_path, "Monitor")

    lifecycle = SimpleNamespace(plugin_manager=PluginManager())
    routes = PluginsRoutes(FastAPI(), lifecycle)

    with pytest.raises(HTTPException) as exc_info:
        await routes.get_plugin_menu_icon("test-plugin", "dashboard")
    assert exc_info.value.status_code == 404


@pytest.mark.anyio
async def test_list_plugins_rewrites_file_menu_icons_to_urls(monkeypatch, tmp_path):
    icon = tmp_path / "assets" / "menu.svg"
    icon.parent.mkdir()
    icon.write_text("<svg></svg>", encoding="utf-8")
    _register_page(monkeypatch, tmp_path, "assets/menu.svg")
    monkeypatch.setattr(
        plugin_registry, "_plugin_infos",
        {"test-plugin": PluginInfo(plugin_id="test-plugin", display_name="Test Plugin")},
    )

    lifecycle = SimpleNamespace(plugin_manager=PluginManager())
    routes = PluginsRoutes(FastAPI(), lifecycle)

    items = await routes.list_plugins()

    assert items[0].menus[0].icon == "/api/plugins/test-plugin/menu-icon/dashboard"


@pytest.mark.anyio
async def test_list_plugins_keeps_icon_names_as_is(monkeypatch, tmp_path):
    _register_page(monkeypatch, tmp_path, "Monitor")
    monkeypatch.setattr(
        plugin_registry, "_plugin_infos",
        {"test-plugin": PluginInfo(plugin_id="test-plugin", display_name="Test Plugin")},
    )

    lifecycle = SimpleNamespace(plugin_manager=PluginManager())
    routes = PluginsRoutes(FastAPI(), lifecycle)

    items = await routes.list_plugins()

    assert items[0].menus[0].icon == "Monitor"
