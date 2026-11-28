import json
from types import SimpleNamespace

import pytest

from tests.test_session_tools import (
    OTHER,
    SID,
    archive_text,
    history,
    incoming,
    session_plugin,
)


@pytest.mark.anyio
async def test_search_anchor_neighbors_and_continuation(session_plugin, history, monkeypatch):
    # Equal archive timestamps exercise the ID tie-break in both directions.
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 1000000000)
    ids = [await archive_text(history, "context", str(i)) for i in range(7)]
    ordered = sorted(ids)
    from sqlalchemy import update

    from core.db.models import MessageRecord

    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).where(MessageRecord.id == ordered[3]).values(
            chain=[{"type": "text", "text": "KiraAI startup ERROR"}],
        ))
    event = SimpleNamespace(sid=SID)
    search = json.loads(await session_plugin.search_messages(event, query="error kiraai"))
    assert [row["message_id"] for row in search["messages"]] == [ordered[3]]
    assert search["messages"][0]["platform_message_id"] != ordered[3]
    result = json.loads(await session_plugin.read_messages(
        event, message_id=ordered[3], before=2, after=2,
    ))
    assert result["anchor_id"] == ordered[3]
    assert [row["message_id"] for row in result["messages"]] == ordered[1:6]
    assert result["has_more_before"] and result["has_more_after"]
    older = json.loads(await session_plugin.read_messages(
        event, message_id=ordered[1], before=50, after=0,
    ))
    assert [row["message_id"] for row in older["messages"]] == ordered[:2]
    assert not older["has_more_before"] and older["has_more_after"]
    latest = json.loads(await session_plugin.read_messages(event, before=1))
    assert [row["message_id"] for row in latest["messages"]] == ordered[-2:]
    assert not latest["has_more_after"]
    anchor_only = json.loads(await session_plugin.read_messages(
        event, message_id=ordered[3], before=0, after=0,
    ))
    assert len(anchor_only["messages"]) == 1


@pytest.mark.anyio
async def test_search_filters_and_cursor(history):
    for i in range(5):
        message = incoming(str(i))
        message.timestamp = 100 + i
        message.sender.user_id = "alice" if i != 2 else "bob"
        message.chain[0].text = "KiraAI has ERROR" if i != 3 else "KiraAI only"
        await history.record_incoming(message, SID, "test")
    await archive_text(history, "KiraAI ERROR", "other", sid=OTHER)
    first = await history.search_messages(SID, query="kiraai error", limit=1)
    second = await history.search_messages(SID, query="kiraai error", limit=1, cursor=first.next_cursor)
    assert first.messages[0].platform_message_id == "4"
    assert second.messages[0].platform_message_id == "2"
    filtered = await history.search_messages(
        SID, query="kiraai error", author="alice", sent_after=100, sent_before=104,
    )
    assert [row.platform_message_id for row in filtered.messages] == ["1"]
    assert not (await history.search_messages(SID, query="error", direction="outgoing")).messages
    with pytest.raises(ValueError, match="cursor"):
        await history.search_messages(SID, query="only", cursor=first.messages[0].id)
    with pytest.raises(ValueError, match="cursor"):
        await history.search_messages(SID, query="error", author="bob", cursor=first.messages[0].id)


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [
    {"before": -1}, {"after": 51}, {"before": True}, {"after": 1.5}, {"message_id": ""},
])
async def test_read_validation(history, kwargs):
    with pytest.raises(ValueError):
        await history.read_messages(SID, **kwargs)


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [
    {"query": " "}, {"query": "x" * 201}, {"query": None},
    {"query": "x", "sent_after": True}, {"query": "x", "sent_before": "today"},
    {"query": "x", "sent_after": 2, "sent_before": 1},
    {"query": "x", "author": ""}, {"query": "x", "limit": 201},
])
async def test_search_validation(history, kwargs):
    with pytest.raises(ValueError):
        await history.search_messages(SID, **kwargs)


@pytest.mark.anyio
async def test_read_missing_empty_and_cross_session(session_plugin, history):
    event = SimpleNamespace(sid=SID)
    empty = json.loads(await session_plugin.read_messages(event))
    assert empty["messages"] == [] and empty["anchor_id"] is None
    foreign = await archive_text(history, "private", "foreign", sid=OTHER)
    assert "Message not found in target session" in await session_plugin.read_messages(event, message_id=foreign)
    assert "permission denied" in await session_plugin.read_messages(event, target=OTHER, message_id=foreign)
    assert "permission denied" in await session_plugin.search_messages(event, target=OTHER, query="private")
    session_plugin.plugin_cfg = {"cross_session_read": {"session_list": [SID]}}
    result = json.loads(await session_plugin.read_messages(event, target=OTHER, message_id=foreign))
    assert result["messages"][0]["content"] == "private"
    session_plugin.plugin_cfg["cross_session_read"]["target_permission_mode"] = "allow_list"
    assert "target permission denied" in await session_plugin.read_messages(event, target=OTHER, message_id=foreign)
    assert "target permission denied" in await session_plugin.search_messages(event, target=OTHER, query="private")


@pytest.mark.anyio
@pytest.mark.parametrize("name,kwargs", [("search_messages", {"query": "x"}), ("read_messages", {})])
async def test_disabled_tools_block_direct_calls(session_plugin, name, kwargs):
    session_plugin.plugin_cfg = {"enable_get_message_history": False}
    result = await getattr(session_plugin, name)(SimpleNamespace(sid=SID), **kwargs)
    assert result == f"Error: {name} is disabled"


@pytest.mark.anyio
@pytest.mark.parametrize("offset,expected", [
    (8, "2026-11-24 16:30:00+08:00"),
    (-5, "2026-11-24 03:30:00-05:00"),
])
async def test_message_tools_format_timestamp_in_configured_timezone(session_plugin, history, offset, expected):
    from datetime import datetime, timedelta, timezone

    session_plugin.ctx.get_timezone = lambda: timezone(timedelta(hours=offset))
    message = incoming("dated")
    message.timestamp = int(datetime(2026, 11, 24, 8, 30, tzinfo=timezone.utc).timestamp())
    message.chain[0].text = "dated message"
    identity = await history.record_incoming(message, SID, "test")
    event = SimpleNamespace(sid=SID)
    search = json.loads(await session_plugin.search_messages(event, query="dated"))
    context = json.loads(await session_plugin.read_messages(event, message_id=identity))
    assert search["messages"][0]["timestamp"] == expected
    assert context["messages"][0]["timestamp"] == expected
    assert (await history.get_message(identity)).timestamp == message.timestamp


@pytest.mark.anyio
@pytest.mark.parametrize("sent_after,sent_before", [
    ("2026-11-24 16:29:59+08:00", "2026-11-24 16:30:01+08:00"),
    ("2026-11-24T08:29:59Z", "2026-11-24T08:30:01Z"),
    ("2026-11-24 16:29:59", "2026-11-24 16:30:01"),
])
async def test_search_tool_accepts_readable_time_ranges(session_plugin, history, sent_after, sent_before):
    from datetime import datetime, timezone

    from core.plugin.builtin_plugins.session_tools.tools import SearchMessagesTool

    anchor = int(datetime(2026, 11, 24, 8, 30, tzinfo=timezone.utc).timestamp())
    for i, timestamp in enumerate((anchor - 1, anchor, anchor + 1)):
        message = incoming(str(i))
        message.timestamp = timestamp
        message.chain[0].text = "time search"
        await history.record_incoming(message, SID, "test")
    result = json.loads(await SearchMessagesTool(session_plugin).execute(
        SimpleNamespace(sid=SID), query="time", sent_after=sent_after, sent_before=sent_before,
    ))
    assert [row["platform_message_id"] for row in result["messages"]] == ["1"]
    assert result["messages"][0]["timestamp"] == "2026-11-24 16:30:00+08:00"
    parameters = SearchMessagesTool.parameters["properties"]
    assert parameters["sent_after"]["type"] == parameters["sent_before"]["type"] == "string"


@pytest.mark.anyio
async def test_search_tool_uses_local_timezone_when_unconfigured(session_plugin, history):
    from datetime import datetime

    session_plugin.ctx.get_timezone = lambda: None
    message = incoming("local")
    message.timestamp = int(datetime(2026, 11, 24, 16, 30).timestamp())
    message.chain[0].text = "local message"
    await history.record_incoming(message, SID, "test")
    result = json.loads(await session_plugin.search_messages(
        SimpleNamespace(sid=SID), query="local",
        sent_after="2026-11-24 16:29:59", sent_before="2026-11-24 16:30:01",
    ))
    assert [row["platform_message_id"] for row in result["messages"]] == ["local"]


@pytest.mark.anyio
@pytest.mark.parametrize("value", [
    1795509000, True, "1795509000", "", "yesterday", "2026-11-24",
    "2026-02-30 12:00:00", "2026-11-24 16:30:00.500+08:00",
])
@pytest.mark.parametrize("field", ["sent_after", "sent_before"])
async def test_search_tool_rejects_invalid_date_strings(session_plugin, monkeypatch, value, field):
    from unittest.mock import AsyncMock

    search = AsyncMock()
    monkeypatch.setattr(session_plugin.ctx.message_history, "search_messages", search)
    result = await session_plugin.search_messages(SimpleNamespace(sid=SID), query="x", **{field: value})
    assert result.startswith(f"Error: {field} must be a date-time string")
    search.assert_not_awaited()


@pytest.mark.anyio
async def test_search_tool_checks_range_after_timezone_conversion(session_plugin):
    result = await session_plugin.search_messages(
        SimpleNamespace(sid=SID), query="x",
        sent_after="2026-11-24 16:30:00+08:00", sent_before="2026-11-24 08:30:00Z",
    )
    assert result == "Error: sent_after must be earlier than sent_before"
