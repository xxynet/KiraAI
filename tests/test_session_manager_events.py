import asyncio
import threading
import time
from copy import deepcopy
from threading import Lock

import pytest

import core.chat.session_manager as session_manager_module
from core.chat.session_manager import SessionManager
from core.chat.session_media_manager import SessionMediaManager


class RecordingEventBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


def build_session_manager(tmp_path, memory, max_memory_length=10):
    manager = object.__new__(SessionManager)
    manager.chat_memory = {
        "adapter:dm:user": {
            "title": "",
            "description": "",
            "timestamp": None,
            "memory": memory,
        }
    }
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    manager.max_memory_length = max_memory_length
    manager.memory_lock = Lock()
    manager._background_tasks = set()
    manager.event_bus = RecordingEventBus()
    return manager


def test_session_manager_receives_event_bus_through_constructor(tmp_path, monkeypatch):
    class Config:
        def __getitem__(self, key):
            assert key == "bot_config"
            return {"bot": {"max_memory_length": 10}}

    event_bus = RecordingEventBus()
    monkeypatch.setattr(
        session_manager_module, "CHAT_MEMORY_PATH", str(tmp_path / "chat_memory.json")
    )

    manager = SessionManager(None, Config(), event_bus=event_bus)

    assert manager.event_bus is event_bus


def test_update_session_info_allows_clearing_description(tmp_path):
    manager = build_session_manager(tmp_path, [])
    manager.chat_memory["adapter:dm:user"]["title"] = "Existing title"
    manager.chat_memory["adapter:dm:user"]["description"] = "Existing description"

    manager.update_session_info("adapter:dm:user", description="")

    session_data = manager.chat_memory["adapter:dm:user"]
    assert session_data["title"] == "Existing title"
    assert session_data["description"] == ""
    assert '"description": ""' in (
        tmp_path / "chat_memory.json"
    ).read_text(encoding="utf-8")


async def wait_for_event_tasks(manager):
    if manager._background_tasks:
        await asyncio.gather(*tuple(manager._background_tasks))


@pytest.mark.asyncio
async def test_update_memory_publishes_only_new_chunk_after_persistence(tmp_path):
    manager = build_session_manager(tmp_path, [[{"role": "user", "content": "old"}]])
    new_chunk = [{"role": "user", "content": "new"}]

    manager.update_memory("adapter:dm:user", new_chunk)
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_memory_updated"
    assert event.payload == {"session": "adapter:dm:user", "new_chunk": new_chunk}
    assert '"new"' in (tmp_path / "chat_memory.json").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_write_memory_publishes_old_and_new_memory(tmp_path):
    old_memory = [[{"role": "user", "content": "old"}]]
    new_memory = [[{"role": "user", "content": "new"}]]
    manager = build_session_manager(tmp_path, old_memory)

    manager.write_memory("adapter:dm:user", new_memory)
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_memory_written"
    assert event.payload == {
        "session": "adapter:dm:user",
        "old_memory": old_memory,
        "new_memory": new_memory,
    }


@pytest.mark.asyncio
async def test_delete_session_publishes_old_memory(tmp_path):
    old_memory = [[{"role": "user", "content": "old"}]]
    manager = build_session_manager(tmp_path, old_memory)

    manager.delete_session("adapter:dm:user")
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_deleted"
    assert event.payload == {"session": "adapter:dm:user", "old_memory": old_memory}
    assert "adapter:dm:user" not in manager.chat_memory


class SubscriptionEventBus:
    def subscribe(self, *_args):
        pass


class SnapshotSessionManager:
    def __init__(self, memory):
        self.memory = memory

    def get_existing_memory_snapshot(self, _session):
        return deepcopy(self.memory)


@pytest.mark.asyncio
async def test_session_media_cleanup_uses_latest_snapshot_and_serializes_per_session(
    monkeypatch,
):
    memory = [[{"role": "user", "content": "latest"}]]
    manager = SessionMediaManager(
        SubscriptionEventBus(), SnapshotSessionManager(memory)
    )
    calls = []
    active_count = 0
    maximum_active_count = 0
    counter_lock = threading.Lock()

    def record_cleanup(session, current_memory):
        nonlocal active_count, maximum_active_count
        with counter_lock:
            active_count += 1
            maximum_active_count = max(maximum_active_count, active_count)
        time.sleep(0.02)
        calls.append((session, current_memory))
        with counter_lock:
            active_count -= 1

    monkeypatch.setattr(
        "core.chat.session_media_manager.cleanup_session_media", record_cleanup
    )
    event = type(
        "Event",
        (),
        {
            "payload": {
                "session": "adapter:dm:user",
                "new_memory": [[{"role": "user", "content": "stale"}]],
            }
        },
    )()

    await asyncio.gather(
        manager._on_memory_written(event),
        manager._on_memory_updated(event),
    )

    assert calls == [
        ("adapter:dm:user", memory),
        ("adapter:dm:user", memory),
    ]
    assert maximum_active_count == 1
