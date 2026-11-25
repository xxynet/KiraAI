import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.agent.subagent_presets import SubAgentPreset as StoredSubAgentPreset
from core.agent.subagent_presets import SubAgentPresetStore
from core.plugin import BasePlugin, PluginManager, SubAgentPreset, registry
from webui.routes.auth import require_auth
from webui.routes.scope import ScopeRoutes


@pytest.fixture(autouse=True)
def isolated_components(monkeypatch):
    monkeypatch.setattr(registry, "_plugin_components", {})


@pytest.mark.anyio
async def test_plugin_lifecycle_keeps_definitions_and_scope_runtime_only(tmp_path):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    ctx = SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store))
    manager = PluginManager(ctx)
    preset = SubAgentPreset(
        name="Coding", instruction_source="custom", instruction="Write code", scope={"allow": ["allowed-session"]},
    )
    item = await manager.register_plugin_subagent("coding", preset)
    assert not store.path.exists()
    user = await store.save(StoredSubAgentPreset(name="User"))
    data = json.loads(store.path.read_text(encoding="utf-8"))
    assert set(data) == {user["id"]}
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
    await restored.replace_scopes({})
    assert restored.path.read_bytes() == snapshot
    ctx.subagent_mgr.presets = restored
    reloaded = await manager.register_plugin_subagent("coding", preset)
    assert reloaded["id"] == item["id"]
    assert restored.is_preset_allowed(item["id"], "allowed-session")
    assert not restored.is_preset_allowed(item["id"], "other-session")
    assert restored.get_scopes() == {}
    await manager.unregister_plugin_subagent("coding", item["id"])
    assert json.loads(restored.path.read_text(encoding="utf-8")) == {user["id"]: data[user["id"]]}
    assert registry._plugin_components["coding"].subagents == {}


@pytest.mark.anyio
async def test_scope_editor_cannot_change_plugin_owned_scope_even_with_stale_snapshot(tmp_path):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    manager = PluginManager(SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store)))
    preset = SubAgentPreset(name="Coding", scope={"allow": ["allowed-session"]})
    item = await manager.register_plugin_subagent("coding", preset)
    user = await store.save(StoredSubAgentPreset(name="User"))
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    ScopeRoutes(app, SimpleNamespace(
        subagent_manager=SimpleNamespace(presets=store),
        mcp_manager=None, skills_manager=None, session_manager=None,
    )).register()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/scope")).json()["subagent_presets"] == [
            {"id": user["id"], "name": "User", "enabled": True},
        ]
        await manager._cleanup_plugin_runtime_components("coding")
        stale = (await client.get("/api/scope")).json()
        await manager.register_plugin_subagent("coding", preset)
        response = await client.put("/api/scope", json={"subagent_scopes": stale["subagent_scopes"]})
        assert response.status_code == 200
        assert not store.is_preset_allowed(item["id"], "other-session")
        forged = await client.put("/api/scope", json={"subagent_scopes": {item["id"]: {"deny": []}}})
        assert forged.status_code == 400
        assert not store.is_preset_allowed(item["id"], "other-session")
        changed = await client.put("/api/scope", json={"subagent_scopes": {user["id"]: {"allow": []}}})
        assert changed.status_code == 200
        assert store.get_scopes() == {user["id"]: {"allow": []}}
        assert item["id"] not in json.loads(store.path.read_text(encoding="utf-8"))["_scope"]


@pytest.mark.anyio
@pytest.mark.parametrize("scope,allowed", [
    (None, True), ({"allow": []}, False), ({"allow": ["session"]}, True),
    ({"deny": []}, True), ({"deny": ["session"]}, False),
])
async def test_plugin_scope_controls_discovery_and_is_copied_from_configuration(tmp_path, scope, allowed):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    manager = PluginManager(SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store)))
    preset = SubAgentPreset(name="Coding", scope=scope)
    item = await manager.register_plugin_subagent("coding", preset)
    if scope is not None:
        next(iter(scope.values())).clear()
    assert store.is_preset_allowed(item["id"], "session") is allowed
    assert store.has_available_presets("session") is allowed
    if allowed:
        assert store.get_enabled_by_name("Coding", session_id="session")[0] == item["id"]
    else:
        with pytest.raises(PermissionError):
            store.get_enabled_by_name("Coding", session_id="session")
    assert store.get_scopes() == {}
    assert not store.path.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("scope", [
    {}, [], {"allow": [], "deny": []}, {"bad": []}, {"allow": "session"},
    {"allow": [1]}, {"allow": [" "]},
])
async def test_plugin_scope_rejects_invalid_rules_before_registration(tmp_path, scope):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    manager = PluginManager(SimpleNamespace(subagent_mgr=SimpleNamespace(presets=store)))
    with pytest.raises(ValueError):
        await manager.register_plugin_subagent("coding", SubAgentPreset(name="Coding", scope=scope))
    assert store.list() == []
    assert registry._plugin_components == {}
    assert not store.path.exists()


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
