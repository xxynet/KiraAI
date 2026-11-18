from types import SimpleNamespace

import pytest

from core.chat.session import Session
from core.plugin.plugin_context import PluginContext
from core.provider import (
    EmbeddingModelClient,
    ImageModelClient,
    LLMModelClient,
    ModelType,
    ProviderAPIError,
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


@pytest.fixture(params=["provider", "plugin"])
def default_llm_lookup(request):
    manager = build_provider_manager()
    manager.kira_config["models"] = {"default_llm": "provider:duplicate-model"}
    manager.kira_config["providers"]["provider"]["model_config"]["llm"]["session:model"] = {}
    manager._providers = {"provider": SimpleNamespace(models={ModelType.LLM: LLMModelClient})}
    context = object.__new__(PluginContext)
    context.provider_mgr = manager
    getter = manager.get_default_llm if request.param == "provider" else context.get_default_llm_client
    return manager, getter


@pytest.mark.parametrize("data", [None, {}, {"llm_model": None}])
def test_default_llm_uses_global_when_session_selection_is_unset(default_llm_lookup, data):
    _, getter = default_llm_lookup
    client = getter() if data is None else getter(Session("adapter", "dm", "user", data=data))

    assert client.model.provider_id == "provider"
    assert client.model.model_id == "duplicate-model"
    assert client.model.model_type is ModelType.LLM


@pytest.mark.parametrize("global_configured", [True, False])
def test_default_llm_prefers_session_without_requiring_global_default(default_llm_lookup, global_configured):
    manager, getter = default_llm_lookup
    if not global_configured:
        manager.kira_config["models"]["default_llm"] = ""
    session = Session("adapter", "dm", "user", data={"llm_model": "provider:session:model"})

    client = getter(session)

    assert client.model.model_id == "session:model"
    assert session.data == {"llm_model": "provider:session:model"}


@pytest.mark.parametrize("reference", ["", "invalid", "unknown:model", "provider:missing"])
def test_default_llm_does_not_hide_unavailable_session_selection(default_llm_lookup, reference):
    _, getter = default_llm_lookup
    session = Session("adapter", "dm", "user", data={"llm_model": reference})

    with pytest.raises(ValueError):
        getter(session)


def test_default_llm_rejects_disabled_session_provider(default_llm_lookup):
    manager, getter = default_llm_lookup
    manager.kira_config["providers"]["disabled"] = {"status": "inactive"}
    session = Session("adapter", "dm", "user", data={"llm_model": "disabled:model"})

    with pytest.raises(ProviderAPIError, match="disabled"):
        getter(session)
