from core.plugin import plugin_registry


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
