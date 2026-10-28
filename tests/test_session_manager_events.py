import asyncio
import threading
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from types import SimpleNamespace

import pytest

import core.chat.session_manager as session_manager_module
from core.chat.session_manager import SessionManager
from core.chat.session_media_manager import SessionMediaManager


class RecordingEventBus:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


async def build_session_manager(
    tmp_path, memory, max_memory_length=10, memory_overflow_discard_count=1, *, db,
):
    config = {"bot_config": {"bot": {
        "max_memory_length": max_memory_length,
        "memory_overflow_discard_count": memory_overflow_discard_count,
    }}}
    manager = SessionManager(db, config)
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await manager.initialize()
    await manager.update_session("adapter:dm:user", content=memory)
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


@pytest.mark.anyio
async def test_update_session_allows_clearing_description(tmp_path, session_db):
    manager = await build_session_manager(tmp_path, [], db=session_db)
    await manager.update_session("adapter:dm:user", title="Existing title", description="Existing description")

    await manager.update_session("adapter:dm:user", description="")

    session_data = await manager.get_session("adapter:dm:user")
    assert session_data.session_title == "Existing title"
    assert session_data.session_description == ""
    assert (await session_db.list_chat_sessions())[0]["description"] == ""


@pytest.mark.anyio
async def test_update_memory_discards_configured_count_when_memory_is_full(tmp_path, session_db):
    memory = [[{"role": "user", "content": str(index)}] for index in range(5)]
    manager = await build_session_manager(
        tmp_path, memory, max_memory_length=5, memory_overflow_discard_count=2, db=session_db,
    )

    await manager.update_memory("adapter:dm:user", [{"role": "user", "content": "5"}])

    retained_contents = [chunk[0]["content"] for chunk in (await manager.get_session("adapter:dm:user")).content]
    assert retained_contents == ["2", "3", "4", "5"]


@pytest.mark.anyio
async def test_update_memory_discards_configured_count_after_existing_overflow(tmp_path, session_db):
    memory = [[{"role": "user", "content": str(index)}] for index in range(7)]
    manager = await build_session_manager(
        tmp_path, memory, max_memory_length=5, memory_overflow_discard_count=2, db=session_db,
    )

    await manager.update_memory("adapter:dm:user", [{"role": "user", "content": "7"}])

    retained_contents = [chunk[0]["content"] for chunk in (await manager.get_session("adapter:dm:user")).content]
    assert retained_contents == ["4", "5", "6", "7"]


@pytest.mark.anyio
async def test_update_memory_uses_limit_lowered_at_runtime(tmp_path, session_db):
    memory = [[{"role": "user", "content": str(index)}] for index in range(5)]
    manager = await build_session_manager(tmp_path, memory, max_memory_length=5, db=session_db)
    manager.kira_config["bot_config"]["bot"]["max_memory_length"] = 3

    await manager.update_memory("adapter:dm:user", [{"role": "user", "content": "5"}])

    retained_contents = [chunk[0]["content"] for chunk in (await manager.get_session("adapter:dm:user")).content]
    assert retained_contents == ["3", "4", "5"]


async def wait_for_event_tasks(manager):
    if manager._background_tasks:
        await asyncio.gather(*tuple(manager._background_tasks))


@pytest.mark.anyio
async def test_update_memory_publishes_new_and_discarded_memory_after_persistence(tmp_path, session_db):
    manager = await build_session_manager(tmp_path, [[{"role": "user", "content": "old"}]], db=session_db)
    new_chunk = [{"role": "user", "content": "new"}]

    await manager.update_memory("adapter:dm:user", new_chunk)
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_memory_updated"
    assert event.payload == {
        "session": "adapter:dm:user",
        "new_chunk": (await manager.get_session("adapter:dm:user")).content[-1],
        "discarded_memory": [],
    }
    assert (await session_db.list_chat_sessions())[0]["content"][-1][0]["content"] == "new"


@pytest.mark.anyio
async def test_update_memory_publishes_truncated_memory_after_persistence(tmp_path, session_db):
    memory = [[{"role": "user", "content": str(index)}] for index in range(5)]
    manager = await build_session_manager(
        tmp_path, memory, max_memory_length=5, memory_overflow_discard_count=2, db=session_db,
    )
    memory = (await manager.get_session("adapter:dm:user")).content
    new_chunk = [{"role": "user", "content": "5"}]

    await manager.update_memory("adapter:dm:user", new_chunk)
    await wait_for_event_tasks(manager)

    assert manager.event_bus.events[0].payload == {
        "session": "adapter:dm:user",
        "new_chunk": (await manager.get_session("adapter:dm:user")).content[-1],
        "discarded_memory": memory[:2],
    }


@pytest.mark.anyio
async def test_update_session_content_publishes_old_and_new_memory(tmp_path, session_db):
    old_memory = [[{"role": "user", "content": "old"}]]
    new_memory = [[{"role": "user", "content": "new"}]]
    manager = await build_session_manager(tmp_path, old_memory, db=session_db)

    old_memory = (await manager.get_session("adapter:dm:user")).content
    await manager.update_session("adapter:dm:user", content=new_memory)
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_memory_written"
    assert event.payload == {
        "session": "adapter:dm:user",
        "old_memory": old_memory,
        "new_memory": (await manager.get_session("adapter:dm:user")).content,
    }


@pytest.mark.anyio
async def test_delete_session_publishes_old_memory(tmp_path, session_db):
    old_memory = [[{"role": "user", "content": "old"}]]
    manager = await build_session_manager(tmp_path, old_memory, db=session_db)

    old_memory = (await manager.get_session("adapter:dm:user")).content
    await manager.delete_session("adapter:dm:user")
    await wait_for_event_tasks(manager)

    event = manager.event_bus.events[0]
    assert event.event_type == "session_deleted"
    assert event.payload == {"session": "adapter:dm:user", "old_memory": old_memory}
    assert await manager.get_session("adapter:dm:user") is None


class SubscriptionEventBus:
    def subscribe(self, *_args):
        pass


class SnapshotSessionManager:
    def __init__(self, memory):
        self.memory = memory

    @asynccontextmanager
    async def maintenance(self):
        yield

    async def get_session(self, _session):
        return SimpleNamespace(content=deepcopy(self.memory))


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

@pytest.mark.anyio
async def test_delete_session_allows_malformed_data(tmp_path, session_db):
    sid = "adapter:dm:user"
    manager = await build_session_manager(tmp_path, [], db=session_db)
    await session_db.save_chat_session(sid, data=42)

    await manager.delete_session(sid)
    await wait_for_event_tasks(manager)

    assert await session_db.get_chat_session(sid) is None
    assert manager.event_bus.events[0].payload == {"session": sid, "old_memory": []}


@pytest.mark.anyio
@pytest.mark.parametrize("malformed", [False, True])
async def test_session_media_cleanup_handles_missing_and_malformed_sessions(
    tmp_path, session_db, monkeypatch, malformed,
):
    sid = "adapter:dm:user"
    manager = await build_session_manager(tmp_path, [], db=session_db)
    if malformed:
        await session_db.save_chat_session(sid, data=42)
    else:
        await session_db.delete_chat_session(sid)
    media = SessionMediaManager(SubscriptionEventBus(), manager)
    calls = []
    monkeypatch.setattr(
        "core.chat.session_media_manager.cleanup_session_media",
        lambda session, memory: calls.append((session, memory)),
    )

    if malformed:
        with pytest.raises(ValueError, match="Session data must be an object"):
            await media._cleanup_current_session_media(sid)
        assert calls == []
    else:
        await media._cleanup_current_session_media(sid)
        assert calls == [(sid, [])]
    assert not manager._write_lock.locked()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["update", "write", "delete"])
async def test_previous_turn_cleanup_preserves_uncommitted_image(
    tmp_path, session_db, monkeypatch, operation,
):
    from core.chat.message_elements import Image
    from core.utils import media_refs

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    sid = "adapter:dm:user"
    image = Image("data:image/png;base64,aGVsbG8=")
    old = await media_refs.store_session_media(image, sid, "old")
    manager = await build_session_manager(
        tmp_path, [[{"role": "user", "content": [old]}]],
        max_memory_length=1, db=session_db,
    )
    media = SessionMediaManager(SubscriptionEventBus(), manager)

    async with media_refs.session_media_scope():
        # A new turn has saved its image but has not committed memory yet.
        pending = await media_refs.store_session_media(image, sid, "pending")
        if operation == "update":
            await manager.update_memory(sid, [{"role": "user", "content": "previous turn"}])
            handler = media._on_memory_updated
        elif operation == "write":
            await manager.update_session(sid, content=[])
            handler = media._on_memory_written
        else:
            await manager.delete_session(sid)
            handler = media._on_session_deleted
        await wait_for_event_tasks(manager)
        await handler(manager.event_bus.events[-1])

        assert not (tmp_path / old["path"]).exists()
        assert (tmp_path / pending["path"]).read_bytes() == b"hello"
        await manager.update_memory(sid, [{"role": "user", "content": [pending]}])
        await wait_for_event_tasks(manager)
        current = await manager.get_session(sid)
        resolved = await media_refs.resolve_media_references(current.flatten_content())
        assert resolved[0]["content"][0]["type"] == "image_url"
    await media._on_memory_updated(manager.event_bus.events[-1])
    assert (tmp_path / pending["path"]).exists()


@pytest.mark.anyio
async def test_delayed_cleanup_preserves_reference_restored_to_current_memory(
    tmp_path, session_db, monkeypatch,
):
    from core.chat.message_elements import Image
    from core.utils import media_refs

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    sid = "adapter:dm:user"
    reference = await media_refs.store_session_media(
        Image("data:image/png;base64,aGVsbG8="), sid, "restored",
    )
    memory = [[{"role": "user", "content": [reference]}]]
    manager = await build_session_manager(tmp_path, memory, db=session_db)
    await manager.update_session(sid, content=[])
    await wait_for_event_tasks(manager)
    stale = manager.event_bus.events[-1]
    await manager.update_session(sid, content=memory)
    media = SessionMediaManager(SubscriptionEventBus(), manager)

    await media._on_memory_written(stale)

    assert (tmp_path / reference["path"]).read_bytes() == b"hello"
    await wait_for_event_tasks(manager)
