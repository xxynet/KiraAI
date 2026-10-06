"""Regression tests for immutable identities, API names, and legacy migrations."""

import copy
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.config import ConfigError, config_loader
from core.config.config_field import build_fields
from core.provider.model_identity import DEFAULT_MODEL_TYPES, resolve_model_reference
from core.provider.model_migration import (
    migrate_model_config, migrate_model_select_fields, migrate_model_config_file,
)
from core.provider import model_migration
from core.config.config_loader import KiraConfig
from core.plugin import manager as plugin_manager_module
from core.plugin.manager import PluginManager
from core.provider import BaseProvider, LLMModelClient, ModelType, ProviderManager
from core.provider.llm_model import LLMRequest
from core.provider.openai_compatible import OpenAICompatibleLLMClient
from webui.routes.auth import require_auth
from webui.routes.config import ConfigRoutes
from webui.routes.providers import ProvidersRoutes


NAME = "upstream/model.v1:variant"


def legacy_config():
    return {
        "providers": {
            "provider": {
                "format": "stub", "name": "Test Provider", "status": "inactive",
                "provider_config": {"option": "preserved"},
                "model_config": {
                    kind.value: {NAME: {"timeout": 42, "nested": {"value": True}}}
                    for kind in ModelType
                },
            },
        },
        "models": {key: f"provider:{NAME}" for key in DEFAULT_MODEL_TYPES},
    }


class StubProvider(BaseProvider):
    models = {ModelType.LLM: LLMModelClient}


@pytest.fixture
def model_manager(monkeypatch, tmp_path):
    path = tmp_path / "system_config.json"
    path.write_text(json.dumps(legacy_config()), encoding="utf-8")
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    monkeypatch.setattr(ProviderManager, "_registry", {"stub": StubProvider})
    monkeypatch.setattr(ProviderManager, "_schemas", {"stub": {"provider_config": []}})
    monkeypatch.setattr(ProviderManager, "_manifests", {})
    monkeypatch.setattr(ProviderManager, "_manifest_dirs", {})
    manager = object.__new__(ProviderManager)
    manager.kira_config = KiraConfig({"providers": {}, "models": {}})
    manager._providers = {}
    manager.providers_config = manager.kira_config["providers"]
    manager._load_providers()
    return manager


@pytest.fixture
def api(model_manager):
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "test"
    lifecycle = SimpleNamespace(kira_config=model_manager.kira_config, provider_manager=model_manager)
    ProvidersRoutes(app, lifecycle).register()
    ConfigRoutes(app, lifecycle).register()
    with TestClient(app) as client:
        yield client


def test_migration_persists_unique_ids_and_all_typed_default_references(model_manager, monkeypatch):
    config = model_manager.kira_config
    provider = config["providers"]["provider"]
    assert provider["status"] == "inactive"
    assert provider["provider_config"] == {"option": "preserved"}
    assert provider["model_config_version"] == 2
    ids = set()
    for key, kind in DEFAULT_MODEL_TYPES.items():
        reference = config["models"][key]
        info = model_manager.get_default_model_info(key)
        assert info.model_type.value == kind
        assert reference == f"provider:{info.model_id}"
        assert info.model_id != NAME
        assert info.model_name == NAME
        assert info.model_config == {"timeout": 42, "nested": {"value": True}}
        ids.add(info.model_id)
    assert len(ids) == len(ModelType)
    assert model_manager.get_model_info("provider", NAME) is None
    assert model_manager.get_model_info("provider", NAME, "llm").model_name == NAME
    saved = config_loader.CONFIG_PATH.read_bytes()
    assert json.loads(saved) == dict(config)
    backup = config_loader.CONFIG_PATH.with_name(config_loader.CONFIG_PATH.name + ".model-identity-v1.bak")
    assert json.loads(backup.read_text(encoding="utf-8")) == legacy_config()
    assert not migrate_model_config(config)

    def fail_save(*args, **kwargs):
        raise AssertionError("An unchanged migrated configuration must not be rewritten")

    monkeypatch.setattr(KiraConfig, "save_config", fail_save)
    reloaded = KiraConfig({"providers": {}, "models": {}})
    monkeypatch.setattr(model_migration, "write_migrated_model_config", fail_save)
    assert not migrate_model_config_file(reloaded, config_loader.CONFIG_PATH)
    assert reloaded == config
    assert config_loader.CONFIG_PATH.read_bytes() == saved


def test_migration_failure_preserves_original_file_and_cleans_temporary_file(monkeypatch, tmp_path):
    path = tmp_path / "system_config.json"
    original = json.dumps(legacy_config()).encode()
    path.write_bytes(original)
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)

    original_replace = config_loader.os.replace

    def fail_replace(source, destination):
        if str(destination) == str(path):
            raise PermissionError("Simulated replacement failure")
        return original_replace(source, destination)

    monkeypatch.setattr(config_loader.os, "replace", fail_replace)
    config = KiraConfig({"providers": {}, "models": {}})
    original_config = copy.deepcopy(dict(config))
    with pytest.raises(ConfigError, match="failed to save migrated model configuration"):
        migrate_model_config_file(config, path)
    assert dict(config) == original_config
    assert path.read_bytes() == original
    assert not list(tmp_path.glob(".system_config-*.tmp"))


def test_plugin_migration_only_changes_schema_model_fields(model_manager, monkeypatch, tmp_path):
    fields = build_fields({
        "selection": {"type": "model_select", "model_type": "llm"},
        "backups": {"type": "multi_select", "source": "model", "model_type": "llm"},
        "text": {"type": "string"},
        "nested": {"type": "section", "fields": {
            "embedding": {"type": "model_select", "model_type": "embedding"},
            "text": {"type": "string"},
        }},
    })
    reference = f"provider:{NAME}"
    cfg = {"selection": reference, "backups": [reference, "missing:model"], "text": reference,
           "nested": {"embedding": reference, "text": reference}}
    directory = tmp_path / "plugins"
    directory.mkdir()
    path = directory / "test.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    monkeypatch.setattr(plugin_manager_module, "PLUGIN_CONFIG_DIR", directory)
    manager = object.__new__(PluginManager)
    manager.ctx = SimpleNamespace(config=model_manager.kira_config)
    manager.plugin_configs = {}
    manager._ensure_plugin_config("test", fields)
    migrated = manager.plugin_configs["test"]
    assert migrated["selection"] == model_manager.kira_config["models"]["default_llm"]
    assert migrated["backups"] == [migrated["selection"], "missing:model"]
    assert migrated["nested"]["embedding"] == model_manager.kira_config["models"]["default_embedding"]
    assert migrated["text"] == migrated["nested"]["text"] == reference
    assert json.loads(path.read_text(encoding="utf-8")) == migrated
    assert not migrate_model_select_fields(migrated, fields, model_manager.kira_config["providers"])


def test_rename_keeps_internal_id_default_selection_and_legacy_alias(api, model_manager):
    reference = model_manager.kira_config["models"]["default_llm"]
    model_id = reference.split(":", 1)[1]
    response = api.put(f"/api/providers/provider/models/llm/{model_id}", json={
        "model_name": "new-upstream-name", "config": {"timeout": 99},
    })
    assert response.status_code == 200
    assert model_manager.kira_config["models"]["default_llm"] == reference
    info = model_manager.get_default_model_info("default_llm")
    assert info.model_id == model_id
    assert info.model_name == "new-upstream-name"
    assert info.model_config == {"timeout": 99}
    assert model_manager.get_model_info("provider", NAME, "llm").model_id == model_id
    assert model_manager.get_provider("provider") is None
    listed = api.get("/api/providers/provider/models").json()["llm"]
    assert listed[model_id] == {"model_name": "new-upstream-name", "config": {"timeout": 99}}
    assert "legacy_ids" not in listed[model_id]
    reloaded = KiraConfig({"providers": {}, "models": {}})
    assert reloaded["models"]["default_llm"] == reference
    entry = reloaded["providers"]["provider"]["model_config"]["llm"][model_id]
    assert entry["model_name"] == "new-upstream-name"
    assert entry["legacy_ids"] == [NAME]
    llm = object.__new__(OpenAICompatibleLLMClient)
    llm.model = info
    assert llm._build_request_kwargs(LLMRequest(messages=[]))["model"] == "new-upstream-name"


@pytest.mark.parametrize("field", ["model_name", "model_id"])
def test_create_allocates_id_and_accepts_legacy_create_field(api, model_manager, field):
    response = api.post("/api/providers/provider/models", json={
        "model_type": "llm", field: "created-model", "config": {"timeout": 9},
    })
    assert response.status_code == 200
    model_id = response.json()["model_id"]
    assert model_id != "created-model"
    info = model_manager.get_model_info("provider", model_id, "llm")
    assert info.model_name == "created-model"
    assert info.model_config["timeout"] == 9
    assert api.delete(f"/api/providers/provider/models/llm/{model_id}").status_code == 200
    assert model_manager.get_model_info("provider", model_id, "llm") is None


def test_remote_sync_matches_names_and_preserves_existing_identity_and_config(api, model_manager):
    old = model_manager.get_model_info("provider", NAME, "llm")
    response = api.post("/api/providers/provider/models/sync/llm", json={
        "add_ids": [NAME, "new-model"], "delete_ids": [],
    })
    assert response.status_code == 200
    assert response.json()["added"] == 1
    assert model_manager.get_model_info("provider", old.model_id, "llm").model_config == old.model_config
    models = model_manager.get_models("provider")["llm"]
    new_id = next(key for key, entry in models.items() if entry["model_name"] == "new-model")
    again = api.post("/api/providers/provider/models/sync/llm", json={"add_ids": ["new-model"]})
    assert again.json()["added"] == 0
    assert new_id in model_manager.get_models("provider")["llm"]
    removed = api.post("/api/providers/provider/models/sync/llm", json={"delete_ids": ["new-model"]})
    assert removed.json()["removed"] == 1
    assert model_manager.get_model_info("provider", new_id, "llm") is None


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("operation", ["create", "update", "delete", "sync"])
def test_model_save_failure_returns_error_without_changing_memory_or_disk(
    api, model_manager, monkeypatch, operation, enabled,
):
    if enabled:
        provider = model_manager.kira_config["providers"]["provider"]
        provider["status"] = "active"
        model_manager.set_provider("provider", provider)
        model_manager.kira_config.save_config()
    runtime_provider = model_manager.get_provider("provider")
    original = copy.deepcopy(dict(model_manager.kira_config))
    original_file = config_loader.CONFIG_PATH.read_bytes()
    model_id = model_manager.get_model_info("provider", NAME, "llm").model_id

    def fail_open(*args, **kwargs):
        raise PermissionError("Simulated model save failure")

    monkeypatch.setattr(config_loader, "open", fail_open, raising=False)
    url = f"/api/providers/provider/models/llm/{model_id}"
    if operation == "create":
        response = api.post("/api/providers/provider/models", json={"model_type": "llm", "model_name": "new"})
    elif operation == "update":
        response = api.put(url, json={"model_name": "new", "config": {}})
    elif operation == "delete":
        response = api.delete(url)
    else:
        response = api.post("/api/providers/provider/models/sync/llm", json={"add_ids": ["new"]})
    assert response.status_code == 500
    assert response.json()["detail"] == "Failed to save model configuration"
    assert dict(model_manager.kira_config) == original
    assert config_loader.CONFIG_PATH.read_bytes() == original_file
    assert model_manager.get_provider("provider") is runtime_provider


def test_missing_and_ambiguous_legacy_references_are_preserved(model_manager):
    providers = model_manager.kira_config["providers"]
    reference = f"provider:{NAME}"
    assert resolve_model_reference(providers, reference) == reference
    assert resolve_model_reference(providers, reference, "llm") != reference
    assert resolve_model_reference(providers, "missing:model", "llm") == "missing:model"


def test_invalid_names_are_rejected_and_default_api_normalizes_legacy_reference(api, model_manager):
    model_id = model_manager.get_model_info("provider", NAME, "llm").model_id
    for name in ("", "   "):
        assert api.post("/api/providers/provider/models", json={"model_type": "llm", "model_name": name}).status_code in (400, 422)
        assert api.put(f"/api/providers/provider/models/llm/{model_id}", json={"model_name": name}).status_code in (400, 422)
    response = api.post("/api/configuration", json={"models": {"default_llm": f"provider:{NAME}"}})
    assert response.status_code == 200
    assert response.json()["configuration"]["models"]["default_llm"] == f"provider:{model_id}"

def test_rename_without_config_preserves_parameters(api, model_manager):
    info = model_manager.get_model_info("provider", NAME, "llm")
    response = api.put(f"/api/providers/provider/models/llm/{info.model_id}", json={"model_name": "renamed"})
    assert response.status_code == 200
    updated = model_manager.get_model_info("provider", info.model_id, "llm")
    assert updated.model_name == "renamed"
    assert updated.model_config == info.model_config


def test_plugin_migration_save_failure_preserves_source_and_cache(model_manager, monkeypatch, tmp_path):
    fields = build_fields({"selection": {"type": "model_select", "model_type": "llm"}})
    directory = tmp_path / "plugins"
    directory.mkdir()
    path = directory / "test.json"
    original = json.dumps({"selection": f"provider:{NAME}"}).encode()
    path.write_bytes(original)
    monkeypatch.setattr(plugin_manager_module, "PLUGIN_CONFIG_DIR", directory)
    manager = object.__new__(PluginManager)
    manager.ctx = SimpleNamespace(config=model_manager.kira_config)
    manager.plugin_configs = {}

    def fail_replace(*args):
        raise PermissionError("Simulated plugin migration failure")

    monkeypatch.setattr(plugin_manager_module.os, "replace", fail_replace)
    with pytest.raises(ConfigError, match="failed to save plugin model references"):
        manager._ensure_plugin_config("test", fields)
    assert path.read_bytes() == original
    assert manager.plugin_configs == {}
    assert not list(directory.glob(".*.tmp"))


@pytest.mark.parametrize("field", ["model_name", "model_id"])
@pytest.mark.parametrize("padding", ["", "  "])
def test_create_rejects_duplicate_names_without_changing_existing_models(api, model_manager, field, padding):
    original = copy.deepcopy(dict(model_manager.kira_config))
    saved = config_loader.CONFIG_PATH.read_bytes()
    response = api.post("/api/providers/provider/models", json={
        "model_type": "llm", field: f"{padding}{NAME}{padding}", "config": {"timeout": 10},
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Model name already exists"
    assert dict(model_manager.kira_config) == original
    assert config_loader.CONFIG_PATH.read_bytes() == saved


def test_rename_rejects_duplicate_but_accepts_unchanged_name(api, model_manager):
    response = api.post("/api/providers/provider/models", json={
        "model_type": "llm", "model_name": "second-model", "config": {"timeout": 10},
    })
    model_id = response.json()["model_id"]
    original = copy.deepcopy(dict(model_manager.kira_config))
    saved = config_loader.CONFIG_PATH.read_bytes()
    response = api.put(f"/api/providers/provider/models/llm/{model_id}", json={
        "model_name": f"  {NAME}  ", "config": {"timeout": 99},
    })
    assert response.status_code == 400
    assert dict(model_manager.kira_config) == original
    assert config_loader.CONFIG_PATH.read_bytes() == saved
    response = api.put(f"/api/providers/provider/models/llm/{model_id}", json={
        "model_name": "second-model", "config": {"timeout": 20},
    })
    assert response.status_code == 200
    assert model_manager.get_model_info("provider", model_id, "llm").model_config["timeout"] == 20


def test_same_name_is_allowed_in_different_providers_or_model_types(api, model_manager):
    assert api.post("/api/providers/provider/models", json={
        "model_type": "llm", "model_name": "shared-name",
    }).status_code == 200
    assert api.post("/api/providers/provider/models", json={
        "model_type": "embedding", "model_name": "shared-name",
    }).status_code == 200
    second = copy.deepcopy(model_manager.kira_config["providers"]["provider"])
    model_manager.kira_config["providers"]["second"] = second
    assert model_manager.register_model("second", "llm", "other-name")
    assert model_manager.register_model("provider", "llm", "other-name")


def test_remote_sync_cannot_remove_preexisting_duplicate_entries(api, model_manager):
    models = model_manager.kira_config["providers"]["provider"]["model_config"]["llm"]
    models["duplicate-id"] = {"model_name": NAME, "config": {"timeout": 99}}
    model_manager.kira_config.save_config()
    original = copy.deepcopy(dict(model_manager.kira_config))
    saved = config_loader.CONFIG_PATH.read_bytes()
    response = api.post("/api/providers/provider/models/sync/llm", json={
        "add_ids": ["new-model"], "delete_ids": [NAME],
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "Model name already exists"
    assert dict(model_manager.kira_config) == original
    assert config_loader.CONFIG_PATH.read_bytes() == saved


def test_remote_sync_repeated_name_adds_only_one_entry(api, model_manager):
    response = api.post("/api/providers/provider/models/sync/llm", json={
        "add_ids": ["new-model", "new-model", "  new-model  "],
    })
    assert response.status_code == 200
    assert response.json()["added"] == 1
    models = model_manager.get_models("provider")["llm"]
    assert sum(entry["model_name"] == "new-model" for entry in models.values()) == 1


def test_migration_rejects_invalid_entries_without_writing_or_losing_original(monkeypatch, tmp_path):
    config = legacy_config()
    config["providers"]["provider"]["model_config"]["llm"][NAME] = "invalid"
    path = tmp_path / "system_config.json"
    original = json.dumps(config).encode()
    path.write_bytes(original)
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"providers": {}, "models": {}})
    with pytest.raises(ConfigError, match="failed to migrate model configuration"):
        migrate_model_config_file(config, path)
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".model-identity-v1.bak").exists()

def test_failed_backup_leaves_original_config_and_can_be_retried(monkeypatch, tmp_path):
    path = tmp_path / "system_config.json"
    original = json.dumps(legacy_config()).encode()
    path.write_bytes(original)
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    original_copy = model_migration.shutil.copyfileobj

    def fail_copy(source, destination):
        destination.write(b"partial")
        raise OSError("Simulated backup copy failure")

    monkeypatch.setattr(model_migration.shutil, "copyfileobj", fail_copy)
    config = KiraConfig({"providers": {}, "models": {}})
    with pytest.raises(ConfigError, match="failed to back up model configuration"):
        migrate_model_config_file(config, path)
    backup_path = path.with_name(path.name + ".model-identity-v1.bak")
    assert not backup_path.exists()
    assert not list(tmp_path.glob(".model_backup-*.tmp"))
    assert path.read_bytes() == original
    monkeypatch.setattr(model_migration.shutil, "copyfileobj", original_copy)
    assert migrate_model_config_file(config, path)
    assert backup_path.read_bytes() == original

def test_config_loader_does_not_migrate_provider_models(monkeypatch, tmp_path):
    path = tmp_path / "system_config.json"
    original = json.dumps(legacy_config()).encode()
    path.write_bytes(original)
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    config = KiraConfig({"providers": {}, "models": {}})
    assert dict(config) == legacy_config()
    assert path.read_bytes() == original
    assert not path.with_name(path.name + ".model-identity-v1.bak").exists()


@pytest.mark.parametrize("invalid", [None, [], ["default_llm"], "", "default_llm", 0, 1, False, True])
def test_migration_rejects_non_dict_model_selections_before_writing(tmp_path, invalid):
    config = legacy_config()
    config["models"] = invalid
    original = copy.deepcopy(config)
    path = tmp_path / "system_config.json"
    saved = json.dumps(config).encode()
    path.write_bytes(saved)
    with pytest.raises(ConfigError, match="failed to migrate model configuration") as error:
        migrate_model_config_file(config, path)
    assert isinstance(error.value.__cause__, ValueError)
    assert config == original
    assert path.read_bytes() == saved
    assert not path.with_name(path.name + ".model-identity-v1.bak").exists()
    assert not list(tmp_path.glob("*.tmp"))


def test_restoring_main_backup_preserves_migrated_plugin_references(model_manager, monkeypatch, tmp_path):
    fields = build_fields({
        "selection": {"type": "model_select", "model_type": "llm"},
        "fallbacks": {"type": "multi_select", "source": "model", "model_type": "llm"},
        "embedding": {"type": "model_select", "model_type": "embedding"},
    })
    directory = tmp_path / "plugins"
    directory.mkdir()
    plugin_path = directory / "test.json"
    plugin_path.write_text(json.dumps({
        "selection": f"provider:{NAME}", "fallbacks": [f"provider:{NAME}"],
        "embedding": f"provider:{NAME}",
    }), encoding="utf-8")
    monkeypatch.setattr(plugin_manager_module, "PLUGIN_CONFIG_DIR", directory)
    plugin_manager = object.__new__(PluginManager)
    plugin_manager.ctx = SimpleNamespace(config=model_manager.kira_config)
    plugin_manager.plugin_configs = {}
    plugin_manager._ensure_plugin_config("test", fields)
    plugin_bytes = plugin_path.read_bytes()
    selections = copy.deepcopy(plugin_manager.plugin_configs["test"])
    original_models = copy.deepcopy(model_manager.kira_config["models"])
    original_ids = {
        kind: set(models)
        for kind, models in model_manager.kira_config["providers"]["provider"]["model_config"].items()
    }
    path = config_loader.CONFIG_PATH
    backup = path.with_name(path.name + ".model-identity-v1.bak")
    path.write_bytes(backup.read_bytes())
    model_manager.kira_config = KiraConfig({"providers": {}, "models": {}})
    model_manager._load_providers()
    assert model_manager.kira_config["models"] == original_models
    for kind, models in model_manager.kira_config["providers"]["provider"]["model_config"].items():
        assert set(models) == original_ids[kind]
    for key, kind in (("selection", "llm"), ("embedding", "embedding")):
        provider_id, model_id = selections[key].split(":", 1)
        info = model_manager.get_model_info(provider_id, model_id, kind)
        assert info is not None
        assert info.model_name == NAME
    assert selections["fallbacks"] == [selections["selection"]]
    plugin_manager.ctx.config = model_manager.kira_config
    plugin_manager._ensure_plugin_config("test", fields)
    assert plugin_manager.plugin_configs["test"] == selections
    assert plugin_path.read_bytes() == plugin_bytes


def test_legacy_migration_identity_does_not_depend_on_model_parameters():
    first = legacy_config()
    second = copy.deepcopy(first)
    second["providers"]["provider"]["model_config"]["llm"][NAME]["timeout"] = 99
    assert migrate_model_config(first)
    assert migrate_model_config(second)
    assert first["models"] == second["models"]
    for kind in first["providers"]["provider"]["model_config"]:
        assert set(first["providers"]["provider"]["model_config"][kind]) == set(
            second["providers"]["provider"]["model_config"][kind]
        )


def test_migration_rejects_duplicate_modern_names_without_discarding_entries(tmp_path):
    config = legacy_config()
    assert migrate_model_config(config)
    models = config["providers"]["provider"]["model_config"]["llm"]
    models["duplicate-id"] = {"model_name": NAME, "config": {"timeout": 99}}
    original = copy.deepcopy(config)
    path = tmp_path / "system_config.json"
    saved = json.dumps(config).encode()
    path.write_bytes(saved)
    with pytest.raises(ConfigError, match="failed to migrate model configuration"):
        migrate_model_config_file(config, path)
    assert config == original
    assert path.read_bytes() == saved
    assert not path.with_name(path.name + ".model-identity-v1.bak").exists()
