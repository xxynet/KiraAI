"""Regression tests for ProviderManager error reporting and model listing."""

import pytest

from core.provider import ModelType, ProviderManager


class StubConfig(dict):
    def get_config(self, key: str):
        value = self
        for part in key.split("."):
            if not isinstance(value, dict) or part not in value:
                return None
            value = value[part]
        return value


def build_provider_manager(models: dict | None = None) -> ProviderManager:
    manager = object.__new__(ProviderManager)
    manager.kira_config = StubConfig(
        {
            "models": models or {},
            "providers": {
                "provider": {
                    "name": "Test Provider",
                    "provider_config": {},
                    "model_config": {"llm": {"gpt-test": {"timeout": 120}}},
                }
            },
        }
    )
    manager._providers = {}
    return manager


class StubProvider:
    def __init__(self, models: list[dict]):
        self._models = models

    async def get_llm_list(self) -> list[dict]:
        return self._models


def test_get_model_client_reports_provider_that_failed_to_load():
    manager = build_provider_manager()

    with pytest.raises(ValueError, match="not loaded"):
        manager.get_model_client("provider", "gpt-test", ModelType.LLM)


def test_get_model_client_still_returns_none_for_unknown_model():
    manager = build_provider_manager()

    assert manager.get_model_client("provider", "missing-model") is None


def test_default_model_without_provider_prefix_reports_malformed_config():
    manager = build_provider_manager({"default_llm": "gpt-test"})

    with pytest.raises(ValueError, match="malformed"):
        manager.get_default_model_info("default_llm")


def test_unset_default_model_still_reports_not_set():
    manager = build_provider_manager()

    with pytest.raises(ValueError, match="not set"):
        manager.get_default_model_info("default_llm")


def test_default_model_id_may_contain_colons_and_dots():
    manager = build_provider_manager({"default_llm": "provider:vendor/model-v1.5:free"})

    model_info = manager.get_default_model_info("default_llm")

    assert model_info.provider_id == "provider"
    assert model_info.model_id == "vendor/model-v1.5:free"
    assert model_info.model_type is ModelType.LLM


@pytest.mark.anyio
async def test_fetch_remote_models_returns_the_llm_list():
    manager = build_provider_manager()
    manager._providers["provider"] = StubProvider([{"id": "gpt-test"}])

    assert await manager.fetch_remote_models("provider", "llm") == [{"id": "gpt-test"}]


@pytest.mark.anyio
async def test_fetch_remote_models_rejects_types_without_a_list_endpoint():
    manager = build_provider_manager()
    manager._providers["provider"] = StubProvider([{"id": "gpt-test"}])

    for model_type in ("tts", "image", "embedding"):
        with pytest.raises(ValueError, match="does not support listing"):
            await manager.fetch_remote_models("provider", model_type)


@pytest.mark.anyio
async def test_fetch_remote_models_rejects_unknown_model_types():
    manager = build_provider_manager()
    manager._providers["provider"] = StubProvider([{"id": "gpt-test"}])

    with pytest.raises(ValueError, match="Unknown model type"):
        await manager.fetch_remote_models("provider", "not-a-type")
