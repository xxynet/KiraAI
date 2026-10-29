import itertools
import json
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
    )
    return SessionPlugin(ctx, {})


async def archive_text(history, text, identity, *, sid=SID):
    message = incoming(identity)
    message.chain[0].text = text
    return await history.record_incoming(message, sid, "test")


@pytest.mark.anyio
async def test_session_view_metadata_and_counts_without_exposing_memory(session_plugin, history, monkeypatch):
    await history.session_manager.update_session(
        SID, title="会话标题", description="会话描述",
        content=[[{"role": "user", "content": "private memory"}], [{"role": "assistant", "content": "reply"}]],
        data={"private_extension": "must not return"},
    )
    await archive_text(history, "first message", "one")
    await history.record_outgoing(SID, incoming().chain, platform="test", self_id="bot")
    get_session = AsyncMock(wraps=history.session_manager.get_session)
    monkeypatch.setattr(history.session_manager, "get_session", get_session)

    result = json.loads(await session_plugin.session_view(SimpleNamespace(sid=SID)))

    assert result["title"] == "会话标题" and result["description"] == "会话描述"
    assert result["history_count"] == 2 and result["context_chunk_count"] == 2
    assert result["incoming_count"] == result["outgoing_count"] == 1
    assert result["created_at"] and result["updated_at"] >= result["created_at"]
    assert result["first_message_at"] == 1 and result["last_message_at"] >= 1
    assert "private memory" not in json.dumps(result) and "private_extension" not in result
    get_session.assert_awaited_once_with(SID, include_content=False)
    session_plugin.ctx.adapter_mgr.get_adapter.assert_not_called()


@pytest.mark.anyio
async def test_history_only_session_view_and_prompt(session_plugin, history):
    archived_sid = "archive-only:dm:user"
    await archive_text(history, "retained message", "one", sid=archived_sid)
    result = json.loads(await session_plugin.session_view(SimpleNamespace(sid=archived_sid)))
    assert result["history_count"] == 1 and result["context_chunk_count"] == 0
    assert result["created_at"] is None and result["updated_at"] is None
    assert archived_sid in await session_plugin.get_session_list_prompt()
    assert await history.session_manager.get_session(archived_sid) is None


@pytest.mark.anyio
async def test_nonexistent_session_has_empty_history_and_no_metadata(session_plugin, history):
    sid = "nonexistent:dm:user"
    event = SimpleNamespace(sid=sid)
    assert json.loads(await session_plugin.session_view(event)) == {"error": "Session not found"}
    assert json.loads(await session_plugin.get_message_history(event)) == {
        "session_id": sid, "messages": [], "next_cursor": None,
    }
    assert await history.session_manager.get_session(sid) is None


@pytest.mark.anyio
async def test_keyword_search_precedes_pagination_and_scopes_direction(session_plugin, history, monkeypatch):
    clock = itertools.count(1_000_000_000, 1_000_000)
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: next(clock))
    expected = []
    for index in range(215):
        text = "中文 Match_100% \\ literal" if index in {0, 105, 210} else "unrelated"
        identity = await archive_text(history, text, str(index))
        if index in {0, 105, 210}:
            expected.append(identity)
    await archive_text(history, "中文 Match_100% \\ literal", "other", sid=OTHER)
    await history.record_outgoing(SID, incoming().chain, platform="test", self_id="bot")
    event = SimpleNamespace(sid=SID)
    found, cursor = [], None
    for _ in range(4):
        page = json.loads(await session_plugin.get_message_history(
            event, keyword="中文 match_100%", direction="incoming", limit=1, cursor=cursor,
        ))
        found.extend(row["id"] for row in page["messages"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert found == list(reversed(expected))
    assert cursor is None
    assert not (await history.get_messages(session_id=SID, keyword="absent")).messages
    assert len((await history.get_messages(session_id=SID, keyword="", limit=200)).messages) == 200


@pytest.mark.anyio
async def test_search_visible_unicode_nested_and_media_text_not_storage_metadata(history):
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
    assert json.loads(result)["messages"][0]["chain"][0]["chain"][0]["description"] == "月亮"
    assert (await history.get_message(record)).to_dict()["chain"] == chain


@pytest.mark.anyio
async def test_search_cursor_must_match_session_keyword_and_direction(history):
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
    result = json.loads(await session_plugin.get_message_history(SimpleNamespace(sid=SID), **options))
    assert "error" in result


@pytest.mark.anyio
@pytest.mark.parametrize("tool_name", ["session_view", "get_message_history"])
@pytest.mark.parametrize("target", ["", "missing", "x:feed:123", "x:dm:", 123, OTHER])
async def test_invalid_or_unauthorized_targets_never_query(session_plugin, tool_name, target, monkeypatch):
    get_session = AsyncMock()
    get_messages = AsyncMock()
    stats = AsyncMock()
    monkeypatch.setattr(session_plugin.ctx.session_mgr, "get_session", get_session)
    monkeypatch.setattr(session_plugin.ctx.message_history, "get_messages", get_messages)
    monkeypatch.setattr(session_plugin.ctx.message_history, "get_session_stats", stats)
    result = json.loads(await getattr(session_plugin, tool_name)(SimpleNamespace(sid=SID), target=target))
    assert "error" in result
    get_session.assert_not_awaited()
    get_messages.assert_not_awaited()
    stats.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("mode,sessions,allowed", [
    ("allow_list", [SID], True), ("allow_list", [OTHER], False),
    ("deny_list", [], True), ("deny_list", [SID], False),
    ("invalid", [], False),
])
async def test_cross_session_read_uses_calling_session_permission(session_plugin, history, mode, sessions, allowed):
    session_plugin.plugin_cfg = {"cross_session_read": {"permission_mode": mode, "session_list": sessions}}
    await archive_text(history, "target history", "target", sid=OTHER)
    event = SimpleNamespace(sid=SID)
    result = json.loads(await session_plugin.get_message_history(event, target=OTHER))
    metadata = json.loads(await session_plugin.session_view(event, target=OTHER))
    assert ("error" not in result) is allowed
    assert ("error" not in metadata) is allowed
    if allowed:
        assert result["messages"][0]["session_id"] == OTHER
        assert metadata["history_count"] == 1
        capability = session_plugin.ctx.adapter_mgr.get_adapter.return_value.get_capability.return_value
        capability.is_allowed.assert_called_with("channel:123", permission="im.group.receive")


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["missing_adapter", "no_im", "denied"])
async def test_cross_session_read_also_respects_adapter_policy(session_plugin, failure):
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
    assert "history-keyword" in str(log.call_args_list)
    assert log.call_args.args == (f"tool_result: {response.tool_results[0]['content']}",)

def test_session_tools_config_schema_has_matching_english_and_chinese_fields():
    from pathlib import Path

    from core.config.config_field import build_fields

    root = Path(__file__).resolve().parents[1] / "core/plugin/builtin_plugins/session_tools"
    schema = json.loads((root / "schema.json").read_text(encoding="utf-8"))
    assert len(build_fields(schema)) == 1

    def validate(fields):
        for field in fields.values():
            assert {"name", "hint"} <= field.keys()
            assert set(field["locales"]["zh"]) == {"name", "hint"}
            if "fields" in field:
                validate(field["fields"])

    validate(schema)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for field in ("display_name", "description"):
        assert field in manifest and field in manifest["locales"]["zh"]
