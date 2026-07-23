from core.provider import ModelType, ProviderManager


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
