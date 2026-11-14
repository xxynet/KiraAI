import copy
import json
from types import SimpleNamespace

import pytest

from core.config import ConfigError, config_loader
from core.config.config_loader import KiraConfig
from core.plugin.plugin_context import PluginContext
from core.provider import (
    EmbeddingModelClient,
    ImageModelClient,
    LLMModelClient,
    ModelType,
    ProviderManager,
)


class StubConfig(dict):
    def get_config(self, key: str):
        value = self
        for part in key.split("."):
            value = value[part]
        return value


def build_provider_manager() -> ProviderManager:
    manager = object.__new__(ProviderManager)
    manager.kira_config = StubConfig(
        {
            "providers": {
                "provider": {
                    "name": "Test Provider",
                    "provider_config": {},
                    "model_config": {
                        "image": {"duplicate-model": {"group": "image"}},
                        "llm": {"duplicate-model": {"group": "llm"}},
                    },
                }
            }
        }
    )
    return manager


def test_get_model_info_filters_duplicate_model_ids_by_model_type():
    manager = build_provider_manager()

    image_info = manager.get_model_info(
        "provider", "duplicate-model", ModelType.IMAGE
    )
    string_image_info = manager.get_model_info(
        "provider", "duplicate-model", "image"
    )
    legacy_info = manager.get_model_info("provider", "duplicate-model")

    assert image_info.model_type is ModelType.IMAGE
    assert image_info.model_config["group"] == "image"
    assert string_image_info.model_type is ModelType.IMAGE
    assert string_image_info.model_config["group"] == "image"
    assert legacy_info.model_type is ModelType.IMAGE
    assert legacy_info.model_config["group"] == "image"


@pytest.mark.parametrize("model_id", ["duplicate-model", "duplicate:model.v1"])
@pytest.mark.parametrize("target_present", [True, False])
@pytest.mark.parametrize(
    "getter,model_type,client_type",
    [
        ("get_llm_client", ModelType.LLM, LLMModelClient),
        ("get_embedding_client", ModelType.EMBEDDING, EmbeddingModelClient),
    ],
)
def test_plugin_model_lookup_filters_by_known_type(
    getter, model_type, client_type, target_present, model_id,
):
    manager = build_provider_manager()
    model_config = manager.kira_config["providers"]["provider"]["model_config"]
    model_config.clear()
    model_config.update({
        kind.value: {model_id: {"group": kind.value}}
        for kind in (ModelType.IMAGE, ModelType.LLM, ModelType.EMBEDDING)
    })
    if not target_present:
        model_config.pop(model_type.value)
    manager._providers = {
        "provider": SimpleNamespace(models={
            ModelType.IMAGE: ImageModelClient,
            ModelType.LLM: LLMModelClient,
            ModelType.EMBEDDING: EmbeddingModelClient,
        }),
    }
    context = object.__new__(PluginContext)
    context.provider_mgr = manager

    client = getattr(context, getter)(f"provider:{model_id}")

    if target_present:
        assert isinstance(client, client_type)
        assert client.model.model_id == model_id
        assert client.model.model_type is model_type
        assert client.model.model_config["group"] == model_type.value
    else:
        assert client is None

class SavingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.saved = 0

    def get_config(self, key: str):
        value = self
        for part in key.split("."):
            value = value[part]
        return value

    def save_config(self, **kwargs):
        self.saved += 1


def test_default_models_without_references_only_matches_given_models():
    manager = object.__new__(ProviderManager)
    manager.kira_config = SavingConfig({
        "providers": {"p": {}, "q": {}},
        "models": {
            "default_llm": "p:m1",
            "default_fast_llm": "p:m2",
            "default_tts": "q:t1",
            "default_vlm": None,
        },
    })
    models = manager.kira_config["models"]

    result = manager._default_models_without_references("p", {"m1"})

    assert result["default_llm"] is None
    assert result["default_fast_llm"] == "p:m2"
    assert result["default_tts"] == "q:t1"
    assert result["default_vlm"] is None
    assert result is not models
    # the helper only returns a cleaned copy; live config stays untouched
    assert manager.kira_config["models"] is models
    assert models["default_llm"] == "p:m1"
    assert manager._default_models_without_references("p", {"missing"}) is None
    assert manager.kira_config.saved == 0


@pytest.fixture
def file_manager(monkeypatch, tmp_path):
    path = tmp_path / "system_config.json"
    path.write_text(json.dumps({
        "providers": {
            "p": {"name": "P", "provider_config": {}, "model_config": {}},
            "q": {"name": "Q", "provider_config": {}, "model_config": {}},
        },
        "models": {
            "default_llm": "p:m1",
            "default_tts": "p:m2",
            "default_vlm": "q:v1",
        },
    }), encoding="utf-8")
    monkeypatch.setattr(config_loader, "CONFIG_PATH", path)
    manager = object.__new__(ProviderManager)
    manager.kira_config = KiraConfig({"providers": {}, "models": {}})
    manager._providers = {"p": object(), "q": object()}
    return manager


def test_delete_provider_clears_defaults_in_one_save(file_manager, monkeypatch):
    manager = file_manager
    saves = []
    original_save = KiraConfig.save_config

    def record_save(self, **kwargs):
        saves.append(copy.deepcopy(dict(self)))
        return original_save(self, **kwargs)

    monkeypatch.setattr(KiraConfig, "save_config", record_save)

    assert manager.delete_provider("p") is True

    assert len(saves) == 1
    config = manager.kira_config
    assert "p" not in config["providers"]
    assert config["models"]["default_llm"] is None
    assert config["models"]["default_tts"] is None
    assert config["models"]["default_vlm"] == "q:v1"
    assert "p" not in manager._providers
    assert "q" in manager._providers

    persisted = json.loads(config_loader.CONFIG_PATH.read_text(encoding="utf-8"))
    assert persisted == saves[0] == dict(config)
    assert "p" not in persisted["providers"]
    assert persisted["models"]["default_llm"] is None
    assert persisted["models"]["default_tts"] is None
    assert persisted["models"]["default_vlm"] == "q:v1"


def test_delete_provider_save_failure_keeps_config_and_runtime(file_manager, monkeypatch):
    manager = file_manager
    original_file = config_loader.CONFIG_PATH.read_bytes()
    providers = manager.kira_config["providers"]
    models = manager.kira_config["models"]

    def fail_replace(*args, **kwargs):
        raise PermissionError("Simulated configuration write failure")

    monkeypatch.setattr(config_loader.os, "replace", fail_replace)

    with pytest.raises(ConfigError):
        manager.delete_provider("p")

    # in-memory config and runtime registry are restored exactly
    assert manager.kira_config["providers"] is providers
    assert list(providers) == ["p", "q"]
    assert manager.kira_config["models"] is models
    assert models["default_llm"] == "p:m1"
    assert models["default_tts"] == "p:m2"
    assert models["default_vlm"] == "q:v1"
    assert config_loader.CONFIG_PATH.read_bytes() == original_file
    assert "p" in manager._providers
    assert "q" in manager._providers
