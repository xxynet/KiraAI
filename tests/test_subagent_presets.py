import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
from webui.routes.auth import require_auth
from webui.routes.subagents import SubAgentsRoutes


@pytest.mark.anyio
async def test_preset_crud_survives_restart_without_exposing_mutable_settings(tmp_path):
    path = tmp_path / "presets.json"
    store = SubAgentPresetStore(path)
    await store.initialize()
    assert not path.exists()
    item = await store.save(SubAgentPreset(
        name=" Research ",
        instruction_source="custom",
        instruction="Study carefully",
        tool_mode="custom",
        tools=[" search ", "search"],
        model="provider:model",
        max_steps=100,
    ))
    assert item["name"] == "Research"
    assert item["tools"] == ["search"]
    assert item["max_steps"] == 100
    item["tools"].append("mutated")
    store.get(item["id"]).tools.append("mutated")
    assert store.get(item["id"]).tools == ["search"]
    restored = SubAgentPresetStore(path)
    await restored.initialize()
    assert restored.list() == store.list()
    await store.save(SubAgentPreset(
        name="Changed",
        enabled=False,
    ), item["id"])
    assert not store.list(enabled_only=True)
    await store.delete(item["id"])
    assert json.loads(path.read_text(encoding="utf-8")) == {}


@pytest.mark.anyio
async def test_failed_preset_write_keeps_previous_memory_and_disk(tmp_path, monkeypatch):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    original = await store.save(SubAgentPreset(name="Original"))
    snapshot = store.path.read_bytes()

    def fail(*_):
        raise OSError("disk failure")

    monkeypatch.setattr("core.agent.subagent_presets.os.replace", fail)
    with pytest.raises(OSError, match="disk failure"):
        await store.save(SubAgentPreset(name="New"), original["id"])
    assert store.list() == [original]
    assert store.path.read_bytes() == snapshot
    assert list(tmp_path.iterdir()) == [store.path]


@pytest.mark.anyio
async def test_concurrent_preset_creates_do_not_overwrite_each_other(tmp_path):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    items = await asyncio.gather(*(store.save(SubAgentPreset(name=str(index))) for index in range(10)))
    assert len({item["id"] for item in items}) == 10
    restored = SubAgentPresetStore(store.path)
    await restored.initialize()
    assert restored.list() == store.list()


@pytest.mark.parametrize("changes", [
    {"name": " "},
    {"max_steps": True},
    {"max_steps": 0},
    {"max_steps": -2},
    {"max_steps": "5"},
    {"tool_mode": "unknown"},
    {"tools": [None]},
    {"tools": [" "]},
    {"enabled": "true"},
    {"model": "missing-provider"},
    {"model": ":model"},
    {"model": "provider:"},
    {"model": False},
    {"model": ""},
    {"model": " "},
    {"instruction_source": "unknown"},
    {"persona_id": ""},
    {"persona_id": " "},
    {"persona_id": False},
    {"unknown": True},
])
def test_preset_validation(changes):
    with pytest.raises(ValidationError):
        SubAgentPreset.model_validate({"name": "Preset", **changes})


@pytest.mark.anyio
async def test_presets_routes_validate_persist_edit_delete_and_require_auth(tmp_path):
    store = SubAgentPresetStore(tmp_path / "presets.json")
    app = FastAPI()
    routes = SubAgentsRoutes(app, SimpleNamespace(subagent_manager=SimpleNamespace(presets=store)))
    routes.register()
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        denied = await client.get("/api/subagents/presets")
        assert denied.status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        invalid = await client.post("/api/subagents/presets", json={"name": "Bad", "max_steps": True})
        assert invalid.status_code == 422
        assert not store.list()
        created = await client.post("/api/subagents/presets", json={
            "name": "Preset",
            "instruction": "Focus",
            "model": "provider:model",
        })
        assert created.status_code == 201
        assert created.json()["model"] == "provider:model"
        assert created.json()["instruction_source"] == "persona"
        assert created.json()["persona_id"] is None
        identity = created.json()["id"]
        assert created.json()["max_steps"] == -1
        duplicate = await client.post(
            "/api/subagents/presets",
            json={"name": " Preset ", "enabled": False},
        )
        assert duplicate.status_code == 409
        listed = await client.get("/api/subagents/presets")
        assert listed.json() == {"presets": [created.json()]}
        changed = await client.put(f"/api/subagents/presets/{identity}", json={
            "name": "Changed",
            "enabled": False,
            "max_steps": 100,
        })
        assert changed.status_code == 200
        assert changed.json()["id"] == identity
        assert not changed.json()["enabled"]
        assert changed.json()["model"] is None
        assert changed.json()["max_steps"] == 100
        missing = await client.put("/api/subagents/presets/missing", json={"name": "Unknown"})
        assert missing.status_code == 404
        deleted = await client.delete(f"/api/subagents/presets/{identity}")
        assert deleted.status_code == 204
        assert not deleted.content
        missing = await client.delete(f"/api/subagents/presets/{identity}")
        assert missing.status_code == 404
        assert not store.list()
