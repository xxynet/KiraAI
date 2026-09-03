import asyncio
import json

from core.plugin.plugin_handlers import EventType, event_handler_reg
from core.plugin import plugin_registry


PLUGIN_ID = "multi_file_reload_plugin"


def _write_plugin(plugin_root, helper_source: str, main_source: str) -> None:
    plugin_root.mkdir(parents=True, exist_ok=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps({"plugin_id": PLUGIN_ID}), encoding="utf-8"
    )
    (plugin_root / "hooks.py").write_text(helper_source, encoding="utf-8")
    (plugin_root / "main.py").write_text(main_source, encoding="utf-8")


def test_loading_updated_multifile_plugin_evicts_helpers_and_old_hooks(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_registry, "_plugin_classes", {})
    monkeypatch.setattr(plugin_registry, "_plugin_components", {})
    monkeypatch.setattr(plugin_registry, "_plugin_load_errors", {})
    monkeypatch.setattr(plugin_registry, "_plugin_manifests", {})
    monkeypatch.setattr(plugin_registry, "_plugin_module_dirs", {})
    monkeypatch.setattr(plugin_registry, "_plugin_module_paths", {})
    monkeypatch.setattr(plugin_registry, "_plugin_schemas", {})
    monkeypatch.setattr(plugin_registry, "_plugin_infos", {})
    monkeypatch.setattr(plugin_registry, "_module_to_plugin", {})
    monkeypatch.setattr(event_handler_reg, "_handlers", {})

    plugins_dir = tmp_path / "plugins"
    plugin_root = plugins_dir / PLUGIN_ID
    helper_v1 = '''
from core.plugin.plugin_registry import on


class HookMixin:
    @on.im_message()
    async def handle_message(self, event):
        self.handled_version = "v1"
'''
    main_v1 = '''
from core.plugin.plugin import BasePlugin
from .hooks import HookMixin


class TestPlugin(HookMixin, BasePlugin):
    generation = "v1"

    async def initialize(self):
        pass

    async def terminate(self):
        pass
'''
    _write_plugin(plugin_root, helper_v1, main_v1)

    async def run_test():
        manager = plugin_registry.PluginManager()
        manager.plugin_dir = plugins_dir
        assert await manager.load_plugin_from_dir(plugin_root) == PLUGIN_ID

        helper_v2 = '''
from core.plugin.plugin_registry import on

NEW_MARKER = "v2"


class HookMixin:
    @on.im_message()
    async def handle_message(self, event):
        self.handled_version = NEW_MARKER
'''
        main_v2 = '''
from core.plugin.plugin import BasePlugin
from .hooks import HookMixin, NEW_MARKER


class TestPlugin(HookMixin, BasePlugin):
    generation = NEW_MARKER

    async def initialize(self):
        pass

    async def terminate(self):
        pass
'''
        _write_plugin(plugin_root, helper_v2, main_v2)

        await manager.prepare_plugin_reload(PLUGIN_ID)

        assert await manager.load_plugin_from_dir(plugin_root) == PLUGIN_ID
        instance = manager.get_plugin_inst(PLUGIN_ID)
        assert instance.generation == "v2"

        handlers = event_handler_reg.get_handlers(EventType.ON_IM_MESSAGE)
        assert len(handlers) == 1
        assert handlers[0].handler.__self__ is instance

        await manager.terminate(PLUGIN_ID)
        manager._cleanup_plugin_modules(PLUGIN_ID)

    asyncio.run(run_test())
