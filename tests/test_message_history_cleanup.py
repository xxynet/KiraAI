import asyncio
import gc
import os
import threading
import time
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import update

from core.chat.message_elements import Image, Text
from core.chat.message_history import _archive_media
from core.chat.message_history_cleanup import MessageHistoryCleanup, validate_cleanup_config
from core.chat.message_utils import MessageChain
from core.config.default import DEFAULT_CONFIG
from core.db.models import MessageRecord
from tests.test_message_history import SID, history, incoming
from webui.routes.config import ConfigRoutes


@pytest.fixture
def cleaner(history, tmp_path, monkeypatch):
    monkeypatch.setattr("core.chat.message_history_cleanup.get_data_path", lambda: tmp_path)
    return MessageHistoryCleanup(history, deepcopy(DEFAULT_CONFIG))


@pytest.fixture
def session_events(history):
    from core.event_bus import EventBus

    bus = EventBus(Mock(), asyncio.Queue())
    bus.subscribe("session_deleted", history.on_session_deleted)
    history.session_manager.event_bus = bus
    return bus


async def dispatch_session_events(history, bus):
    tasks = tuple(history.session_manager._background_tasks)
    if tasks:
        await asyncio.gather(*tasks)
    while not bus.event_queue.empty():
        await bus._process_event(await bus.event_queue.get())

def settings(**overrides):
    return {**DEFAULT_CONFIG["bot_config"]["message_history_cleanup"], "max_age_days": 30, **overrides}


async def seed(history, number, *, age_days=0, sid=SID, direction="incoming", status="received", chain=None):
    identity = f"{number:032x}"
    created_at = int(time.time() * 1000) - age_days * 86400000
    async with history.db.db.transaction() as session:
        session.add(MessageRecord(
            id=identity, session_id=sid, platform="test", direction=direction,
            timestamp=created_at // 1000, created_at=created_at,
            chain=chain or [{"type": "text", "text": str(number)}], status=status,
            llm_message_id="retained-llm-id", schema_version=1,
        ))
    return identity


@pytest.mark.anyio
async def test_age_and_count_limits_are_combined_per_session(cleaner, history):
    old = await seed(history, 1, age_days=40)
    excess = await seed(history, 2, age_days=3)
    sent = await seed(history, 3, age_days=2, direction="outgoing", status="sent")
    failed = await seed(history, 4, age_days=1, direction="outgoing", status="failed")
    other = await seed(history, 5, sid="other:dm:user")
    memory = deepcopy(history.session_manager.chat_memory)
    result = await cleaner.cleanup_once(settings(max_messages_per_session=2))
    assert result["deleted_messages"] == 2
    assert await history.get_message(old) is None
    assert await history.get_message(excess) is None
    for identity in (sent, failed, other):
        assert await history.get_message(identity) is not None
    assert history.session_manager.chat_memory == memory


@pytest.mark.anyio
async def test_count_tie_breaking_and_disabled_age_limit(cleaner, history):
    ids = [await seed(history, n, age_days=60) for n in range(1, 5)]
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).values(created_at=1))
    result = await cleaner.cleanup_once(settings(max_age_days=0, max_messages_per_session=2))
    assert result["deleted_messages"] == 2
    assert await history.get_message(ids[0]) is None
    assert await history.get_message(ids[1]) is None
    assert await history.get_message(ids[2]) is not None
    assert await history.get_message(ids[3]) is not None


@pytest.mark.anyio
async def test_active_incoming_and_pending_outgoing_are_temporarily_protected(cleaner, history):
    message = incoming()
    active = await history.record_incoming(message, SID, "test")
    pending = await seed(history, 2, age_days=40, direction="outgoing", status="pending")
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).values(created_at=1))
    result = await cleaner.cleanup_once(settings(max_messages_per_session=0))
    assert result["deleted_messages"] == 0
    del message
    gc.collect()
    await history.finish_outgoing(pending, status="sent")
    assert (await cleaner.cleanup_once(settings(max_messages_per_session=0)))["deleted_messages"] == 2
    assert await history.get_message(active) is None


@pytest.mark.anyio
async def test_media_gc_preserves_shared_nested_and_context_references(cleaner, history, tmp_path):
    def media(raw):
        import base64
        return _archive_media(base64.b64encode(raw).decode(), "base64")

    shared = media(b"shared")
    context_only = media(b"context")
    orphan = media(b"orphan")
    element = {"type": "image", "file_type": "archive", "file": shared}
    await seed(history, 1, age_days=40, chain=[element])
    await seed(history, 2, chain=[{"type": "forward", "chains": [[{"type": "reply", "chain": [element]}]]}])
    history.session_manager.chat_memory[SID]["memory"] = [[{
        "role": "user", "content": [{"type": "kira_image_ref", "path": context_only}],
        "_extra": {"llm_message_id": "retained-llm-id"},
    }]]
    root = tmp_path / "session_media" / "archive"
    old_tmp = root / ("a" * 32 + ".tmp")
    fresh_tmp = root / ("b" * 32 + ".download")
    old_tmp.write_bytes(b"old")
    fresh_tmp.write_bytes(b"active")
    os.utime(old_tmp, (1, 1))
    unmanaged = root / "notes.txt"
    unmanaged.write_text("keep")
    native = tmp_path / "session_media" / "native-session" / "image.png"
    native.parent.mkdir()
    native.write_bytes(b"native")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside")
    await seed(history, 3, chain=[{"type": "image", "file_type": "archive", "file": "outside.bin"}])
    result = await cleaner.cleanup_once(settings())
    assert result["deleted_messages"] == 1
    assert result["deleted_files"] == 2
    assert result["freed_bytes"] == len(b"orphanold")
    for path in (shared, context_only):
        assert (tmp_path / path).is_file()
    assert not (tmp_path / orphan).exists()
    assert not old_tmp.exists()
    for path in (fresh_tmp, unmanaged, native, outside):
        assert path.is_file()


@pytest.mark.anyio
async def test_disabled_cleanup_does_not_touch_records_or_files(cleaner, history, tmp_path):
    identity = await seed(history, 1, age_days=40)
    archived = _archive_media("aGVsbG8=", "base64")
    assert (await cleaner.cleanup_once(settings(enabled=False)))["deleted_messages"] == 0
    assert await history.get_message(identity) is not None
    assert (tmp_path / archived).exists()


@pytest.mark.anyio
async def test_cleanup_defers_until_media_and_database_are_both_persisted(cleaner, history, monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def archive(file, kind):
        result = _archive_media(file, kind)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return result

    monkeypatch.setattr("core.chat.message_history._archive_media", archive)
    task = asyncio.create_task(history.record_outgoing(
        SID, MessageChain([Image("base64://aGVsbG8=")]), platform="test", self_id="bot"
    ))
    try:
        await asyncio.wait_for(started.wait(), 3)
        result = await cleaner.cleanup_once(settings())
        assert result["deferred"]
        assert result["deleted_files"] == 0
    finally:
        release.set()
        identity = await task
    assert await history.get_message(identity) is not None
    assert not (await cleaner.cleanup_once(settings()))["deferred"]


@pytest.mark.anyio
async def test_media_gc_excludes_new_archives_and_stop_waits_for_completion(cleaner, history, monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = cleaner._cleanup_media

    def cleanup(retained):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return original(retained)

    monkeypatch.setattr(cleaner, "_cleanup_media", cleanup)
    cleaner.start()
    await asyncio.wait_for(started.wait(), 3)
    writer = asyncio.create_task(history.record_outgoing(
        SID, MessageChain([Text("new")]), platform="test", self_id="bot"
    ))
    stopper = asyncio.create_task(cleaner.stop())
    try:
        await asyncio.sleep(0)
        assert not writer.done()
        assert not stopper.done()
    finally:
        release.set()
        await stopper
        identity = await writer
    assert await history.get_message(identity) is not None


@pytest.mark.anyio
async def test_background_cleanup_reacts_to_configuration_changes(cleaner, history):
    identity = await seed(history, 1, age_days=40)
    cleaner.config["bot_config"]["message_history_cleanup"]["max_age_days"] = 30
    cleaner.config["bot_config"]["message_history_cleanup"]["enabled"] = False
    completed = asyncio.Event()
    original = cleaner.cleanup_once

    async def observe(config):
        result = await original(config)
        completed.set()
        return result

    cleaner.cleanup_once = observe
    cleaner.start()
    try:
        await asyncio.sleep(0)
        assert await history.get_message(identity) is not None
        cleaner.config["bot_config"]["message_history_cleanup"]["enabled"] = True
        cleaner.notify_config_changed()
        await asyncio.wait_for(completed.wait(), 3)
        assert await history.get_message(identity) is None
    finally:
        await cleaner.stop()


@pytest.mark.parametrize("invalid", [
    None, [], {"enabled": "true"}, {"max_age_days": -1}, {"max_age_days": True},
    {"max_messages_per_session": 1.5}, {"cleanup_interval_seconds": 0},
    {"max_age_days": 0, "max_messages_per_session": 0},
])
def test_invalid_cleanup_settings_are_rejected(invalid):
    with pytest.raises(ValueError):
        validate_cleanup_config(invalid)


@pytest.mark.anyio
async def test_config_api_rejects_invalid_values_before_any_mutation_and_notifies_on_save():
    class Config(dict):
        def save_config(self):
            pass

    config = Config(deepcopy(DEFAULT_CONFIG))
    cleanup = SimpleNamespace(notify_config_changed=Mock())
    routes = ConfigRoutes(FastAPI(), SimpleNamespace(kira_config=config, message_history_cleanup=cleanup))
    before = deepcopy(config)
    with pytest.raises(HTTPException) as exc:
        await routes.update_configuration({"bot_config": {"message_history_cleanup": {"max_age_days": -1}}})
    assert exc.value.status_code == 400
    assert config == before
    cleanup.notify_config_changed.assert_not_called()
    payload = deepcopy(config["bot_config"])
    payload["message_history_cleanup"] = settings(enabled=False, max_age_days=7)
    response = await routes.update_configuration({"bot_config": payload})
    assert response["configuration"]["bot_config"]["message_history_cleanup"] == payload["message_history_cleanup"]
    cleanup.notify_config_changed.assert_called_once()


@pytest.mark.anyio
async def test_cancelled_cleanup_keeps_writers_out_until_worker_finishes(cleaner, history, monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def cleanup(retained):
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return 0, 0

    monkeypatch.setattr(cleaner, "_cleanup_media", cleanup)
    task = asyncio.create_task(cleaner.cleanup_once(settings()))
    await asyncio.wait_for(started.wait(), 3)
    task.cancel()
    writer = asyncio.create_task(history.record_outgoing(
        SID, MessageChain([Text("new")]), platform="test", self_id="bot"
    ))
    try:
        await asyncio.sleep(0)
        assert not task.done()
        assert not writer.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await writer


@pytest.mark.anyio
async def test_large_prune_uses_bounded_batches(cleaner, history):
    async with history.db.db.transaction() as session:
        session.add_all([
            MessageRecord(id=f"{n:032x}", session_id=SID, platform="test", direction="incoming",
                          timestamp=1, created_at=1, chain=[], status="received", schema_version=1)
            for n in range(5101)
        ])
    first = await cleaner.cleanup_once(settings(max_age_days=0, max_messages_per_session=1))
    second = await cleaner.cleanup_once(settings(max_age_days=0, max_messages_per_session=1))
    assert first["deleted_messages"] == 5000
    assert second["deleted_messages"] == 100
    assert await history.get_message(f"{5100:032x}") is not None


@pytest.mark.anyio
async def test_failed_media_deletion_is_retried_without_changing_context(cleaner, history, monkeypatch, tmp_path):
    from pathlib import Path

    relative = _archive_media("aGVsbG8=", "base64")
    target = tmp_path / relative
    original = Path.unlink
    failures = []

    def unlink(path, *args, **kwargs):
        if path == target and not failures:
            failures.append(path)
            raise PermissionError("busy")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    assert (await cleaner.cleanup_once(settings()))["deleted_files"] == 0
    assert target.is_file()
    assert (await cleaner.cleanup_once(settings()))["deleted_files"] == 1
    assert not target.exists()


@pytest.mark.anyio
async def test_default_policy_keeps_latest_500_without_age_limit(cleaner, history):
    defaults = DEFAULT_CONFIG["bot_config"]["message_history_cleanup"]
    assert defaults == {"enabled": True, "max_age_days": 0,
                        "max_messages_per_session": 500, "cleanup_interval_seconds": 3600}
    async with history.db.db.transaction() as session:
        session.add_all([
            MessageRecord(id=f"{n:032x}", session_id=SID, platform="test", direction="incoming",
                          timestamp=1, created_at=1, chain=[], status="received", schema_version=1)
            for n in range(501)
        ])
    assert (await cleaner.cleanup_once(defaults))["deleted_messages"] == 1
    assert await history.get_message(f"{0:032x}") is None
    assert await history.get_message(f"{1:032x}") is not None
    assert (await history.list_sessions())[0]["message_count"] == 500


@pytest.mark.anyio
@pytest.mark.parametrize("with_context", [True, False])
async def test_session_delete_removes_all_archive_rows_even_when_cleanup_disabled(cleaner, history, session_events, with_context):
    from webui.routes.sessions import SessionsRoutes

    manager = history.session_manager
    if with_context:
        manager.write_memory(SID, [[{"role": "user", "content": "old"}]])
    else:
        manager.chat_memory.pop(SID, None)
    cleaner.config["bot_config"]["message_history_cleanup"]["enabled"] = False
    await seed(history, 1)
    await seed(history, 2, direction="outgoing", status="pending")
    other = await seed(history, 3, sid="other:dm:user")
    scopes = SimpleNamespace(remove_session_from_scopes=Mock())
    routes = SessionsRoutes(FastAPI(), SimpleNamespace(
        session_manager=manager, message_processor=SimpleNamespace(message_history=history),
        mcp_manager=scopes, skills_manager=None,
    ))
    await routes.delete_session(SID)
    await dispatch_session_events(history, session_events)
    assert manager.get_existing_memory_snapshot(SID) is None
    assert (await history.list_messages(SID))["messages"] == []
    assert await history.get_message(other) is not None
    assert all(item["id"] != SID for item in (await routes.list_sessions())["sessions"])
    scopes.remove_session_from_scopes.assert_called_once_with(SID)


@pytest.mark.anyio
async def test_session_delete_waits_for_existing_archive_and_does_not_rearchive_buffered_message(history, session_events, monkeypatch):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    def archive(file, kind):
        result = _archive_media(file, kind)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5)
        return result

    monkeypatch.setattr("core.chat.message_history._archive_media", archive)
    message = incoming("buffered")
    message.chain = MessageChain([Image("base64://aGVsbG8=")])
    writer = asyncio.create_task(history.record_incoming(message, SID, "test"))
    await asyncio.wait_for(started.wait(), 3)
    history.session_manager.delete_session(SID)
    deletion = asyncio.create_task(dispatch_session_events(history, session_events))
    try:
        await asyncio.sleep(0)
        assert not deletion.done()
    finally:
        release.set()
        identity = await writer
        await deletion
    assert (await history.list_messages(SID))["messages"] == []
    assert await history.record_incoming(message, SID, "test") == identity
    assert (await history.list_messages(SID))["messages"] == []
    new_id = await history.record_incoming(incoming("new-after-delete"), SID, "test")
    assert await history.get_message(new_id) is not None


@pytest.mark.anyio
async def test_failed_context_delete_does_not_delete_archive(history, session_events, monkeypatch):
    identity = await seed(history, 1)
    previous = deepcopy(history.session_manager.chat_memory)
    monkeypatch.setattr(history.session_manager, "_save_memory", lambda *args: False)
    with pytest.raises(OSError, match="Unable to persist session deletion"):
        history.session_manager.delete_session(SID)
    assert history.session_manager.chat_memory == previous
    assert await history.get_message(identity) is not None


@pytest.mark.anyio
async def test_empty_context_edit_keeps_structured_history(history):
    identity = await seed(history, 1)
    history.session_manager.write_memory(SID, [])
    assert await history.get_message(identity) is not None


@pytest.mark.anyio
async def test_session_deleted_event_triggers_archive_deletion(history, session_events):
    manager = history.session_manager
    identity = await seed(history, 1)
    manager.delete_session(SID)
    assert await history.get_message(identity) is not None
    await dispatch_session_events(history, session_events)
    assert await history.get_message(identity) is None
    assert not manager._background_tasks


@pytest.mark.anyio
@pytest.mark.parametrize("malformed", ["scalar", "null", "flat", "object", "nested"])
async def test_media_gc_tolerates_malformed_sessions_and_preserves_references(
    cleaner, history, tmp_path, malformed,
):
    healthy_path = _archive_media("aGVhbHRoeQ==", "base64")
    damaged_path = _archive_media("ZGFtYWdlZA==", "base64")
    orphan_path = _archive_media("b3JwaGFu", "base64")
    reference = {"type": "kira_image_ref", "path": damaged_path}
    records = {
        "scalar": 42,
        "null": {"memory": None},
        "flat": {"memory": [{"role": "user", "content": [reference]}]},
        "object": {"memory": {"content": [reference]}},
        "nested": {"memory": [None, ["bad", {"role": "invalid", "content": [reference]}]]},
    }
    damaged_record = deepcopy(records[malformed])
    history.session_manager.chat_memory["adapter:dm:damaged"] = damaged_record
    history.session_manager.chat_memory[SID]["memory"] = [[{
        "role": "user", "content": [{"type": "kira_image_ref", "path": healthy_path}],
    }]]
    if malformed in {"scalar", "null"}:
        await seed(history, 1, chain=[{
            "type": "image", "file_type": "archive", "file": damaged_path,
        }])

    result = await cleaner.cleanup_once(settings())
    assert result["deleted_files"] == 1
    assert not (tmp_path / orphan_path).exists()
    assert (tmp_path / healthy_path).is_file()
    assert (tmp_path / damaged_path).is_file()
    assert history.session_manager.chat_memory["adapter:dm:damaged"] == records[malformed]
    assert (await cleaner.cleanup_once(settings()))["deleted_files"] == 0
