import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException

from core.agent.message import OpenAIMessage
from core.chat.message_elements import Text, Image, At, Reply, Forward, Json, Sticker, Record, Video, File
from core.chat.message_history import MessageHistoryService, serialize_message_chain
from core.chat.message_utils import KiraIMMessage, KiraIMSentResult, MessageChain, User
from core.chat.memory_metadata import normalize_memory
from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.message_manager import MessageProcessor
from core.provider.llm_model import LLMRequest
from core.utils.media_refs import cleanup_session_media, resolve_media_references, store_session_media
from tests.test_session_manager_events import build_session_manager
from webui.routes.sessions import SessionsRoutes

SID = "adapter:dm:user"


@pytest.fixture
async def history(tmp_path, monkeypatch):
    monkeypatch.setattr("core.chat.message_history.get_data_path", lambda: tmp_path)
    monkeypatch.setattr("core.utils.media_refs.get_data_path", lambda: tmp_path)
    database = DatabaseManager(f"sqlite+aiosqlite:///{(tmp_path / 'history.db').as_posix()}")
    await database.init()
    db = DatabaseService(database)
    await db.init_tables()
    memories = build_session_manager(tmp_path, [])
    memories.event_bus = None
    service = MessageHistoryService(db, memories)
    yield service
    await database.dispose()


def incoming(identity="in-1", bot="bot"):
    return KiraIMMessage(
        message_id=identity, self_id=bot, chain=MessageChain([Text("original")]),
        timestamp=1, sender=User("user", "Alice"), raw_message={"private": "must not persist"},
    )


def processor(history, result=None, error=None):
    instance = object.__new__(MessageProcessor)
    instance.event_bus = None
    instance.kira_config = Mock()
    instance.session_manager = history.session_manager
    instance.prompt_manager = Mock()
    instance.provider_mgr = Mock()
    instance.tool_manager = Mock()
    instance.skills_manager = Mock()
    instance.mcp_manager = Mock()
    instance.db = history.db
    instance.message_history = history
    target = SimpleNamespace(
        send_direct_message=AsyncMock(return_value=result, side_effect=error),
        send_group_message=AsyncMock(return_value=result, side_effect=error),
    )
    adapter = SimpleNamespace(config={"self_id": "bot"}, info=SimpleNamespace(platform="test"),
                              get_capability=lambda _: target)
    instance.adapter_mgr = SimpleNamespace(get_adapter=lambda _: adapter)
    return instance, target


@pytest.mark.anyio
async def test_incoming_snapshot_dedup_accounts_and_notices(history):
    message = incoming()
    identity = await history.record_incoming(message, SID, "test")
    message.chain[0].text = "modified by plugin"
    assert await history.record_incoming(incoming(), SID, "test") == identity
    assert await history.record_incoming(incoming(bot="other-bot"), SID, "test") != identity
    for _ in range(2):
        notice = incoming("system_message")
        notice.is_notice = True
        await history.record_incoming(notice, SID, "test")
    record = await history.get_message(identity)
    assert record["chain"] == [{"type": "text", "text": "original"}]
    assert "source" not in record
    assert "raw_message" not in record
    assert "must not persist" not in json.dumps(record)
    assert len((await history.list_messages(SID))["messages"]) == 4


@pytest.mark.anyio
async def test_nested_chain_media_survives_original_file_removal(history, tmp_path):
    source = tmp_path / "original.png"
    source.write_bytes(b"image bytes")
    chain = MessageChain([
        Text("hi"), At("123", "Alice"),
        Reply("quoted", chain=MessageChain([Image(str(source))])),
        Forward(chains=[MessageChain([Json({"nested": [1, 2]})])]),
    ])
    stored = await serialize_message_chain(chain)
    source.unlink()
    image = stored[2]["chain"][0]
    assert image["file_type"] == "archive"
    assert (tmp_path / image["file"]).read_bytes() == b"image bytes"
    assert stored[3] == {"type": "forward"}
    assert stored[1] == {"type": "at", "pid": "123", "nickname": "Alice"}


@pytest.mark.anyio
async def test_outgoing_success_failure_exception_and_proactive(history):
    for result, expected in [(KiraIMSentResult("sent-1"), "sent"),
                             (KiraIMSentResult(ok=False), "failed"), (None, "failed")]:
        instance, _ = processor(history, result)
        response = await instance.send_message_chain(SID, MessageChain([Text("out")]))
        row = await history.get_message(response.history_id)
        assert row["direction"] == "outgoing"
        assert "source" not in row
        assert row["sender_id"] == "bot"
        assert row["status"] == expected
        assert row["llm_message_id"] is None
    instance, _ = processor(history, error=TimeoutError("private endpoint"))
    with pytest.raises(TimeoutError):
        await instance.send_message_chain(SID, MessageChain([Text("uncertain")]))
    rows = (await history.list_messages(SID))["messages"]
    uncertain = next(row for row in rows if row["status"] == "unknown")
    assert uncertain["error_type"] == "TimeoutError"
    assert "private endpoint" not in json.dumps(rows)


@pytest.mark.anyio
async def test_many_messages_link_to_exact_user_and_assistant_and_survive_pruning(history):
    inbound = [await history.record_incoming(incoming(identity), SID, "test") for identity in ("a", "b")]
    user = OpenAIMessage(role="user", content="combined")
    user.to_memory_dict()
    await history.link_incoming_messages(SID, user.extra["llm_message_id"], inbound)
    first = OpenAIMessage(role="assistant", content="first step")
    second = OpenAIMessage(role="assistant", content="second step")
    instance, _ = processor(history, KiraIMSentResult("out-id"))
    emitted = []
    for memory in (first, first, second):
        result = await instance.send_message_chain(SID, MessageChain([Text(memory.content)]),
                                                    memory_message=memory)
        emitted.append(result.history_id)
    history.session_manager.update_memory(SID, [user, first, second])
    linked_inputs = (await history.get_messages_by_llm_message_id(SID, user.extra["llm_message_id"]))["messages"]
    assert {row["id"] for row in linked_inputs} == set(inbound)
    linked = (await history.get_messages_by_llm_message_id(SID, first.extra["llm_message_id"]))["messages"]
    assert {row["id"] for row in linked} == set(emitted[:2])
    assert (await history.get_message(emitted[2]))["llm_message_id"] == second.extra["llm_message_id"]
    assert (await history.get_message(inbound[0]))["llm_message_id"] == user.extra["llm_message_id"]
    row = await history.get_message(emitted[0])
    assert history.get_linked_memory(row)["content"] == "first step"
    history.session_manager.write_memory(SID, [])
    assert history.get_linked_memory(row) is None
    assert len((await history.list_messages(SID))["messages"]) == 5


@pytest.mark.anyio
async def test_metadata_is_storage_only_even_for_dictionary_provider_inputs():
    message = OpenAIMessage(role="assistant", content="hi")
    stored = message.to_memory_dict()
    stored["_extra"]["custom"] = {"private": True}
    request = LLMRequest(messages=[stored])
    assert request.messages[0].extra == stored["_extra"]
    assert "_extra" not in request.messages[0].to_dict()
    assert "extra" not in request.messages[0].to_dict()
    assert await resolve_media_references([stored]) == [{"role": "assistant", "content": "hi"}]
    assert "_extra" in stored


def test_edit_metadata_stable_and_copies_cannot_reuse_links():
    original = normalize_memory([[{"role": "user", "content": "before"}]])
    edited = copy.deepcopy(original)
    edited[0][0]["content"] = "after"
    edited[0].append(copy.deepcopy(edited[0][0]))
    saved = normalize_memory(edited, previous=original)
    assert saved[0][0]["_extra"] == original[0][0]["_extra"]
    assert saved[0][1]["_extra"]["llm_message_id"] != saved[0][0]["_extra"]["llm_message_id"]
    assert all("message_ids" not in message["_extra"] for message in saved[0])


@pytest.mark.anyio
async def test_cursor_pagination_stable_with_identical_timestamps(history, monkeypatch):
    monkeypatch.setattr("core.chat.message_history.time.time_ns", lambda: 1000000000)
    ids = {await history.record_incoming(incoming(str(index)), SID, "test") for index in range(5)}
    page = await history.list_messages(SID, limit=2)
    found = []
    while True:
        found.extend(row["id"] for row in page["messages"])
        if not page["next_cursor"]:
            break
        page = await history.list_messages(SID, limit=2, cursor=page["next_cursor"])
    assert len(found) == len(set(found)) == 5
    assert set(found) == ids
    with pytest.raises(ValueError):
        await history.list_messages("other:dm:user", cursor=found[0])


@pytest.mark.anyio
async def test_startup_preserves_database_links_and_marks_incomplete_sends_unknown(history):
    identity = await history.record_incoming(incoming(), SID, "test")
    memory = OpenAIMessage(role="user", content="saved before crash")
    memory.to_memory_dict()
    await history.link_incoming_messages(SID, memory.extra["llm_message_id"], [identity])
    history.session_manager.update_memory(SID, [memory])
    pending = await history.record_outgoing(SID, MessageChain([Text("out")]), platform="test", self_id="bot")
    restored = MessageHistoryService(history.db, history.session_manager)
    await restored.initialize()
    row = await restored.get_message(identity)
    assert restored.get_linked_memory(row)["_extra"] == {"llm_message_id": memory.extra["llm_message_id"]}
    assert (await history.get_message(identity))["llm_message_id"] == memory.extra["llm_message_id"]
    assert (await history.get_message(pending))["status"] == "unknown"


@pytest.mark.anyio
async def test_history_api_and_archive_only_sessions(history):
    identity = await history.record_incoming(incoming(), SID, "test")
    history.session_manager.chat_memory.clear()
    lifecycle = SimpleNamespace(session_manager=history.session_manager,
                                message_processor=SimpleNamespace(message_history=history))
    routes = SessionsRoutes(FastAPI(), lifecycle)
    assert (await routes.list_sessions())["sessions"][0]["history_count"] == 1
    assert (await routes.get_session(SID))["messages"] == []
    assert (await routes.get_message(identity))["memory"] is None
    with pytest.raises(HTTPException) as error:
        await routes.list_messages(SID, limit=0)
    assert error.value.status_code == 400
    with pytest.raises(HTTPException) as error:
        await routes.get_message("missing")
    assert error.value.status_code == 404
    assert all(route.dependencies for route in routes.get_routes())



@pytest.mark.anyio
async def test_full_batch_and_tool_loop_link_each_assistant_separately(history, monkeypatch):
    from core.adapter.adapter_info import AdapterInfo
    from core.agent.tool import ToolSet
    from core.chat.message_utils import KiraMessageBatchEvent
    from core.chat.session import Session
    from core.provider.llm_model import LLMResponse

    monkeypatch.setattr("core.message_manager.event_handler_reg.get_handlers", lambda *a, **kw: [])
    instance, target = processor(history, KiraIMSentResult("platform-id"))
    first = LLMResponse('<msg><text>one</text></msg><msg><text>two</text></msg>', tool_calls=[
        {"id": "call-1", "type": "function", "function": {"name": "check", "arguments": "{}"}}
    ])
    second = LLMResponse('<msg><text>three</text></msg>')
    model = SimpleNamespace(model=SimpleNamespace(provider_name="test", model_id="model", model_name="test"),
                            chat=AsyncMock(side_effect=[first, second]))

    async def execute_tool(event, response, tool_set):
        response.tool_results = [{"role": "tool", "tool_call_id": "call-1", "content": "result"}]

    async def parse(text, tag_set):
        return [MessageChain([Text(value)]) for value in (["one", "two"] if "one" in text else ["three"])]

    instance.session_manager = history.session_manager
    instance.kira_config = SimpleNamespace(get_config=lambda key, default=None: {"bot_config.agent.max_tool_loop": 2, "bot_config.bot.min_message_delay": 0, "bot_config.bot.max_message_delay": 0}.get(key, default))
    instance.provider_mgr = SimpleNamespace(get_default_llm=lambda: model)
    instance.prompt_manager = SimpleNamespace(get_agent_prompt=AsyncMock(return_value=[]))
    instance.skills_manager = SimpleNamespace(skills_info=[])
    instance.mcp_manager = SimpleNamespace(get_tool_server_map=lambda: {})
    instance.tool_manager = SimpleNamespace(build_tool_set=ToolSet, execute_tool=execute_tool)
    instance.db = SimpleNamespace(add_telemetry_llm_usage=AsyncMock())
    instance.session_locks = {}
    instance.message_delivery.parse_xml = parse
    event = KiraMessageBatchEvent(
        supported_elements=["text"], timestamp=1,
        adapter=AdapterInfo(True, "test", "adapter", "test"),
        session=Session("adapter", "dm", "user"), messages=[incoming("a"), incoming("b")],
    )
    await instance.handle_im_batch_message(event)
    memory = history.session_manager.get_existing_memory_snapshot(SID)[0]
    assert [message["role"] for message in memory] == ["user", "assistant", "tool", "assistant"]
    assert memory[1]["_extra"]["llm_message_id"] != memory[3]["_extra"]["llm_message_id"]
    for message, count in zip(memory, [2, 2, 0, 1]):
        assert set(message["_extra"]) == {"llm_message_id"}
        records = (await history.get_messages_by_llm_message_id(SID, message["_extra"]["llm_message_id"]))["messages"]
        assert len(records) == count
        for record in records:
            assert history.get_linked_memory(record) == message
    persisted = history.session_manager._load_memory(history.session_manager.chat_memory_path)
    assert "message_ids" not in json.dumps(persisted)
    assert target.send_direct_message.await_count == 3
    assert len((await history.list_messages(SID))["messages"]) == 5


@pytest.mark.anyio
async def test_stopped_or_discarded_incoming_is_recorded_before_plugin_changes(history, monkeypatch):
    from core.adapter.adapter_info import AdapterInfo
    from core.chat.message_utils import KiraMessageEvent

    class StopHandler:
        async def exec_handler(self, event):
            event.message.chain[0].text = "plugin changed"
            event.stop()

    instance, _ = processor(history)
    instance.session_manager = history.session_manager
    monkeypatch.setattr("core.message_manager.event_handler_reg.get_handlers", lambda *a, **kw: [StopHandler()])
    event = KiraMessageEvent(supported_elements=["text"], timestamp=1, message=incoming(),
                            adapter=AdapterInfo(True, "test", "adapter", "test"))
    await instance.handle_im_message(event)
    record = (await history.list_messages(SID))["messages"][0]
    assert record["chain"] == [{"type": "text", "text": "original"}]
    assert record["llm_message_id"] is None


def test_existing_llm_message_ids_survive_reload_and_new_roles_get_new_ids(tmp_path):
    manager = build_session_manager(tmp_path, [[{"role": "user", "content": "legacy"}]])
    manager._ensure_memory_format()
    snapshot = manager.get_existing_memory_snapshot(SID)
    identity = snapshot[0][0]["_extra"]["llm_message_id"]
    manager.chat_memory = manager._load_memory(manager.chat_memory_path)
    manager._ensure_memory_format()
    assert manager.get_existing_memory_snapshot(SID)[0][0]["_extra"]["llm_message_id"] == identity
    edited = copy.deepcopy(snapshot)
    edited[0][0]["role"] = "assistant"
    manager.write_memory(SID, edited)
    assert manager.get_existing_memory_snapshot(SID)[0][0]["_extra"]["llm_message_id"] != identity


@pytest.mark.anyio
@pytest.mark.parametrize("failed", [False, True])
async def test_remote_media_never_persists_credential_urls(history, tmp_path, monkeypatch, failed):
    async def download(url, path, **kwargs):
        assert kwargs["max_bytes"] == 20 * 1024 * 1024
        assert kwargs["timeout"] == 10.0
        if failed:
            raise TimeoutError("secret URL must not be logged or stored")
        from pathlib import Path
        Path(path).write_bytes(b"remote image")

    monkeypatch.setattr("core.chat.message_history.download_file", download)
    message = incoming()
    message.chain = MessageChain([Image("https://media.example/bot-secret/photo.png?token=private")])
    identity = await history.record_incoming(message, SID, "test")
    record = await history.get_message(identity)
    assert "bot-secret" not in json.dumps(record)
    assert "token=private" not in json.dumps(record)
    image = record["chain"][0]
    assert image["file_type"] == ("unavailable" if failed else "archive")
    if failed:
        assert "file" not in image
    else:
        assert image["file"].startswith("session_media/archive/")
        assert (tmp_path / image["file"]).read_bytes() == b"remote image"
    assert not list((tmp_path / "session_media").rglob("*.download"))


@pytest.mark.anyio
@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
@pytest.mark.parametrize("source_type", ["path", "base64", "data_url", "url"])
async def test_all_media_store_only_local_relative_paths(history, tmp_path, monkeypatch, direction, source_type):
    raw = b"persistent media payload"
    encoded = base64.b64encode(raw).decode("ascii")
    source_path = tmp_path / "temporary-media.bin"
    source_path.write_bytes(raw)
    source = {
        "path": str(source_path),
        "base64": "base64://" + encoded,
        "data_url": "data:application/octet-stream;base64," + encoded,
        "url": "https://media.example/file?token=temporary",
    }[source_type]

    async def download(url, path, **kwargs):
        Path(path).write_bytes(raw)

    monkeypatch.setattr("core.chat.message_history.download_file", download)
    media = MessageChain([
        Image(source), Sticker(sticker=source), Record(source), Video(source), File(source),
    ])
    chain = MessageChain([Reply("quoted", chain=media), Forward(chains=[media])])
    if direction == "incoming":
        message = incoming()
        message.chain = chain
        identity = await history.record_incoming(message, SID, "test")
    else:
        identity = await history.record_outgoing(SID, chain, platform="test", self_id="bot")
    row = await history.get_message(identity)
    serialized = json.dumps(row["chain"])
    assert encoded not in serialized
    assert "https://" not in serialized
    assert "base64" not in serialized
    assert "temporary-media.bin" not in serialized
    source_path.unlink()
    paths = set()
    assert row["chain"][1] == {"type": "forward"}
    for element in row["chain"][0]["chain"]:
        relative = element["file"]
        assert element["file_type"] == "archive"
        assert relative.startswith("session_media/archive/")
        assert not Path(relative).is_absolute()
        assert (tmp_path / relative).read_bytes() == raw
        paths.add(relative)
    assert len(paths) == 1
    assert not list((tmp_path / "session_media").rglob("*.tmp"))
    assert not list((tmp_path / "session_media").rglob("*.download"))


@pytest.mark.anyio
async def test_archive_survives_session_media_cleanup(history, tmp_path):
    reference = await store_session_media(Image("data:image/png;base64,aGVsbG8="), SID, "platform-id")
    source = tmp_path / reference["path"]
    message = incoming()
    message.chain = MessageChain([Image(str(source))])
    identity = await history.record_incoming(message, SID, "test")
    record = await history.get_message(identity)
    archived = tmp_path / record["chain"][0]["file"]

    cleanup_session_media(SID, [])

    assert not source.exists()
    assert archived.read_bytes() == b"hello"
    assert archived.is_relative_to(tmp_path / "session_media")


@pytest.mark.anyio
async def test_incoming_tracking_preserves_message_fields_and_releases_references(history):
    import gc
    import weakref
    from dataclasses import fields

    assert {"source", "history_id"}.isdisjoint(field.name for field in fields(KiraIMMessage))
    message = incoming("system_message")
    message.is_notice = True
    message.extra = {"plugin_data": {"retained": True}}
    attributes = dict(message.__dict__)
    identity = await history.record_incoming(message, SID, "test")
    assert message.__dict__ == attributes
    message.chain[0].text = "changed after persistence"
    assert await history.record_incoming(message, SID, "test") == identity
    row = await history.get_message(identity)
    assert row["chain"][0]["text"] == "original"
    assert "source" not in row
    assert len((await history.list_messages(SID))["messages"]) == 1
    reference = weakref.ref(message)
    del message
    gc.collect()
    assert reference() is None
    assert not history._incoming_records


@pytest.mark.anyio
async def test_persisted_messages_keep_full_session_identity(history):
    sessions = ["adapter:dm:user", "adapter:gm:user", "other-adapter:dm:user"]
    incoming_ids = set()
    for sid in sessions:
        identity = await history.record_incoming(incoming("same-platform-id"), sid, "test")
        incoming_ids.add(identity)
        outgoing_id = await history.record_outgoing(
            sid, MessageChain([Text("reply")]), platform="test", self_id="bot")
        assert (await history.get_message(identity))["session_id"] == sid
        assert (await history.get_message(outgoing_id))["session_id"] == sid
        records = (await history.list_messages(sid))["messages"]
        assert {row["id"] for row in records} == {identity, outgoing_id}
        assert {row["session_id"] for row in records} == {sid}
    assert len(incoming_ids) == len(sessions)


@pytest.mark.anyio
async def test_database_links_survive_memory_edits_without_reverse_links(history):
    identity = await history.record_incoming(incoming(), SID, "test")
    message = OpenAIMessage(role="user", content="original")
    message.to_memory_dict()
    await history.link_incoming_messages(SID, message.extra["llm_message_id"], [identity])
    history.session_manager.update_memory(SID, [message])
    edited = history.session_manager.get_existing_memory_snapshot(SID)
    edited[0][0]["content"] = "edited"
    edited[0].append(copy.deepcopy(edited[0][0]))
    history.session_manager.write_memory(SID, edited)
    snapshot = history.session_manager.get_existing_memory_snapshot(SID)
    record = await history.get_message(identity)
    assert history.get_linked_memory(record) == snapshot[0][0]
    assert record["llm_message_id"] == message.extra["llm_message_id"]
    assert "message_ids" not in json.dumps(snapshot)
    copied = snapshot[0][1]["_extra"]["llm_message_id"]
    assert copied != message.extra["llm_message_id"]
    assert (await history.get_messages_by_llm_message_id(SID, copied))["messages"] == []


@pytest.mark.anyio
async def test_incoming_link_update_is_scoped_to_session_and_direction(history):
    source = await history.record_incoming(incoming(), SID, "test")
    other = await history.record_incoming(incoming(), "other:dm:user", "test")
    outgoing = await history.record_outgoing(
        SID, MessageChain([Text("sent")]), platform="test", self_id="bot", llm_message_id="assistant-id")
    await history.link_incoming_messages(SID, "user-id", [source, other, outgoing])
    await history.link_incoming_messages(SID, "unused", [])
    assert (await history.get_message(source))["llm_message_id"] == "user-id"
    assert (await history.get_message(other))["llm_message_id"] is None
    assert (await history.get_message(outgoing))["llm_message_id"] == "assistant-id"


@pytest.mark.anyio
@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
async def test_forward_placeholder_does_not_archive_contents(history, tmp_path, monkeypatch, direction):
    archive = Mock()
    monkeypatch.setattr("core.chat.message_history._archive_media", archive)
    forward = Forward(
        message_id=["forward-id"],
        chains=[MessageChain([
            Text("private forwarded text"),
            Image("https://media.example/image?token=temporary"),
            Forward(chains=[MessageChain([Image("base64://aGVsbG8=")])]),
        ])],
    )
    chain = MessageChain([forward, Reply("quoted", chain=MessageChain([forward]))])
    if direction == "incoming":
        message = incoming()
        message.chain = chain
        identity = await history.record_incoming(message, SID, "test")
    else:
        identity = await history.record_outgoing(SID, chain, platform="test", self_id="bot")
    row = await history.get_message(identity)
    assert row["chain"] == [
        {"type": "forward"},
        {"type": "reply", "message_id": "quoted", "message_content": None,
         "chain": [{"type": "forward"}]},
    ]
    archive.assert_not_called()
    assert not (tmp_path / "session_media").exists()
    assert forward.chains[0][0].text == "private forwarded text"
    assert len(forward.chains[0]) == 3
