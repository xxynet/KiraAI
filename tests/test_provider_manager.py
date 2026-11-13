from types import SimpleNamespace

import pytest

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


def test_clear_default_references_only_removes_matching_models():
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

    assert manager.clear_default_references("p", {"m1"}) is True
    assert manager.kira_config["models"]["default_llm"] is None
    assert manager.kira_config["models"]["default_fast_llm"] == "p:m2"
    assert manager.kira_config["models"]["default_tts"] == "q:t1"
    assert manager.kira_config.saved == 1


def test_clear_default_references_removes_whole_provider():
    manager = object.__new__(ProviderManager)
    manager.kira_config = SavingConfig({
        "providers": {"p": {}, "q": {}},
        "models": {
            "default_llm": "p:m1",
            "default_fast_llm": "p:m2",
            "default_tts": "q:t1",
        },
    })

    assert manager.clear_default_references("p") is True
    assert manager.kira_config["models"]["default_llm"] is None
    assert manager.kira_config["models"]["default_fast_llm"] is None
    assert manager.kira_config["models"]["default_tts"] == "q:t1"
    assert manager.kira_config.saved == 1
