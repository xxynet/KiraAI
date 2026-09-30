"""Regression coverage for shared registration state and builtin ownership."""

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import core.plugin.builtin_plugins as builtin_plugins
from core.plugin import PluginManager, registry
from core.plugin import manager as manager_module
from core.plugin.handlers import EventHandler, EventType, Priority, event_handler_reg
from core.tag import tag_registry


PLUGIN_ID = "registry_builtin_test"
PACKAGE_NAME = "core.plugin.builtin_plugins.registry_migration"
PLUGIN_SOURCE = '''
from core.plugin import BasePlugin, PluginPage, on, register

PAGE = register.page("/status", auth=False)(PluginPage.from_html("ready"))


class RegistryPlugin(BasePlugin):
    async def initialize(self):
        plugin_id = self.ctx.plugin_mgr.get_plugin_id_for_module(__name__)
        comp = self.ctx.plugin_mgr.get_plugin_components()[plugin_id]
        comp.tags[0]["description"] = "configured description"

    async def terminate(self):
        pass

    @register.tool("registry_tool", "test tool", {})
    async def status(self):
        return "ready"

    @register.tag("registry_tag", "initial description")
    async def tag(self, value, **kwargs):
        return value

    @on.custom_event(priority=10, event_name="registry_event")
    async def handle(self, event):
        pass
'''


@pytest.fixture
def isolated_registry(tmp_path, monkeypatch):
    for name in (
        "_plugin_classes", "_plugin_components", "_plugin_load_errors",
        "_plugin_manifests", "_plugin_module_dirs", "_plugin_module_paths",
        "_plugin_schemas", "_plugin_infos", "_module_to_plugin",
    ):
        monkeypatch.setattr(registry, name, {})
    monkeypatch.setattr(manager_module, "PLUGIN_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(manager_module, "PLUGIN_STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(event_handler_reg, "_handlers", {})
    monkeypatch.setattr(tag_registry, "_tags", [])
    monkeypatch.setattr(tag_registry, "_root_tags", [])


def test_builtin_declarations_share_registry_and_bind_instance(tmp_path, monkeypatch, isolated_registry):
    root = tmp_path / "builtin_plugins"
    plugin_root = root / "registry_migration"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps({"plugin_id": PLUGIN_ID}), encoding="utf-8"
    )
    (plugin_root / "main.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    monkeypatch.setattr(manager_module, "BUILTIN_PLUGINS_DIR", root)
    monkeypatch.setattr(builtin_plugins, "__path__", [str(root)])
    tool_mgr = Mock()
    context = SimpleNamespace(tool_mgr=tool_mgr)
    manager = PluginManager(context)
    context.plugin_mgr = manager

    async def run():
        try:
            await manager._discover_builtin_plugins()
            assert not manager.get_plugin_load_errors()
            assert manager.get_registered_plugins().keys() == {PLUGIN_ID}
            assert manager.get_plugin_info(PLUGIN_ID).builtin
            comp = manager.get_plugin_components()[PLUGIN_ID]
            assert comp is registry._plugin_components[PLUGIN_ID]
            assert "" not in registry._plugin_components
            assert comp.pages[0]["page"].source_value == "ready"
            assert registry.get_obj_plugin_id(comp.tool_funcs["registry_tool"]) == PLUGIN_ID

            await manager.init_plugin(PLUGIN_ID)
            instance = manager.get_plugin_inst(PLUGIN_ID)
            assert instance is not None
            tool_func = tool_mgr.register_tool.call_args.kwargs["func"]
            assert tool_func.__self__ is instance
            assert await tool_func() == "ready"
            assert tag_registry.get("registry_tag").description == "configured description"
            hooks = event_handler_reg.get_handlers(EventType.ON_CUSTOM_EVENT)
            assert len(hooks) == 1
            assert hooks[0].handler.__self__ is instance
            assert hooks[0].handler._custom_event_name == "registry_event"

            await manager.terminate(PLUGIN_ID)
            assert not event_handler_reg.get_handlers(EventType.ON_CUSTOM_EVENT)
            assert comp is manager.get_plugin_components()[PLUGIN_ID]
        finally:
            await manager.terminate(PLUGIN_ID)
            manager._cleanup_plugin_modules(PLUGIN_ID)
            for name in list(sys.modules):
                if name == PACKAGE_NAME or name.startswith(PACKAGE_NAME + "."):
                    sys.modules.pop(name, None)
            if hasattr(builtin_plugins, "registry_migration"):
                delattr(builtin_plugins, "registry_migration")

    asyncio.run(run())


def test_exception_handler_resolves_plugin_from_shared_registry(isolated_registry, monkeypatch):
    monkeypatch.setitem(registry._module_to_plugin, __name__, PLUGIN_ID)
    received = []
    event = object()

    async def failing_handler(event):
        raise ValueError("test failure")

    async def exception_handler(event, error):
        received.append((event, error))

    event_handler_reg.register(EventHandler(EventType.ON_EXCEPTION, Priority.MEDIUM, exception_handler))
    handler = EventHandler(EventType.ON_CUSTOM_EVENT, Priority.MEDIUM, failing_handler)
    asyncio.run(handler.exec_handler(event))

    assert len(received) == 1
    assert received[0][0] is event
    assert received[0][1].comp_id == PLUGIN_ID
    assert received[0][1].stage == EventType.ON_CUSTOM_EVENT.value
