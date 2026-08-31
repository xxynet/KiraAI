import asyncio

import pytest

from core.adapter.adapter_registry import AdapterManager


def test_adapter_name_rejects_colon():
    with pytest.raises(ValueError, match="must not contain"):
        AdapterManager._validate_adapter_name("my:adapter")


def test_adapter_name_allows_regular_name():
    AdapterManager._validate_adapter_name("my-adapter")

class _NoSaveConfig(dict):
    def save_config(self):
        raise AssertionError("An unavailable adapter platform must not be persisted")


def test_update_rejects_enabling_an_unregistered_adapter_platform():
    manager = object.__new__(AdapterManager)
    manager.kira_config = _NoSaveConfig(
        {
            "adapters": {
                "plugin-adapter": {
                    "enabled": False,
                    "name": "plugin-adapter",
                    "platform": "plugin-platform-that-is-not-registered",
                    "config": {},
                }
            }
        }
    )
    manager.adas_config = manager.kira_config["adapters"]

    with pytest.raises(ValueError, match="No adapter registered"):
        asyncio.run(manager.update_adapter("plugin-adapter", status="active"))

    assert manager.kira_config["adapters"]["plugin-adapter"]["enabled"] is False
