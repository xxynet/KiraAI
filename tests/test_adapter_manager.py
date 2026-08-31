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


class _CancellationResistantStartAdapter:
    def __init__(self, release_event):
        self.release_event = release_event
        self.stop_calls = 0

    async def start(self):
        try:
            await self.release_event.wait()
        except asyncio.CancelledError:
            await self.release_event.wait()

    async def stop(self):
        self.stop_calls += 1


@pytest.mark.asyncio
async def test_stop_adapter_bounds_wait_for_cancellation_resistant_start_task(monkeypatch):
    monkeypatch.setattr("core.adapter.adapter_registry.ADAPTER_STOP_TIMEOUT", 0.01)
    release_event = asyncio.Event()
    adapter = _CancellationResistantStartAdapter(release_event)
    manager = object.__new__(AdapterManager)
    manager._adapters = {"test": adapter}
    start_task = asyncio.create_task(adapter.start())
    manager._adapter_tasks = {"test": start_task}
    await asyncio.sleep(0)

    await manager.stop_adapter("test")

    assert adapter.stop_calls == 1
    assert "test" not in manager._adapters
    release_event.set()
    await start_task


class _BlockingStopAdapter:
    async def stop(self):
        await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_delete_adapter_uses_bounded_stop(monkeypatch):
    monkeypatch.setattr("core.adapter.adapter_registry.ADAPTER_STOP_TIMEOUT", 0.01)
    adapter_id = "blocked-adapter"
    manager = object.__new__(AdapterManager)
    manager._adapters = {"blocked": _BlockingStopAdapter()}
    manager._adapter_tasks = {}
    manager.kira_config = _SavingConfig(
        {"adapters": {adapter_id: {"name": "blocked"}}}
    )
    manager.adas_config = manager.kira_config["adapters"]

    assert await manager.delete_adapter(adapter_id) is True
    assert "blocked" not in manager._adapters
    assert adapter_id not in manager.kira_config["adapters"]
    assert manager.kira_config.save_count == 1
