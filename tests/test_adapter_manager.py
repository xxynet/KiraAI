import asyncio

import pytest

from core.adapter.adapter_info import AdapterInfo
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

class _SavingConfig(dict):
    def __init__(self, value):
        super().__init__(value)
        self.save_count = 0

    def save_config(self):
        self.save_count += 1


class _DelayedFailingAdapter:
    def __init__(self, info):
        self.info = info

    async def start(self):
        await asyncio.sleep(0)
        raise RuntimeError("startup failed")

    async def stop(self):
        return None


def test_delayed_adapter_start_failure_disables_the_adapter():
    adapter_id = "delayed-failure"
    info = AdapterInfo(
        enabled=True,
        adapter_id=adapter_id,
        name="delayed-failure",
        platform="test-platform",
    )
    adapter = _DelayedFailingAdapter(info)
    manager = object.__new__(AdapterManager)
    manager._adapters = {info.name: adapter}
    manager._adapter_tasks = {}
    manager.kira_config = _SavingConfig(
        {"adapters": {adapter_id: {"enabled": True}}}
    )
    manager.adas_config = manager.kira_config["adapters"]

    async def run_startup():
        await manager.start_adapter(info.name)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(run_startup())

    assert info.name not in manager._adapters
    assert info.name not in manager._adapter_tasks
    assert manager.kira_config["adapters"][adapter_id]["enabled"] is False
    assert manager.kira_config.save_count == 1
