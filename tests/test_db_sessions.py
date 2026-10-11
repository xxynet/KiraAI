"""Persistence and migration guarantees for database-backed LLM sessions."""

from copy import deepcopy

import pytest
from sqlalchemy import inspect, text

@pytest.mark.anyio
async def test_session_columns_and_identity_survive_updates_and_reconnection(session_db, monkeypatch):
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 1000)
    first = (await session_db.save_chat_session("adapter:dm:user"))["id"]
    assert first.startswith("sess_") and len(first) == 37
    assert (await session_db.list_chat_sessions())[0]["created_at"] == 1000
    assert (await session_db.list_chat_sessions())[0]["updated_at"] == 1000
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 2000)
    content = [[{"role": "user", "content": "hi"}]]
    extra = {"capabilities": {"tts": {"enabled": False}}}
    assert (await session_db.save_chat_session(
        "adapter:dm:user", title="Changed", description="Daily chat", content=content, data=extra,
    ))["id"] == first
    other = (await session_db.save_chat_session("adapter:gm:group"))["id"]
    assert other != first
    content.clear()
    extra.clear()
    await session_db.db.dispose()
    await session_db.db.init()
    rows = {row["session_key"]: row for row in await session_db.list_chat_sessions()}
    assert len(rows) == 2
    assert rows["adapter:dm:user"] == {
        "id": first, "session_key": "adapter:dm:user", "title": "Changed", "description": "Daily chat",
        "content": [[{"role": "user", "content": "hi"}]], "created_at": 1000, "updated_at": 2000,
        "data": {"capabilities": {"tts": {"enabled": False}}},
    }
    async with session_db.db.engine.connect() as connection:
        columns = await connection.run_sync(lambda conn: inspect(conn).get_columns("chat_sessions"))
    assert {column["name"] for column in columns} == {
        "id", "session_key", "title", "description", "content", "created_at", "updated_at", "data",
    }


@pytest.mark.anyio
async def test_import_maps_legacy_fields_without_overwriting_or_reviving_sessions(session_db, monkeypatch):
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 3000)
    identity = (await session_db.save_chat_session("adapter:dm:existing", title="DB"))["id"]
    records = {
        "adapter:dm:existing": {"title": "Legacy"},
        "adapter:dm:legacy": {
            "title": "Old title", "description": "Old description", "timestamp": 100,
            "memory": [[{"role": "user", "content": "hello", "_extra": {"llm_message_id": "keep"}}]],
            "capabilities": {"tts": {"enabled": False}}, "extension": {"custom": True},
        },
    }
    original = deepcopy(records)
    await session_db.import_chat_sessions(records)
    assert records == original
    rows = {row["session_key"]: row for row in await session_db.list_chat_sessions()}
    assert rows["adapter:dm:existing"]["id"] == identity
    assert rows["adapter:dm:existing"]["title"] == "DB"
    imported = rows["adapter:dm:legacy"]
    assert imported["title"] == "Old title"
    assert imported["description"] == "Old description"
    assert imported["content"] == records["adapter:dm:legacy"]["memory"]
    assert imported["created_at"] == 3000
    assert imported["updated_at"] == 100
    assert imported["data"] == {"capabilities": {"tts": {"enabled": False}}, "extension": {"custom": True}}
    await session_db.delete_chat_session("adapter:dm:legacy")
    await session_db.import_chat_sessions(records)
    assert [row["session_key"] for row in await session_db.list_chat_sessions()] == ["adapter:dm:existing"]
    assert await session_db.is_chat_memory_imported()


@pytest.mark.anyio
async def test_import_handles_missing_timestamps_and_legacy_lists(session_db, monkeypatch):
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 4000)
    records = {
        "adapter:dm:missing": {"memory": []},
        "adapter:dm:null": {"memory": [], "timestamp": None},
        "adapter:dm:zero": {"memory": [], "timestamp": 0},
        "adapter:dm:list": [[{"role": "user", "content": "hello"}]],
    }
    await session_db.import_chat_sessions(records)
    rows = {row["session_key"]: row for row in await session_db.list_chat_sessions()}
    assert all(row["created_at"] == 4000 for row in rows.values())
    assert rows["adapter:dm:missing"]["updated_at"] == 4000
    assert rows["adapter:dm:null"]["updated_at"] == 4000
    assert rows["adapter:dm:zero"]["updated_at"] == 0
    assert rows["adapter:dm:list"]["content"] == records["adapter:dm:list"]
    assert all(row["data"] == {} for row in rows.values())


@pytest.mark.anyio
async def test_import_preserves_malformed_records_without_loss(session_db):
    records = {
        "adapter:dm:null": None, "adapter:dm:number": 42,
        "adapter:dm:bad": {"memory": "raw"}, "adapter:dm:null-memory": {"memory": None},
    }
    await session_db.import_chat_sessions(records)
    rows = {row["session_key"]: row for row in await session_db.list_chat_sessions()}
    assert rows["adapter:dm:null"]["data"] is None
    assert rows["adapter:dm:number"]["data"] == 42
    assert rows["adapter:dm:bad"]["content"] == "raw"
    assert rows["adapter:dm:null-memory"]["content"] is None


@pytest.mark.anyio
async def test_failed_import_rolls_back_rows_and_migration_marker(session_db):
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER fail_session_import BEFORE INSERT ON chat_sessions "
            "WHEN NEW.session_key = 'adapter:dm:fail' "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        ))
    records = {"adapter:dm:first": {"memory": []}, "adapter:dm:fail": {"memory": []}}
    with pytest.raises(Exception, match="injected failure"):
        await session_db.import_chat_sessions(records)
    assert await session_db.list_chat_sessions() == []
    assert not await session_db.is_chat_memory_imported()
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text("DROP TRIGGER fail_session_import"))
    await session_db.import_chat_sessions(records)
    assert len(await session_db.list_chat_sessions()) == 2
    assert await session_db.is_chat_memory_imported()


@pytest.mark.anyio
async def test_failed_update_preserves_previous_record(session_db, monkeypatch):
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 5000)
    await session_db.save_chat_session("adapter:dm:user", title="Original")
    original = await session_db.list_chat_sessions()
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER fail_session_update BEFORE UPDATE ON chat_sessions "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        ))
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 6000)
    with pytest.raises(Exception, match="injected failure"):
        await session_db.save_chat_session("adapter:dm:user", title="New", content=[[{"content": "new"}]])
    assert await session_db.list_chat_sessions() == original


@pytest.mark.anyio
async def test_migration_metadata_records_original_version_and_execution_time(session_db, monkeypatch):
    from core.db.mixins.sessions import CHAT_MEMORY_MIGRATION
    from core.db.models import DatabaseMigration

    monkeypatch.setattr("core.db.mixins.sessions.VERSION", "v-test-original")
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 7000)
    await session_db.import_chat_sessions({})
    async with session_db.db.get_session() as session:
        marker = await session.get(DatabaseMigration, CHAT_MEMORY_MIGRATION)
        assert marker.app_version == "v-test-original"
        assert marker.executed_at == 7000

    monkeypatch.setattr("core.db.mixins.sessions.VERSION", "v-test-next")
    monkeypatch.setattr("core.db.mixins.sessions.time.time", lambda: 8000)
    await session_db.import_chat_sessions({"adapter:dm:late": {"memory": []}})
    async with session_db.db.get_session() as session:
        marker = await session.get(DatabaseMigration, CHAT_MEMORY_MIGRATION)
        assert marker.app_version == "v-test-original"
        assert marker.executed_at == 7000
    assert await session_db.list_chat_sessions() == []


@pytest.mark.anyio
async def test_failed_migration_marker_rolls_back_imported_sessions(session_db):
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text(
            "CREATE TRIGGER fail_migration_marker BEFORE INSERT ON database_migrations "
            "BEGIN SELECT RAISE(ABORT, 'injected marker failure'); END"
        ))
    with pytest.raises(Exception, match="injected marker failure"):
        await session_db.import_chat_sessions({"adapter:dm:user": {"memory": []}})
    assert await session_db.list_chat_sessions() == []
    assert not await session_db.is_chat_memory_imported()
