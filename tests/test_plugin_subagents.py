import json
from types import SimpleNamespace

import pytest

from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
from core.agent.subagent_presets import SubAgentPresetStore
from core.plugin import BasePlugin, PluginManager, SubAgentPreset, registry


@pytest.fixture(autouse=True)
def isolated_components(monkeypatch):
    monkeypatch.setattr(registry, "_plugin_components", {})


@pytest.mark.anyio
async def test_plugin_lifecycle_keeps_definitions_runtime_only_and_retains_user_scopes(tmp_path):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    ctx = SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store))
    manager = PluginManager(ctx)
    preset = SubAgentPreset(name="Coding", instruction_source="custom", instruction="Write code")
    item = await manager.register_plugin_subagent("coding", preset)
    assert not store.path.exists()
    user = await store.save(StoredSubAgentPreset(name="User"))
    await store.replace_scopes({item["id"]: {"allow": ["allowed-session"]}})
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data) == {user["id"], "_scope"}
    assert "plugin_id" not in data[user["id"]]
    snapshot = store.path.read_bytes()

    await manager._cleanup_plugin_runtime_components("coding")
    assert registry._plugin_components["coding"].subagents == {}
    assert store.list() == [user]
    assert store.get_scopes() == {}
    assert store.path.read_bytes() == snapshot

    restored = SubAgentPresetStore(store.path)
    await restored.initialize()
    assert restored.list() == [user]
    assert restored.get_scopes() == {}
    # Saving visible rules must not discard restrictions for disabled plugins.
    await restored.replace_scopes({})
    assert restored.path.read_bytes() == snapshot
    ctx.subagent_mgr.presets = restored
    reloaded = await manager.register_plugin_subagent("coding", preset)
    assert reloaded["id"] == item["id"]
    assert restored.is_preset_allowed(item["id"], "allowed-session")
    assert not restored.is_preset_allowed(item["id"], "other-session")
    assert restored.get_scopes() == {item["id"]: {"allow": ["allowed-session"]}}
    await manager.unregister_plugin_subagent("coding", item["id"])
    assert json.loads(restored.path.read_text(encoding="utf-8")) == {user["id"]: data[user["id"]]}
    assert registry._plugin_components["coding"].subagents == {}


@pytest.mark.anyio
async def test_failed_plugin_initialization_removes_registered_subagents(tmp_path, monkeypatch):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    ctx = SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store))
    manager = PluginManager(ctx)
    ctx.plugin_mgr = manager

    class FailingPlugin(BasePlugin):
        async def initialize(self):
            await self.ctx.plugin_mgr.register_plugin_subagent("failing", SubAgentPreset(name="Temporary"))
            raise RuntimeError("Initialization failed")

        async def terminate(self):
            pass

    monkeypatch.setitem(registry._plugin_classes, "failing", FailingPlugin)
    monkeypatch.setattr(manager, "is_plugin_enabled", lambda plugin_id: True)
    monkeypatch.setattr(manager, "_load_plugin_config_from_file", lambda plugin_id: {})
    await manager.init_plugin("failing")
    assert "failing" not in manager.plugin_instances
    assert registry._plugin_components["failing"].subagents == {}
    assert store.list() == []
    assert not store.path.exists()
