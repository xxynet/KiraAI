import asyncio
from types import ModuleType, SimpleNamespace

from core.plugin import plugin_registry
from core.provider import BaseProvider

def test_cleanup_preserves_widget_declarations(monkeypatch):
    """Widgets must remain declared so a disabled plugin can be re-enabled."""
    plugin_id = "widget_lifecycle_test"
    components = plugin_registry.PluginComponents()

    def status_widget():
        return "ready"

    components.register_widget(
        widget_id=f"{plugin_id}:status_widget",
        label="Status",
        icon="Box",
        color="blue",
        order=0,
        size="small",
        func=status_widget,
    )
    monkeypatch.setitem(plugin_registry._plugin_components, plugin_id, components)

    manager = plugin_registry.PluginManager(ctx=None)
    manager._cleanup_plugin_registration(plugin_id)

    assert components.widgets[0]["widget_id"] == f"{plugin_id}:status_widget"
    assert components.widget_funcs[f"{plugin_id}:status_widget"] is status_widget

class _FailingStopAdapterManager:
    async def stop_adapter_instances_by_platform(self, platform):
        raise RuntimeError("stop failed")

    def unregister_adapter_type(self, platform, adapter_cls):
        raise AssertionError("The type must remain registered after a stop failure")


class _ProviderManager:
    pass


def test_unregister_plugin_adapter_keeps_metadata_when_stop_fails(monkeypatch):
    plugin_id = "adapter_cleanup_failure"
    platform = "adapter-cleanup-platform"
    components = plugin_registry.PluginComponents()
    adapter_cls = type("PluginAdapter", (), {})
    components.register_adapter(platform, {"class": adapter_cls})
    monkeypatch.setitem(plugin_registry._plugin_components, plugin_id, components)

    manager = plugin_registry.PluginManager(
        ctx=SimpleNamespace(adapter_mgr=_FailingStopAdapterManager())
    )

    assert asyncio.run(manager.unregister_plugin_adapter(plugin_id, platform)) is False
    assert components.adapters[platform]["class"] is adapter_cls


def test_runtime_cleanup_continues_after_adapter_cleanup_failure(monkeypatch):
    plugin_id = "runtime_cleanup_failure"
    components = plugin_registry.PluginComponents()
    components.register_adapter("failing-platform", {"class": object})
    components.register_provider("remaining-provider", {"class": object})
    monkeypatch.setitem(plugin_registry._plugin_components, plugin_id, components)

    manager = plugin_registry.PluginManager(ctx=SimpleNamespace())
    provider_cleanup_calls = []

    async def fail_adapter_cleanup(plugin_id_arg, platform):
        assert plugin_id_arg == plugin_id
        assert platform == "failing-platform"
        raise RuntimeError("adapter cleanup failed")

    async def clean_provider(plugin_id_arg, provider_format):
        provider_cleanup_calls.append((plugin_id_arg, provider_format))
        return True

    monkeypatch.setattr(manager, "unregister_plugin_adapter", fail_adapter_cleanup)
    monkeypatch.setattr(manager, "unregister_plugin_provider", clean_provider)

    asyncio.run(manager._cleanup_plugin_runtime_components(plugin_id))

    assert provider_cleanup_calls == [(plugin_id, "remaining-provider")]


def test_component_class_lookup_ignores_imported_provider_classes():
    module = ModuleType("plugin_component_module")
    imported_provider = type(
        "ImportedProvider", (BaseProvider,), {"__module__": "shared_provider_module"}
    )
    local_provider = type(
        "LocalProvider", (BaseProvider,), {"__module__": module.__name__}
    )
    module.ImportedProvider = imported_provider
    module.LocalProvider = local_provider

    assert plugin_registry.PluginManager._find_component_class(
        module, (BaseProvider,), "Provider"
    ) is local_provider
