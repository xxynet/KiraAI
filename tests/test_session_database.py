"""Session manager integration with transactional database persistence."""

import asyncio
import json

import pytest
from sqlalchemy import text

from core.chat.session_manager import SessionManager
from tests.test_session_manager_events import RecordingEventBus, wait_for_event_tasks

SID = "adapter:dm:user"
CONFIG = {"bot_config": {"bot": {"max_memory_length": 100}}}


def manager_for(session_db, tmp_path):
    manager = SessionManager(session_db, CONFIG, RecordingEventBus())
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    return manager


@pytest.mark.anyio
async def test_import_restart_and_delete_keep_database_authoritative(session_db, tmp_path):
    path = tmp_path / "chat_memory.json"
    original = json.dumps({SID: {
        "title": "Legacy", "description": "Daily", "timestamp": 100,
        "memory": [[{"role": "user", "content": "hello"}]],
        "capabilities": {"tts": {"enabled": False}}, "custom": {"keep": True},
    }})
    path.write_text(original, encoding="utf-8")
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    metadata = (await manager.get_session(SID, include_content=False))
    assert metadata.internal_id.startswith("sess_")
    assert metadata.updated_at == metadata.timestamp == 100
    assert metadata.sid == SID
    assert metadata.session_title == "Legacy"
    assert metadata.session_description == "Daily"
    assert metadata.content == []
    assert metadata.data == {"capabilities": {"tts": {"enabled": False}}, "custom": {"keep": True}}
    assert (await manager.get_session(SID)).internal_id == metadata.internal_id
    message_id = (await manager.get_session(SID)).content[0][0]["_extra"]["llm_message_id"]
    await manager.update_session(SID, title="New", description="Changed")
    await manager.update_session_capabilities(SID, {"tts": {"enabled": True}})
    assert path.read_text(encoding="utf-8") == original

    restarted = manager_for(session_db, tmp_path)
    await restarted.initialize()
    current = (await restarted.get_session(SID, include_content=False))
    assert current.internal_id == metadata.internal_id
    assert current.created_at == metadata.created_at
    assert current.updated_at > 100
    assert (await restarted.get_session(SID)).session_title == "New"
    assert (await restarted.get_session(SID)).content[0][0]["_extra"]["llm_message_id"] == message_id
    assert (await restarted.get_session(SID)).data["custom"] == {"keep": True}
    assert (await restarted.get_effective_capabilities(SID, {})) == {"tts": {"enabled": True}}
    await restarted.delete_session(SID)
    await wait_for_event_tasks(restarted)
    await restarted.initialize()
    assert await restarted.get_session(SID) is None
    assert await session_db.list_chat_sessions() == []
    assert path.read_text(encoding="utf-8") == original


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", ["{broken", "[]"])
async def test_invalid_json_can_be_repaired_before_import(session_db, tmp_path, invalid):
    path = tmp_path / "chat_memory.json"
    path.write_text(invalid, encoding="utf-8")
    manager = manager_for(session_db, tmp_path)
    with pytest.raises(ValueError, match="Unable to import legacy chat memory"):
        await manager.initialize()
    assert not await session_db.is_chat_memory_imported()
    assert await session_db.list_chat_sessions() == []
    path.write_text(json.dumps({SID: {"memory": []}}), encoding="utf-8")
    await manager.initialize()
    assert (await manager.get_session(SID, include_content=False)).internal_id
    assert await session_db.is_chat_memory_imported()


@pytest.mark.anyio
async def test_failed_commit_preserves_records_metadata_and_events(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.get_session(SID, ensure_session=True)
    original = await manager.get_sessions()
    metadata = (await manager.get_session(SID, include_content=False))
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER fail_session_update BEFORE UPDATE ON chat_sessions "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        ))
    with pytest.raises(Exception, match="injected failure"):
        await manager.update_session(SID, content=[[{"role": "user", "content": "new"}]])
    assert await manager.get_sessions() == original
    assert (await manager.get_session(SID, include_content=False)) == metadata
    assert manager.event_bus.events == []
    assert not hasattr(manager, "_pending_memory")
    assert (await session_db.list_chat_sessions())[0]["content"] == []


@pytest.mark.anyio
async def test_concurrent_writes_preserve_all_updates_and_one_identity(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await asyncio.gather(*(manager.get_session(SID, ensure_session=True) for _ in range(8)))
    identity = (await manager.get_session(SID, include_content=False)).internal_id
    await asyncio.gather(
        *(manager.update_memory(SID, [{"role": "user", "content": str(i)}]) for i in range(10)),
        manager.update_session(SID, title="Title"),
        manager.update_session_capabilities(SID, {"tts": {"enabled": False}}),
    )
    await wait_for_event_tasks(manager)
    rows = await session_db.list_chat_sessions()
    assert len(rows) == 1 and rows[0]["id"] == identity
    assert {chunk[0]["content"] for chunk in rows[0]["content"]} == {str(i) for i in range(10)}
    assert rows[0]["title"] == "Title"
    assert rows[0]["data"]["capabilities"] == {"tts": {"enabled": False}}
    assert rows[0]["content"] == (await manager.get_session(SID)).content
    assert not (tmp_path / "chat_memory.json").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("delete", [False, True])
async def test_cancellation_waits_for_commit_and_event_publication(session_db, tmp_path, monkeypatch, delete):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.get_session(SID, ensure_session=True)
    entered, release = asyncio.Event(), asyncio.Event()
    name = "delete_chat_session" if delete else "save_chat_session"
    original = getattr(session_db, name)

    async def delayed(*args, **kwargs):
        entered.set()
        await release.wait()
        return await original(*args, **kwargs)

    monkeypatch.setattr(session_db, name, delayed)
    operation = manager.delete_session(SID) if delete else manager.update_session(
        SID, content=[[{"role": "user", "content": "committed"}]],
    )
    task = asyncio.create_task(operation)
    await asyncio.wait_for(entered.wait(), timeout=5)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    await wait_for_event_tasks(manager)
    rows = await session_db.list_chat_sessions()
    if delete:
        assert rows == [] and await manager.get_session(SID) is None
        assert manager.event_bus.events[0].event_type == "session_deleted"
    else:
        assert rows[0]["content"] == (await manager.get_session(SID)).content
        assert (await manager.get_session(SID)).content[0][0]["content"] == "committed"
        assert manager.event_bus.events[0].event_type == "session_memory_written"
    assert not hasattr(manager, "_pending_memory")

@pytest.mark.anyio
async def test_session_api_exposes_identity_without_changing_routing_key(session_db, tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI

    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.get_session(SID, ensure_session=True)
    routes = SessionsRoutes(FastAPI(), SimpleNamespace(session_manager=manager))
    before = await routes.get_session(SID)
    updated = await routes.update_session(SID, {"title": "Renamed", "messages": []})
    listing = await routes.list_sessions()
    for result in (before, updated, listing["sessions"][0]):
        assert result["id"] == SID
        assert result["internal_id"] == before["internal_id"]
        assert result["created_at"] == before["created_at"]
        assert isinstance(result["updated_at"], int)
    assert updated["title"] == "Renamed"
    await wait_for_event_tasks(manager)


@pytest.mark.anyio
async def test_initialize_does_not_load_all_sessions(session_db, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    await session_db.import_chat_sessions({SID: {"memory": []}})
    listing = AsyncMock(side_effect=AssertionError("Startup must not preload session content"))
    monkeypatch.setattr(session_db, "list_chat_sessions", listing)
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    listing.assert_not_awaited()
    assert not hasattr(manager, "chat_memory")
    assert not hasattr(manager, "_metadata")
    assert not hasattr(manager, "_pending_memory")
    assert (await manager.get_session(SID)).internal_id


@pytest.mark.anyio
async def test_reads_and_edits_use_latest_database_state(session_db, tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI

    from webui.routes.scope import ScopeRoutes
    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.get_session(SID, ensure_session=True)
    identity = (await manager.get_session(SID)).internal_id
    assert (await manager.get_session(SID)).content == []
    content = [[{"role": "user", "content": "external", "_extra": {"llm_message_id": "keep"}}]]
    await session_db.save_chat_session(
        SID, title="External", description="Updated outside manager", content=content,
        data={"capabilities": {"tts": {"enabled": False}}, "custom": "retained"},
    )
    assert (await manager.get_session(SID)).content == content
    assert (await manager.get_session(SID)).flatten_content() == content[0]
    assert (await manager.get_session(SID)).session_title == "External"
    assert (await manager.get_sessions())[0].session_title == "External"
    assert (await manager.get_session(SID, include_content=False)).internal_id == identity
    assert await manager.get_effective_capabilities(SID, {}) == {"tts": {"enabled": False}}
    snapshot = (await manager.get_session(SID)).content
    snapshot.clear()
    assert (await manager.get_session(SID)).content == content

    lifecycle = SimpleNamespace(session_manager=manager, mcp_manager=None, skills_manager=None)
    routes = SessionsRoutes(FastAPI(), lifecycle)
    detail = await routes.get_session(SID)
    assert detail["messages"] == content and detail["title"] == "External"
    assert (await routes.list_sessions())["sessions"][0]["message_count"] == 1
    scope = await ScopeRoutes(FastAPI(), lifecycle).get_scope()
    assert scope["sessions"][0]["title"] == "External"

    await manager.update_session(SID, content=[])
    persisted = await session_db.get_chat_session(SID)
    assert persisted["title"] == "External"
    assert persisted["description"] == "Updated outside manager"
    assert persisted["data"]["custom"] == "retained"
    assert persisted["id"] == identity
    await wait_for_event_tasks(manager)

    await session_db.delete_chat_session(SID)
    assert await manager.get_session(SID) is None
    assert await manager.get_sessions() == []
    assert await manager.get_session(SID, include_content=False) is None
    assert await manager.get_effective_capabilities(SID, {"tts": {"enabled": True}}) == {
        "tts": {"enabled": True},
    }


@pytest.mark.anyio
async def test_session_listing_uses_two_bulk_queries(session_db, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    for key in (SID, "adapter:dm:other"):
        await manager.get_session(key, ensure_session=True)
    listing = AsyncMock(wraps=session_db.list_chat_sessions)
    counts = AsyncMock(wraps=session_db.get_chat_session_message_counts)
    monkeypatch.setattr(session_db, "get_chat_session_message_counts", counts)
    monkeypatch.setattr(session_db, "list_chat_sessions", listing)
    monkeypatch.setattr(session_db, "get_chat_session", AsyncMock(
        side_effect=AssertionError("Listing must not query individual sessions"),
    ))
    routes = SessionsRoutes(FastAPI(), SimpleNamespace(session_manager=manager))
    result = await routes.list_sessions()
    assert len(result["sessions"]) == 2
    listing.assert_awaited_once_with(include_content=False)
    counts.assert_awaited_once_with()


@pytest.mark.anyio
async def test_session_queries_return_complete_independent_snapshots(session_db, tmp_path):
    from core.chat.session import Session

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    sid = "adapter:dm:user:thread"
    content = [[{"role": "user", "content": "hello"}]]
    data = {"capabilities": {"tts": {"enabled": False}}, "custom": {"value": 1}}
    stored = await session_db.save_chat_session(
        sid, title="Title", description="Description", content=content, data=data,
    )
    record = await manager.get_session(sid)
    listing = await manager.get_sessions()
    info = await manager.get_session(sid)
    assert isinstance(record, Session)
    assert listing == [record] and info == record
    assert record.sid == sid
    assert record.adapter_name == "adapter"
    assert record.session_type == "dm"
    assert record.session_id == "user:thread"
    assert record.internal_id == stored["id"]
    assert record.session_title == "Title"
    assert record.session_description == "Description"
    assert record.created_at == stored["created_at"]
    assert record.updated_at == record.timestamp == stored["updated_at"]
    assert record.content == content and record.data == data

    record.content[0][0]["content"] = "local change"
    record.data["custom"]["value"] = 2
    assert listing[0].content == content and info.content == content
    assert listing[0].data == data and info.data == data
    assert await session_db.get_chat_session(sid) == stored
    assert (await manager.get_session(sid)) == info
    assert await manager.get_session("adapter:dm:missing") is None
    missing = await manager.get_session("adapter:dm:missing")
    assert missing is None


def test_flatten_content_isolates_nested_message_mutations():
    from core.chat.session import Session

    session = Session("adapter", "dm", "user", content=[
        [{"role": "user", "content": [{"type": "text", "text": "original"}]}],
        [],
        [{"role": "assistant", "content": "reply"}],
    ])
    messages = session.flatten_content()
    assert [message["role"] for message in messages] == ["user", "assistant"]
    messages[0]["content"][0]["text"] = "changed"
    messages[0]["content"].append({"type": "text", "text": "new"})
    messages[1]["content"] = "changed reply"
    messages.clear()
    assert session.content == [
        [{"role": "user", "content": [{"type": "text", "text": "original"}]}],
        [],
        [{"role": "assistant", "content": "reply"}],
    ]


def test_session_defaults_and_record_conversion_do_not_share_mutable_data():
    from core.chat.session import Session

    first = Session("adapter", "dm", "first")
    second = Session("adapter", "dm", "second")
    first.content.append([])
    first.data["custom"] = True
    assert second.content == [] and second.data == {}

    source = {
        "session_key": "adapter:dm:user", "id": "sess_test", "title": "Title",
        "description": "Description", "created_at": 1, "updated_at": 2,
        "content": [[{"content": "original"}]], "data": {"custom": {"value": 1}},
    }
    snapshot = Session.from_record(source)
    snapshot.content[0][0]["content"] = "changed"
    snapshot.data["custom"]["value"] = 2
    assert source["content"][0][0]["content"] == "original"
    assert source["data"]["custom"]["value"] == 1


@pytest.mark.anyio
async def test_update_session_preserves_omitted_columns_and_skips_empty_updates(session_db, tmp_path, monkeypatch):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 1000)
    await manager.update_session(
        SID, title="Original", description="Keep", content=[[{"role": "user", "content": "hello"}]],
        data={"capabilities": {"tts": {"enabled": False}}, "custom": 1},
    )
    await wait_for_event_tasks(manager)
    manager.event_bus.events.clear()
    original = await session_db.get_chat_session(SID)
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER reject_unrelated_session_update BEFORE UPDATE OF content, data, description "
            "ON chat_sessions BEGIN SELECT RAISE(ABORT, 'unrelated column updated'); END"
        ))
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 2000)
    await manager.update_session(SID, title="Changed")
    changed = await session_db.get_chat_session(SID)
    assert changed == {**original, "title": "Changed", "updated_at": 2000}
    assert manager.event_bus.events == []
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 3000)
    await manager.update_session(SID)
    await manager.update_session("adapter:dm:missing")
    assert await session_db.get_chat_session(SID) == changed
    assert await manager.get_session("adapter:dm:missing") is None


@pytest.mark.anyio
async def test_update_session_clears_explicit_fields_and_publishes_content_event(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title="Title", description="Description",
                                 content=[[{"role": "user", "content": "hello"}]], data={"old": True})
    await wait_for_event_tasks(manager)
    original = await manager.get_session(SID)
    manager.event_bus.events.clear()
    await manager.update_session(SID, title=None, description="", data={"new": True})
    current = await manager.get_session(SID)
    assert current.session_title is None and current.session_description == ""
    assert current.data == {"new": True} and current.content == original.content
    assert current.internal_id == original.internal_id and current.created_at == original.created_at
    assert manager.event_bus.events == []
    await manager.update_session(SID, content=[], data={})
    await wait_for_event_tasks(manager)
    current = await manager.get_session(SID)
    assert current.content == [] and current.data == {}
    event, = manager.event_bus.events
    assert event.event_type == "session_memory_written"
    assert event.payload == {"session": SID, "old_memory": original.content, "new_memory": []}


@pytest.mark.anyio
async def test_update_session_rolls_back_all_fields_and_events_on_failure(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title="Original", content=[[{"role": "user", "content": "hello"}]])
    await wait_for_event_tasks(manager)
    manager.event_bus.events.clear()
    original = await manager.get_session(SID)
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER reject_session_update BEFORE UPDATE ON chat_sessions "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        ))
    with pytest.raises(Exception, match="injected failure"):
        await manager.update_session(SID, title="Changed", content=[], data={"new": True})
    await wait_for_event_tasks(manager)
    assert await manager.get_session(SID) == original
    assert manager.event_bus.events == []


@pytest.mark.anyio
@pytest.mark.parametrize("changes", [
    {"title": 1}, {"description": []}, {"content": None}, {"data": None},
    {"content": [[{"role": "invalid", "content": "bad"}]]},
])
async def test_update_session_rejects_invalid_fields_before_writing(session_db, tmp_path, changes):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title="Original")
    original = await manager.get_session(SID)
    with pytest.raises(ValueError):
        await manager.update_session(SID, **{"title": "Changed", **changes})
    assert await manager.get_session(SID) == original


@pytest.mark.anyio
async def test_session_api_updates_only_supplied_metadata(session_db, tmp_path):
    from types import SimpleNamespace

    from fastapi import FastAPI

    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title="Title", description="Keep")
    routes = SessionsRoutes(FastAPI(), SimpleNamespace(session_manager=manager))
    result = await routes.update_session(SID, {"title": "Changed"})
    assert result["title"] == "Changed" and result["description"] == "Keep"
    result = await routes.update_session(SID, {"description": None})
    assert result["title"] == "Changed" and result["description"] is None


@pytest.mark.anyio
async def test_update_session_preserves_explicit_nulls_on_creation(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title=None, description=None)
    created = await manager.get_session(SID)
    assert created.session_title is None
    assert created.session_description is None
    assert created.content == [] and created.data == {}


@pytest.mark.anyio
async def test_get_session_can_ensure_one_persistent_identity_concurrently(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    assert await manager.get_session(SID) is None
    assert await session_db.list_chat_sessions() == []
    sessions = await asyncio.gather(*(
        manager.get_session(SID, ensure_session=True) for _ in range(8)
    ))
    assert len({session.internal_id for session in sessions}) == 1
    assert sessions[0].internal_id.startswith("sess_")
    assert all(session.sid == SID and session.content == [] and session.data == {} for session in sessions)
    assert all(session.created_at == session.updated_at for session in sessions)
    assert len(await session_db.list_chat_sessions()) == 1
    sessions[0].content.append([])
    assert sessions[1].content == []
    assert (await manager.get_session(SID)).content == []
    await wait_for_event_tasks(manager)
    assert manager.event_bus.events == []


@pytest.mark.anyio
async def test_get_session_ensure_preserves_existing_record_without_writing(session_db, tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await manager.update_session(SID, title="Keep", description="Description", data={"custom": True})
    original = await manager.get_session(SID)
    query = AsyncMock(wraps=session_db.get_chat_session)
    monkeypatch.setattr(session_db, "get_chat_session", query)
    monkeypatch.setattr(session_db, "save_chat_session", AsyncMock(side_effect=AssertionError("Do not rewrite")))
    assert await manager.get_session(SID, ensure_session=True) == original
    query.assert_awaited_once_with(SID, include_content=True)


@pytest.mark.anyio
async def test_get_session_ensure_rejects_invalid_routing_key_without_creating_record(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    with pytest.raises(ValueError, match="Invalid session routing key"):
        await manager.get_session("invalid", ensure_session=True)
    assert await session_db.list_chat_sessions() == []


@pytest.mark.anyio
@pytest.mark.parametrize("ensure", [False, True])
@pytest.mark.parametrize("include_content", [False, True])
@pytest.mark.parametrize("data", [None, 42, "malformed"])
async def test_get_session_rejects_non_object_data_without_modifying_record(session_db, tmp_path, ensure, data, include_content):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    original = await session_db.save_chat_session(SID, data=data)
    with pytest.raises(ValueError, match="^Session data must be an object$"):
        await manager.get_session(SID, ensure_session=ensure, include_content=include_content)
    assert await session_db.get_chat_session(SID) == original


@pytest.mark.anyio
async def test_metadata_ensure_shares_identity_with_full_session_reads(session_db, tmp_path):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    assert await manager.get_session(SID, include_content=False) is None
    assert await session_db.list_chat_sessions() == []
    results = await asyncio.gather(*(
        manager.get_session(SID, ensure_session=True, include_content=False) if index % 2 else
        manager.get_session(SID, ensure_session=True)
        for index in range(8)
    ))
    identities = {result.internal_id for result in results}
    assert len(identities) == 1
    assert len(await session_db.list_chat_sessions()) == 1
    await manager.update_session(SID, description="Current description")
    metadata = await manager.get_session(SID, ensure_session=True, include_content=False)
    assert metadata.internal_id in identities
    assert metadata.session_description == "Current description"
    assert metadata.content == [] and metadata.data == {}


@pytest.mark.anyio
@pytest.mark.parametrize("consumer", ["prompt", "scope", "list"])
async def test_metadata_consumers_load_data_without_message_content(session_db, tmp_path, monkeypatch, consumer):
    from types import SimpleNamespace

    from fastapi import FastAPI
    from sqlalchemy import event

    from core.plugin.builtin_plugins.session_tools.main import SessionPlugin
    from webui.routes.scope import ScopeRoutes
    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await session_db.save_chat_session(
        SID, title="Visible title", content=[[{"role": "user", "content": "private history"}]] * 3,
        data={"private": "extension payload"},
    )
    await session_db.save_chat_session("adapter:dm:bad", title="Hidden title", data=42)
    await session_db.save_chat_session("invalid", title="Invalid routing")

    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append((statement, [column[0] for column in cursor.description]))

    event.listen(session_db.db.engine.sync_engine, "after_cursor_execute", capture)
    try:
        lifecycle = SimpleNamespace(session_manager=manager, mcp_manager=None, skills_manager=None)
        if consumer == "prompt":
            from unittest.mock import AsyncMock
            ctx = SimpleNamespace(session_mgr=manager, message_history=SimpleNamespace(list_sessions=AsyncMock(return_value=[])))
            result = await SessionPlugin.get_session_list_prompt(SimpleNamespace(ctx=ctx))
            assert "Visible title" in result and SID in result and "Hidden title" not in result
        elif consumer == "scope":
            result = await ScopeRoutes(FastAPI(), lifecycle).get_scope()
            assert [row["id"] for row in result["sessions"]] == [SID]
        else:
            result = await SessionsRoutes(FastAPI(), lifecycle).list_sessions()
            assert [row["id"] for row in result["sessions"]] == [SID]
            assert result["sessions"][0]["message_count"] == 3
    finally:
        event.remove(session_db.db.engine.sync_engine, "after_cursor_execute", capture)
    assert len(queries) == (2 if consumer == "list" else 1)
    sql, columns = queries[0]
    assert "content" not in columns and "data" in columns
    assert "chat_sessions.content" not in sql
    if consumer == "list":
        assert "content" not in queries[1][1] and "data" not in queries[1][1]


@pytest.mark.anyio
@pytest.mark.parametrize("content", [[], [[{"role": "user", "content": "hi"}]], None, 42])
async def test_session_counts_match_content_shape(session_db, tmp_path, content):
    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    await session_db.save_chat_session(SID, content=content)
    assert await manager.get_session_message_counts() == {SID: len(content) if isinstance(content, list) else 0}
    await session_db.delete_chat_session(SID)
    assert await manager.get_session_message_counts() == {}


@pytest.mark.anyio
async def test_detail_update_and_archive_only_responses_include_message_count(session_db, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from webui.routes.sessions import SessionsRoutes

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    routes = SessionsRoutes(FastAPI(), SimpleNamespace(
        session_manager=manager,
        message_history=SimpleNamespace(list_messages=AsyncMock(return_value=SimpleNamespace(messages=[object()]))),
    ))
    assert (await routes.get_session(SID))["message_count"] == 0
    messages = [[{"role": "user", "content": "hi"}], [{"role": "assistant", "content": "hello"}]]
    assert (await routes.update_session(SID, {"messages": messages}))["message_count"] == 2
    assert (await routes.get_session(SID))["message_count"] == 2
    assert (await routes.update_session(SID, {"messages": []}))["message_count"] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("single", [False, True])
@pytest.mark.parametrize("include_content", [False, True])
async def test_session_queries_share_content_options_and_return_session(session_db, tmp_path, single, include_content):
    from core.chat.session import Session

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    content = [[{"role": "user", "content": "history"}], [{"role": "assistant", "content": "reply"}]]
    data = {"custom": {"nested": "extension"}}
    stored = await session_db.save_chat_session(SID, title="Title", content=content, data=data)
    options = {"include_content": include_content}
    if single:
        record = await manager.get_session(SID, **options)
    else:
        record, = await manager.get_sessions(**options)
    assert type(record) is Session
    assert record.sid == SID and record.internal_id == stored["id"]
    assert record.session_title == "Title" and isinstance(record.data, dict)
    assert record.content == (content if include_content else [])
    assert record.data == data
    record.content.clear()
    record.data.clear()
    assert (await manager.get_session(SID)).content == content
    assert (await manager.get_sessions())[0].data == data


@pytest.mark.anyio
async def test_lightweight_ensure_creates_session_without_content(session_db, tmp_path):
    from core.chat.session import Session

    manager = manager_for(session_db, tmp_path)
    await manager.initialize()
    assert await manager.get_session(SID, include_content=False) is None
    record = await manager.get_session(SID, ensure_session=True, include_content=False)
    assert type(record) is Session
    assert await manager.get_session_message_counts() == {SID: 0}
    assert record.content == [] and record.data == {}
    assert (await manager.get_session(SID)).internal_id == record.internal_id
