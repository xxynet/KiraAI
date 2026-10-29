import asyncio
import itertools
import json
import threading
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.plugin.builtin_plugins.session_tools.main import SessionPlugin
from tests.test_message_history import SID, history, incoming

OTHER = "custom-instance:gm:channel:123"


@pytest.fixture
def session_plugin(history):
    capability = SimpleNamespace(is_allowed=Mock(return_value=True))
    adapter = SimpleNamespace(get_capability=Mock(return_value=capability))
    ctx = SimpleNamespace(
        session_mgr=history.session_manager,
        message_history=history,
        adapter_mgr=SimpleNamespace(get_adapter=Mock(return_value=adapter)),
        publish_notice=AsyncMock(),
        get_timezone=lambda: timezone(timedelta(hours=8)),
    )
    return SessionPlugin(ctx, {})


async def archive_text(history, text, identity, *, sid=SID):
    message = incoming(identity)
    message.chain[0].text = text
    return await history.record_incoming(message, sid, "test")


@pytest.mark.anyio
async def test_session_view_metadata_and_counts_without_exposing_memory(session_plugin, history, monkeypatch):
    """Distinguish retained messages from context chunks while keeping detail responses compact."""
    await history.session_manager.update_session(
        SID, title="会话标题", description="会话描述",
        content=[
            [{"role": "user", "content": "private memory"}, {"role": "assistant", "content": "context reply"}],
            [{"role": "assistant", "content": "reply"}],
        ],
        data={"private_extension": "must not return"},
    )
    await archive_text(history, "first message", "one")
    await history.record_outgoing(SID, incoming().chain, platform="test", self_id="bot")
    get_session = AsyncMock(wraps=history.session_manager.get_session)
    monkeypatch.setattr(history.session_manager, "get_session", get_session)

    result = json.loads(await session_plugin.session_view(SimpleNamespace(sid=SID)))

    assert result["title"] == "会话标题" and result["description"] == "会话描述"
    assert result["history_count"] == 2 and result["context_chunk_count"] == 2
    assert result["created_at"] and result["updated_at"] >= result["created_at"]
    assert set(result) == {
        "session_id", "title", "description", "created_at", "updated_at",
        "context_chunk_count", "history_count", "timestamp_unit",
    }
    assert "private memory" not in json.dumps(result) and "private_extension" not in result
    get_session.assert_awaited_once_with(SID, include_content=False)
    session_plugin.ctx.adapter_mgr.get_adapter.assert_not_called()


@pytest.mark.anyio
async def test_history_only_session_is_queryable_but_excluded_from_prompt(session_plugin, history):
    """Explicit archive reads remain possible without adding archive-only sessions to model prompts."""
    archived_sid = "archive-only:dm:user"
    await archive_text(history, "retained message", "one", sid=archived_sid)
    result = json.loads(await session_plugin.session_view(SimpleNamespace(sid=archived_sid)))
    assert result["history_count"] == 1 and result["context_chunk_count"] == 0
    assert result["created_at"] is None and result["updated_at"] is None
    prompt = await session_plugin.get_session_list_prompt()
    assert archived_sid not in prompt and SID in prompt
    assert await history.session_manager.get_session(archived_sid) is None


@pytest.mark.anyio
async def test_nonexistent_session_has_empty_history_and_no_metadata(session_plugin, history):
    """Read-only tools must not create sessions when no matching history or metadata exists."""
    sid = "nonexistent:dm:user"
    event = SimpleNamespace(sid=sid)
    assert json.loads(await session_plugin.session_view(event)) == {"error": "Session not found"}
    assert json.loads(await session_plugin.get_message_history(event)) == {
        "session_id": sid, "messages": [], "next_cursor": None,
    }
    assert await history.session_manager.get_session(sid) is None


@pytest.mark.anyio
async def test_keyword_search_precedes_pagination_and_scopes_direction(session_plugin, history, monkeypatch):
    """Older matches remain discoverable across batches without leaking other sessions."""
    clock = itertools.count(1_000_000_000, 1_000_000)
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: next(clock))
    expected = []
    for index in range(215):
        text = "中文 Match_100% \\ literal" if index in {0, 105, 210} else "unrelated"
        await archive_text(history, text, str(index))
        if index in {0, 105, 210}:
            expected.append(str(index))
    await archive_text(history, "中文 Match_100% \\ literal", "other", sid=OTHER)
    await history.record_outgoing(SID, incoming().chain, platform="test", self_id="bot")
    event = SimpleNamespace(sid=SID)
    found, cursor = [], None
    for _ in range(4):
        page = json.loads(await session_plugin.get_message_history(
            event, keyword="中文 match_100%", direction="incoming", limit=1, cursor=cursor,
        ))
        found.extend(row.split("[message_id: ", 1)[1].split("]", 1)[0] for row in page["messages"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == list(reversed(expected))
    assert cursor is None
    assert not (await history.get_messages(session_id=SID, keyword="absent")).messages
    assert len((await history.get_messages(session_id=SID, keyword="", limit=200)).messages) == 200


@pytest.mark.anyio
async def test_search_visible_unicode_nested_and_media_text_not_storage_metadata(history):
    """Search visible Unicode content while excluding archive paths and routing metadata."""
    record = await archive_text(history, "replace", "one")
    from sqlalchemy import update

    from core.db.models import MessageRecord

    chain = [
        {"type": "text", "text": "Straße"},
        {"type": "reply", "message_id": "hidden-reference", "chain": [{"type": "text", "text": "引用内容"}]},
        {"type": "image", "description": "月亮", "file": "session_media/archive/private-path", "file_type": "archive"},
        {"type": "record", "transcript": "语音转写"},
        {"type": "json", "data": {"visible": "卡片正文"}},
    ]
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).where(MessageRecord.id == record).values(
            chain=chain, sender_name="hidden-sender",
        ))
    for keyword in ("STRASSE", "引用内容", "月亮", "语音转写", "卡片正文"):
        assert [row.id for row in (await history.get_messages(session_id=SID, keyword=keyword)).messages] == [record]
    for keyword in ("private-path", "hidden-reference", "hidden-sender", "file_type", "archive"):
        assert not (await history.get_messages(session_id=SID, keyword=keyword)).messages


@pytest.mark.anyio
async def test_history_tool_omits_media_paths_without_changing_archive(session_plugin, history):
    """Tool projections remove nested storage paths without changing the retained snapshot."""
    from sqlalchemy import update

    from core.db.models import MessageRecord

    record = await archive_text(history, "replace", "one")
    chain = [{"type": "reply", "chain": [
        {"type": "image", "description": "月亮", "file": "session_media/archive/private-path", "file_type": "archive"},
    ]}]
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).where(MessageRecord.id == record).values(chain=chain))
    result = await session_plugin.get_message_history(SimpleNamespace(sid=SID), keyword="月亮")
    assert "private-path" not in result
    assert "[Image 月亮]" in json.loads(result)["messages"][0]
    assert (await history.get_message(record)).to_dict()["chain"] == chain


@pytest.mark.anyio
async def test_search_cursor_must_match_session_keyword_and_direction(history):
    """Continuation cursors must identify records matching the active session and filters."""
    first = await archive_text(history, "alpha", "one")
    other = await archive_text(history, "beta", "two", sid=OTHER)
    for filters in (
        {"keyword": "beta", "cursor": first},
        {"keyword": "alpha", "cursor": other},
        {"direction": "outgoing", "cursor": first},
        {"keyword": "alpha", "cursor": "missing"},
    ):
        with pytest.raises(ValueError, match="cursor"):
            await history.get_messages(session_id=SID, **filters)


@pytest.mark.anyio
@pytest.mark.parametrize("options", [
    {"keyword": 1}, {"keyword": "x" * 201}, {"limit": True}, {"limit": 1.5},
    {"limit": 0}, {"limit": 201}, {"direction": "invalid"}, {"cursor": 123}, {"cursor": ""},
])
async def test_history_tool_validates_arguments(session_plugin, options):
    """Invalid pagination and filter values produce readable tool errors."""
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), **options))
    assert "error" in result


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["session_view", "get_message_history"])
@pytest.mark.parametrize("target", ["", "missing", "x:feed:123", "x:dm:", 123, OTHER])
async def test_invalid_or_unauthorized_targets_never_query(session_plugin, tool_name, target, monkeypatch):
    """Reject invalid routes and unauthorized callers before querying session data."""
    get_session = AsyncMock()
    get_messages = AsyncMock()
    history_sessions = AsyncMock()
    monkeypatch.setattr(session_plugin.ctx.session_mgr, "get_session", get_session)
    monkeypatch.setattr(session_plugin.ctx.message_history, "get_messages", get_messages)
    monkeypatch.setattr(session_plugin.ctx.message_history, "list_sessions", history_sessions)
    result = json.loads(await getattr(session_plugin, tool_name)(SimpleNamespace(sid=SID), target=target))
    assert "error" in result
    get_session.assert_not_awaited()
    get_messages.assert_not_awaited()
    history_sessions.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("mode,sessions,allowed", [
    ("allow_list", [SID], True), ("allow_list", [OTHER], False),
    ("deny_list", [], True), ("deny_list", [SID], False),
    ("invalid", [], False),
])
async def test_cross_session_read_uses_calling_session_permission(session_plugin, history, mode, sessions, allowed):
    """Cross-session access applies the configured policy to the caller rather than the target."""
    session_plugin.plugin_cfg = {"cross_session_read": {"permission_mode": mode, "session_list": sessions}}
    await archive_text(history, "target history", "target", sid=OTHER)
    event = SimpleNamespace(sid=SID)
    result = json.loads(await session_plugin.get_message_history(event, target=OTHER))
    metadata = json.loads(await session_plugin.session_view(event, target=OTHER))
    assert ("error" not in result) is allowed
    assert ("error" not in metadata) is allowed
    if allowed:
        assert result["session_id"] == OTHER
        assert "[message_id: target]" in result["messages"][0]
        assert result["messages"][0].endswith(" | target history")
        assert metadata["history_count"] == 1
        capability = session_plugin.ctx.adapter_mgr.get_adapter.return_value.get_capability.return_value
        capability.is_allowed.assert_called_with("channel:123", permission="im.group.receive")


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["missing_adapter", "no_im", "denied"])
async def test_cross_session_read_also_respects_adapter_policy(session_plugin, failure):
    """Caller authorization alone cannot bypass the target adapter receive policy."""
    session_plugin.plugin_cfg = {"cross_session_read": {"session_list": [SID]}}
    lookup = session_plugin.ctx.adapter_mgr.get_adapter
    if failure == "missing_adapter":
        lookup.return_value = None
    elif failure == "no_im":
        lookup.return_value.get_capability.side_effect = ValueError("not supported")
    else:
        lookup.return_value.get_capability.return_value.is_allowed.return_value = False
    for method in (session_plugin.get_message_history, session_plugin.session_view):
        assert "error" in json.loads(await method(SimpleNamespace(sid=SID), target=OTHER))


@pytest.mark.anyio
async def test_registered_history_tools_log_arguments_and_results(session_plugin, monkeypatch):
    """Registered tools preserve the existing argument and result logging behavior."""
    from core.agent import func_tool_manager
    from core.agent.func_tool_manager import FuncToolManager
    from core.plugin.handlers import event_handler_reg
    from core.plugin.manager import PluginManager
    from core.provider import LLMResponse

    config = {
        "bot_config.agent.max_tool_calls_per_turn": 5,
        "bot_config.agent.tool_call_timeout": 60,
        "bot_config.agent.max_tool_output_tokens": 10000,
    }
    manager = FuncToolManager(SimpleNamespace(get_config=config.get))
    owner = SimpleNamespace(
        ctx=SimpleNamespace(tool_mgr=manager),
        plugin_instances={"kira_session_plugin": session_plugin},
    )
    PluginManager._register_plugin_tools_for(owner, "kira_session_plugin")
    tools = manager.build_tool_set()
    assert "session_view" in tools and "get_message_history" in tools and "session_send" in tools
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda **kwargs: [])
    log = Mock()
    monkeypatch.setattr(func_tool_manager.tool_logger, "info", log)
    await archive_text(session_plugin.ctx.message_history, "history-keyword", "one")
    response = LLMResponse("")
    response.tool_calls = [{"id": "query", "function": {
        "name": "get_message_history", "arguments": '{"keyword": "history-keyword"}',
    }}]
    await manager.execute_tool(SimpleNamespace(sid=SID, is_stopped=False), response, tools)
    assert "history-keyword" in response.tool_results[0]["content"]
    log.assert_any_call("get_message_history args: {'keyword': 'history-keyword'}")
    assert log.call_args.args == (f"tool_result: {response.tool_results[0]['content']}",)

def test_session_tools_config_schema_has_matching_english_and_chinese_fields():
    """Plugin configuration fields remain parseable and have matching English and Chinese labels."""
    from pathlib import Path

    from core.config.config_field import build_fields

    root = Path(__file__).resolve().parents[1] / "core/plugin/builtin_plugins/session_tools"
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    assert len(build_fields(schema)) == 1

    def validate(fields):
        """Require localized display text recursively for every configuration field."""
        for field in fields.values():
            assert {"name", "hint"} <= field.keys()
            assert set(field["locales"]["zh"]) == {"name", "hint"}
            if "fields" in field:
                validate(field["fields"])

    validate(schema)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for field in ("display_name", "description"):
        assert field in manifest and field in manifest["locales"]["zh"]

@pytest.mark.anyio
async def test_session_view_counts_only_target_context_without_loading_bodies(session_plugin, history):
    """A detail request must count its target's chunks without scanning all session contexts."""
    from sqlalchemy import event

    await history.session_manager.update_session(SID, content=[
        [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}],
        [{"role": "user", "content": "three"}],
    ])
    await history.session_manager.update_session(OTHER, content=[[{"role": "user", "content": "other"}]] * 5)
    await archive_text(history, "one", "first")
    await archive_text(history, "two", "second")
    await archive_text(history, "other", "third", sid=OTHER)
    queries = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append((statement, parameters, [column[0] for column in cursor.description]))

    engine = history.db.db.engine.sync_engine
    event.listen(engine, "after_cursor_execute", capture)
    try:
        result = json.loads(await session_plugin.session_view(SimpleNamespace(sid=SID)))
    finally:
        event.remove(engine, "after_cursor_execute", capture)

    assert result["context_chunk_count"] == result["history_count"] == 2
    history_queries = [(sql, parameters) for sql, parameters, _ in queries if "FROM messages" in sql]
    assert len(history_queries) == 1
    history_sql, history_parameters = history_queries[0]
    assert "WHERE messages.session_id =" in history_sql and SID in history_parameters
    count_queries = [(sql, parameters) for sql, parameters, _ in queries if "json_array_length" in sql]
    assert len(count_queries) == 1
    sql, parameters = count_queries[0]
    assert "WHERE" in sql and "chat_sessions.session_key =" in sql and SID in parameters
    assert all("content" not in columns and "chain" not in columns for _, _, columns in queries)
    assert await history.session_manager.get_session_message_counts() == {SID: 2, OTHER: 5}


@pytest.mark.anyio
async def test_mention_search_matches_nickname_without_matching_numeric_id(history):
    """Mention identifiers stay excluded while user-facing nicknames remain searchable."""
    from core.chat.message_elements import At
    from core.chat.message_utils import MessageChain

    message = incoming("mention")
    message.chain = MessageChain([At("12345678901234567890", "Alice"), At("98765432109876543210")])
    record = await history.record_incoming(message, SID, "test")
    assert [item.id for item in (await history.get_messages(session_id=SID, keyword="alice")).messages] == [record]
    for keyword in ("12345678901234567890", "98765432109876543210"):
        assert not (await history.get_messages(session_id=SID, keyword=keyword)).messages


@pytest.mark.anyio
@pytest.mark.parametrize("chain,matched", [
    ([None, "broken", {"type": "text", "text": "needle"}], True),
    ([{"type": []}, {"type": "text", "text": "needle"}], True),
    ([{"type": "reply", "chain": [None, {"type": "text", "text": "needle"}]}], True),
    ([{"type": "reply", "chain": 42}], False),
    ([{"type": "json", "data": None}, {"type": "text", "text": "needle"}], True),
    ([{"type": "json", "data": []}, {"type": "text", "text": "needle"}], True),
    ([{"type": "json", "data": "invalid"}, {"type": "text", "text": "needle"}], True),
    ([{"type": "json", "data": 42}, {"type": "text", "text": "needle"}], True),
    ([{"type": "reply", "chain": [{"type": "json", "data": None}]}, {"type": "text", "text": "needle"}], True),
    (None, False),
    ({"invalid": "chain"}, False),
])
async def test_malformed_archive_is_readable_and_does_not_block_later_matches(session_plugin, history, chain, matched):
    """Search, restoration and tool projection tolerate bad elements without rewriting archives."""
    from sqlalchemy import update

    from core.db.models import MessageRecord

    bad_record = await archive_text(history, "replace", "malformed")
    good_record = await archive_text(history, "needle", "valid")
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).where(MessageRecord.id == bad_record).values(chain=chain))

    page = await history.get_messages(session_id=SID, keyword="needle")
    expected = {good_record, bad_record} if matched else {good_record}
    assert {record.id for record in page.messages} == expected
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), keyword="needle"))
    expected_platform_ids = {"valid", "malformed"} if matched else {"valid"}
    assert {line.split("[message_id: ", 1)[1].split("]", 1)[0] for line in result["messages"]} == expected_platform_ids

    unfiltered = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID)))
    assert {line.split("[message_id: ", 1)[1].split("]", 1)[0] for line in unfiltered["messages"]} == {"malformed", "valid"}
    assert (await history.get_message(bad_record)).to_dict()["chain"] == chain
    assert not (await history.get_messages(session_id=SID, keyword="not found")).messages


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_count", [1, 2, 4])
async def test_keyword_search_concurrency_and_cancellation_keep_unfiltered_reads_available(history, monkeypatch, cancel_count):
    """Cancelled scans retain their slot until matching finishes; queued scans cannot consume connections."""
    from sqlalchemy import event

    from core.db.mixins import messages

    await archive_text(history, "needle", "one")
    original = messages._message_chain_matches
    loop = asyncio.get_running_loop()
    both_started = asyncio.Event()
    release = threading.Event()
    lock = threading.Lock()
    active = 0
    maximum = 0
    queries = []

    def blocking_match(chain, keyword, *, depth=0):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                loop.call_soon_threadsafe(both_started.set)
        try:
            if not release.wait(10):
                raise TimeoutError("Test did not release the search workers")
            return original(chain, keyword, depth=depth)
        finally:
            with lock:
                active -= 1

    def capture(conn, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    monkeypatch.setattr(messages, "_message_chain_matches", blocking_match)
    engine = history.db.db.engine.sync_engine
    event.listen(engine, "before_cursor_execute", capture)
    tasks = [asyncio.create_task(history.get_messages(session_id=SID, keyword="needle")) for _ in range(6)]
    try:
        await asyncio.wait_for(both_started.wait(), timeout=5)
        assert len(queries) == 2
        tasks[-1].cancel()
        with pytest.raises(asyncio.CancelledError):
            await tasks[-1]
        for _ in range(cancel_count):
            tasks[0].cancel()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not tasks[0].done()
            assert len(queries) == 2

        page = await asyncio.wait_for(history.get_messages(session_id=SID), timeout=2)
        assert len(page.messages) == 1
        release.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=5)
        assert isinstance(results[0], asyncio.CancelledError)
        assert isinstance(results[-1], asyncio.CancelledError)
        assert all(len(result.messages) == 1 for result in results[1:-1])
        assert maximum == 2
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        event.remove(engine, "before_cursor_execute", capture)


@pytest.mark.anyio
async def test_keyword_search_failure_releases_shared_slots(history, monkeypatch):
    """Matching failures must release database resources and search slots for later calls."""
    from core.db.mixins import messages

    await archive_text(history, "needle", "one")
    original = messages._message_chain_matches

    def fail_match(chain, keyword, *, depth=0):
        raise ValueError("invalid archive")

    monkeypatch.setattr(messages, "_message_chain_matches", fail_match)
    results = await asyncio.wait_for(asyncio.gather(
        *(history.get_messages(session_id=SID, keyword="needle") for _ in range(4)),
        return_exceptions=True,
    ), timeout=5)
    assert all(isinstance(result, ValueError) for result in results)
    monkeypatch.setattr(messages, "_message_chain_matches", original)
    assert len((await asyncio.wait_for(history.get_messages(session_id=SID, keyword="needle"), timeout=5)).messages) == 1

@pytest.mark.anyio
@pytest.mark.parametrize("worker_fails", [False, True])
async def test_matching_worker_drains_after_repeated_cancel_and_preserves_original_cancel(monkeypatch, worker_fails):
    """Repeated cancellation cannot finish the waiter while its worker still runs."""
    from core.db.mixins import messages

    loop = asyncio.get_running_loop()
    started = asyncio.Event()
    finished = asyncio.Event()
    release = threading.Event()

    def blocking_match(chain, keyword, *, depth=0):
        loop.call_soon_threadsafe(started.set)
        try:
            if not release.wait(10):
                raise TimeoutError("Test did not release its worker")
            if worker_fails:
                raise ValueError("Worker failed while cancellation was draining")
            return True
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(messages, "_message_chain_matches", blocking_match)
    cancellations = []

    async def run_match():
        try:
            return await messages._matching_message_records([SimpleNamespace(chain=[])], "needle")
        except asyncio.CancelledError as exc:
            cancellations.append(exc.args)
            raise

    task = asyncio.create_task(run_match())
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        for reason in ("original cancellation", "second cancellation", "third cancellation"):
            task.cancel(reason)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert not task.done()
            assert not finished.is_set()

        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cancellations == [("original cancellation",)]
        await asyncio.wait_for(finished.wait(), timeout=5)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.wait_for(finished.wait(), timeout=5)


@pytest.mark.parametrize("payload", [None, [], "invalid", 42])
def test_invalid_json_payload_uses_placeholder_without_rewriting_snapshot(payload):
    """Invalid JSON payloads remain inspectable instead of failing the history page."""
    from core.chat.message_elements import ElementType
    from core.chat.message_history import (
        ArchivedMessagePlaceholder,
        _deserialize_message_chain,
    )

    snapshot = [{"type": "json", "data": payload}]
    restored = _deserialize_message_chain(snapshot)
    assert isinstance(restored[0], ArchivedMessagePlaceholder)
    assert restored[0].type == ElementType.Json
    assert restored[0].data == {"type": "json", "data": payload}
    assert snapshot == [{"type": "json", "data": payload}]

@pytest.mark.anyio
@pytest.mark.parametrize("parts,keyword", [
    (["hello", " world"], "hello world"),
    (["he", "llo", "", " ", "world"], "HELLO WORLD"),
    (["跨", "会话", "搜索"], "跨会话"),
    (["Stra", "ße"], "STRASSE"),
])
@pytest.mark.parametrize("quoted", [False, True])
async def test_adjacent_text_segments_have_equivalent_keyword_search_and_pagination(
    session_plugin, history, parts, keyword, quoted,
):
    """Visible text must match identically before and after adjacent segment splitting."""
    from core.chat.message_elements import Reply, Text
    from core.chat.message_utils import MessageChain

    expected = {}
    for label, segments in (("single", ["".join(parts)]), ("split", parts)):
        chain = MessageChain([Text(part) for part in segments])
        if quoted:
            chain = MessageChain([Reply("quoted-message", chain=chain)])
        message = incoming(label)
        message.chain = chain
        identity = await history.record_incoming(message, SID, "test")
        expected[identity] = (await history.get_message(identity)).to_dict()["chain"]

    found = []
    cursor = None
    for _ in range(3):
        page = json.loads(await session_plugin.get_message_history(
            SimpleNamespace(sid=SID), keyword=keyword, limit=1, cursor=cursor,
        ))
        for message in page["messages"]:
            label = message.split("[message_id: ", 1)[1].split("]", 1)[0]
            found.append(label)
            assert "".join(parts) in message
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(found) == len(set(found)) == 2
    assert set(found) == {"single", "split"}
    for identity, chain in expected.items():
        assert (await history.get_message(identity)).to_dict()["chain"] == chain
    assert cursor is None


@pytest.mark.parametrize("separator", [
    {"type": "image", "description": "photo"},
    {"type": "at", "pid": "12345678901234567890", "nickname": "Alice"},
    {"type": "notice", "text": "notice"},
    {"type": "reply", "chain": [{"type": "text", "text": "quoted"}]},
    {"type": "text", "text": None},
    None,
])
def test_keyword_search_does_not_join_text_across_other_elements(separator):
    """A non-text or malformed element separates otherwise adjacent text runs."""
    from core.db.mixins.messages import _message_chain_matches

    chain = [{"type": "text", "text": "hello"}, separator, {"type": "text", "text": " world"}]
    assert not _message_chain_matches(chain, "hello world")
    assert _message_chain_matches(chain, "hello")
    assert _message_chain_matches(chain, "world")


@pytest.mark.anyio
async def test_history_lines_use_configured_time_sender_content_and_platform_id(session_plugin, history):
    """Render readable lines without archive metadata or changes to stored messages."""
    message = incoming("platform-42")
    message.timestamp = 0
    message.sender.nickname = "小林"
    message.sender.user_id = "123456"
    message.chain[0].text = "午餐\n吃面"
    identity = await history.record_incoming(message, SID, "test")

    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), keyword="午餐"))
    assert result == {
        "session_id": SID,
        "messages": ["[Jan 01 1970 08:00 Thu] [message_id: platform-42] [user_nickname: 小林, user_id: 123456] | 午餐\\n吃面"],
        "next_cursor": None,
    }
    assert (await history.get_message(identity)).chain[0].text == "午餐\n吃面"

    session_plugin.ctx.get_timezone = lambda: timezone.utc
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID)))
    assert result["messages"][0].startswith("[Jan 01 1970 00:00 Thu]")


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["sent", "failed", "pending", "unknown"])
async def test_outgoing_history_keeps_delivery_state_and_missing_platform_id_visible(session_plugin, history, status):
    """Unconfirmed or failed outgoing messages must not appear as successfully sent."""
    from core.chat.message_elements import Text
    from core.chat.message_utils import MessageChain

    identity = await history.record_outgoing(
        SID, MessageChain([Text("你好")]), platform="test", self_id="self-123",
    )
    await history.finish_outgoing(identity, status=status)
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), direction="outgoing"))
    line = result["messages"][0]
    marker = "" if status == "sent" else f"[发送状态:{status}] "
    assert line.endswith(f"[message_id: 无] [user_nickname: 你, user_id: self-123] | {marker}你好")


@pytest.mark.anyio
async def test_history_lines_render_media_quotes_mentions_and_cards(session_plugin, history):
    """Keep visible media and quoted content in the compact text response."""
    from sqlalchemy import update

    from core.db.models import MessageRecord

    identity = await archive_text(history, "replace", "mixed")
    chain = [
        {"type": "at", "pid": "456", "nickname": "小明"},
        {"type": "reply", "message_id": "original-7", "chain": [{"type": "text", "text": "周五见"}]},
        {"type": "image", "description": "月亮", "file": "private/path", "file_type": "archive"},
        {"type": "record", "transcript": "下午开会"},
        {"type": "json", "data": {"地点": "会议室"}},
    ]
    async with history.db.db.transaction() as session:
        await session.execute(update(MessageRecord).where(MessageRecord.id == identity).values(chain=chain))
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), keyword="月亮"))
    line = result["messages"][0]
    for visible in ("[At 456(nickname: 小明)]", "[Reply ID: original-7 content: 周五见]", "[Image 月亮]", "[Record 下午开会]", '[Json card {"地点": "会议室"}]'):
        assert visible in line
    assert "private/path" not in line
    assert "[message_id: mixed]" in line
    assert (await history.get_message(identity)).to_dict()["chain"] == chain


@pytest.mark.anyio
@pytest.mark.parametrize("group", [False, True])
@pytest.mark.parametrize("notice", [False, True])
async def test_history_headers_match_kira_ai_message_format(session_plugin, history, group, notice):
    """Compare archived headers against the live plugin for direct/group messages and notices."""
    from importlib import import_module

    from core.chat.session import Group

    plugin_type = import_module("core.plugin.builtin_plugins.kira-ai.main").DefaultPlugin
    live_plugin = plugin_type(session_plugin.ctx, {})
    message = incoming("platform-header")
    message.timestamp = 0
    message.is_notice = notice
    message.message_str = "original"
    sid = SID
    if group:
        sid = "adapter:gm:channel:123"
        message.group = Group("channel:123", "未知")
    await history.record_incoming(message, sid, "test")

    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=sid)))
    assert result["messages"] == [live_plugin._format_user_message(message)]
    session_plugin.ctx.adapter_mgr.get_adapter.assert_not_called()
