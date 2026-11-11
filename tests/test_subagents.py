import asyncio
from types import SimpleNamespace
from typing import ClassVar
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import text

from core.adapter.adapter_info import AdapterInfo
from core.agent.config import AgentExecutionConfig, SubAgentConfig
from core.agent.message import OpenAIMessage
from core.agent.subagent_event import SubAgentEvent
from core.agent.subagent_executor import SubAgentToolExecutor
from core.agent.subagent_manager import (
    SUBAGENT_COMPLETED_EVENT,
    SUBAGENT_TOOL_NAMES,
    SubAgentManager,
)
from core.agent.tool import ToolSet
from core.chat.message_elements import Image, Text
from core.chat.message_history import MessageHistoryService
from core.chat.message_router import MessageRouter
from core.chat.message_utils import KiraIMMessage, KiraMessageBatchEvent, MessageChain
from core.chat.session import Session, User
from core.chat.session_manager import SessionManager
from core.chat.subagent_route import SubAgentRoute
from core.persona.persona_manager import PersonaManager
from core.provider import LLMResponse
from core.utils.tool_utils import BaseTool


class RecordingTool(BaseTool):
    name = "record"
    description = "Record event identity"
    parameters: ClassVar[dict] = {"type": "object", "properties": {}}

    def __init__(self):
        super().__init__()
        self.events = []

    async def execute(self, event):
        self.events.append(event)
        return "recorded"


@pytest.fixture
async def agents(session_db):
    sessions = SessionManager(session_db, {"bot_config": {"bot": {"max_memory_length": 100}}})
    parent = await sessions.get_session("platform:dm:parent", ensure_session=True)
    model = SimpleNamespace(
        model=SimpleNamespace(provider_id="test", provider_name="test", model_id="test", model_name="Test"),
        chat=AsyncMock(return_value=LLMResponse("result")),
    )
    manager = SubAgentManager(
        sessions,
        SimpleNamespace(get_default_llm=lambda: model),
        message_history=MessageHistoryService(session_db, sessions),
        event_bus=Mock(publish=AsyncMock()),
        persona_manager=PersonaManager(sessions.db),
    )
    try:
        yield manager, sessions, parent, model
    finally:
        await manager.shutdown(timeout=0)


def _source_batch(session, supported_elements):
    return KiraMessageBatchEvent(
        supported_elements=supported_elements,
        timestamp=1,
        adapter=AdapterInfo(
            enabled=True,
            adapter_id="adapter",
            name=session.adapter_name,
            platform="test",
        ),
        session=session,
        messages=[KiraIMMessage(
            message_id="parent-message",
            self_id="bot",
            bot=User("bot", "Parent Bot"),
            chain=MessageChain([Text("original IM input")]),
            timestamp=1,
        )],
    )


@pytest.mark.anyio
async def test_background_agent_has_independent_session_and_parent_tool_permissions(agents):
    manager, sessions, parent, model = agents
    source_event = _source_batch(parent, ["text", "image"])
    tool = RecordingTool()
    model.chat.side_effect = [
        LLMResponse("", tool_calls=[{"id": "call", "function": {"name": "record", "arguments": "{}"}}]),
        LLMResponse("child result"),
    ]
    info = await manager.spawn(
        "delegated task",
        parent_id=parent.internal_id,
        parent_tools=ToolSet([tool]),
        source_event=source_event,
    )
    assert info["status"] == "queued"
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done" and result["result"] == "child result"
    session = await sessions.resolve_session(info["id"])
    assert session.kind == "subagent" and session.parent_id == parent.internal_id
    assert session.session_id == session.internal_id == info["id"]
    assert session.sid != parent.sid
    event = tool.events[0]
    executor = manager._agents[info["id"]].executor
    assert isinstance(executor.tool_executor, SubAgentToolExecutor)
    assert executor.tool_executor.context is executor.context
    assert isinstance(event, SubAgentEvent)
    assert isinstance(event, KiraMessageBatchEvent)
    assert event.sid == event.session.sid == parent.sid
    assert event.agent_session.sid == session.sid
    assert event.messages[-1].message_str == "delegated task"
    assert event.messages[-1].session.sid == parent.sid
    assert event.message_str == "delegated task"
    assert not event.is_group_message()
    assert event.adapter is source_event.adapter
    assert event.supported_elements == ["text", "image"]
    assert event.supported_elements is not source_event.supported_elements
    assert event.bot.user_id == event.self_id == "bot"
    assert event.bot.nickname == "Parent Bot"
    assert event.bot is not source_event.bot
    assert event.model_group == [model]
    assert [message.message_id for message in source_event.messages] == ["parent-message"]
    assert len(session.content) == 1
    assert [message["role"] for message in session.content[0]] == ["user", "assistant", "tool", "assistant"]
    assert (await sessions.get_session(parent.sid)).content == []


def test_subagent_batch_exposes_group_and_multimodal_task():
    group = Session("test", "gm", "group")
    event = SubAgentEvent(
        session=group,
        agent_session=Session("subagent", "dm", "child", kind="subagent"),
        content=OpenAIMessage(
            role="user",
            content=[
                {"type": "text", "text": "inspect this"},
                {"type": "image_url", "image_url": {"url": "https://example.invalid/image.png"}},
            ],
        ),
    )
    assert event.is_group_message()
    assert event.messages[0].group.group_id == group.session_id
    assert event.messages[0].chain[0].text == "inspect this"
    assert isinstance(event.messages[0].chain[1], Image)
    assert event.messages[0].native_content == event.content.content


def test_subagent_batch_only_uses_metadata_from_the_permission_session():
    event = SubAgentEvent(
        session=Session("test", "dm", "parent"),
        agent_session=Session("subagent", "dm", "child", kind="subagent"),
        content="",
    )
    event.set_source_batch(_source_batch(Session("test", "dm", "other"), ["image"]))
    event.begin_turn()
    event.append_input("task")
    assert event.adapter is None
    assert event.supported_elements == []
    assert event.self_id == ""


@pytest.mark.anyio
@pytest.mark.parametrize("mode", ["inherit", "exclude", "custom"])
async def test_tool_selection_uses_an_independent_tool_list(agents, mode):
    manager, _, parent, model = agents
    inherited, custom = RecordingTool(), RecordingTool()
    custom.name = "custom"
    parent_tools = ToolSet([inherited])
    config = SubAgentConfig(
        tool_mode=mode,
        excluded_tools=("record",) if mode == "exclude" else (),
        tool_names=("custom",) if mode == "custom" else (),
    )
    info = await manager.spawn(
        "task",
        parent_id=parent.internal_id,
        config=config,
        parent_tools=parent_tools,
        tools=ToolSet([custom]),
    )
    await manager.wait(info["id"], timeout=2)
    seen = model.chat.await_args.args[0].tool_set
    expected = {"record"} if mode == "inherit" else {"custom"} if mode == "custom" else set()
    assert {tool.name for tool in seen.tools} == expected
    assert parent_tools.tools == [inherited]
    assert seen.tools is not parent_tools.tools


@pytest.mark.anyio
async def test_followup_starts_a_fresh_turn_and_persists_each_turn_once(agents):
    manager, sessions, parent, model = agents
    info = await manager.spawn(
        "first",
        parent_id=parent.internal_id,
        config=SubAgentConfig(execution=AgentExecutionConfig(max_steps=1)),
    )
    await manager.wait(info["id"], timeout=2)
    await manager.followup(info["id"], "second", caller_id=parent.internal_id)
    result = await manager.wait(info["id"], timeout=2)
    session = await sessions.resolve_session(info["id"])
    assert result["turn"] == 2
    assert len(session.content) == 2
    assert [chunk[0]["content"] for chunk in session.content] == ["first", "second"]
    assert model.chat.await_count == 2


@pytest.mark.anyio
async def test_followup_reads_replaced_history_and_keeps_instruction(agents):
    manager, sessions, parent, model = agents
    info = await manager.spawn(
        "old input",
        parent_id=parent.internal_id,
        config=SubAgentConfig(instruction="Keep this instruction"),
    )
    await manager.wait(info["id"], timeout=2)
    await sessions.update_session(
        info["sid"],
        content=[[{"role": "user", "content": "replacement input"}]],
    )

    await manager.followup(info["id"], "next input")
    await manager.wait(info["id"], timeout=2)

    request = model.chat.await_args.args[0]
    assert [message.content for message in request.messages[:3]] == [
        "Keep this instruction", "replacement input", "next input",
    ]
    assert all(message.content != "old input" for message in request.messages)


@pytest.mark.anyio
async def test_followup_persists_running_state_without_an_empty_history_chunk(agents):
    manager, sessions, parent, model = agents
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()
        return LLMResponse("second result")

    model.chat.side_effect = chat
    await manager.followup(info["id"], "second")
    try:
        await asyncio.wait_for(entered.wait(), 2)
        saved = await sessions.resolve_session(info["id"])
        assert saved.data["subagent"]["status"] == "running"
        assert saved.data["subagent"]["turn"] == 2
        assert len(saved.content) == 1
    finally:
        release.set()
        await manager.wait(info["id"], timeout=2)
    saved = await sessions.resolve_session(info["id"])
    assert saved.data["subagent"]["status"] == "done"
    assert len(saved.content) == 2


@pytest.mark.anyio
async def test_ownership_is_enforced_and_root_agents_can_bind_permission_scope(agents):
    manager, sessions, parent, _ = agents
    other = await sessions.get_session("platform:dm:other", ensure_session=True)
    info = await manager.spawn("task", permission_session=parent)
    await manager.wait(info["id"], timeout=2)
    session = await sessions.resolve_session(info["id"])
    assert session.parent_id is None
    assert len(await manager.list_agents(caller_id=parent.internal_id)) == 1
    assert await manager.list_agents(caller_id=other.internal_id) == []
    for operation in (manager.get, manager.interrupt, manager.wait):
        with pytest.raises(PermissionError):
            await operation(info["id"], caller_id=other.internal_id)
    with pytest.raises(PermissionError):
        await manager.followup(info["id"], "wrong caller", caller_id=other.internal_id)


@pytest.mark.anyio
async def test_router_uses_child_identity_while_tools_use_permission_identity(agents):
    manager, sessions, parent, _ = agents
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    router = MessageRouter(sessions)
    router.register_route(SubAgentRoute(manager))
    event = SubAgentEvent(
        session=parent,
        agent_session=child,
        source_session=parent,
        content="next",
    )
    await router.handle_event(event)
    await manager.wait(info["id"], timeout=2)
    assert event.sid == parent.sid
    assert event.target_session.sid == child.sid
    receipt = await router.send_message_chain(child, MessageChain([Text("third")]))
    assert receipt.ok
    await manager.wait(info["id"], timeout=2)
    assert len((await sessions.resolve_session(info["id"])).content) == 3


@pytest.mark.anyio
async def test_model_failure_is_retained_and_logged(agents):
    manager, sessions, parent, model = agents
    model.chat.side_effect = ValueError("full model failure")
    info = await manager.spawn("task", parent_id=parent.internal_id)
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "error"
    assert "full model failure" in result["error"]
    saved = await sessions.resolve_session(info["id"])
    assert saved.data["subagent"]["status"] == "error"


@pytest.mark.anyio
async def test_old_schema_gets_real_kind_and_parent_columns(session_db):
    async with session_db.db.engine.begin() as connection:
        await connection.execute(text("DROP TABLE chat_sessions"))
        await connection.execute(text(
            "CREATE TABLE chat_sessions (id VARCHAR(37) PRIMARY KEY, session_key VARCHAR UNIQUE NOT NULL, "
            "title TEXT, description TEXT, content JSON NOT NULL DEFAULT '[]', created_at BIGINT, "
            "updated_at BIGINT, data JSON NOT NULL DEFAULT '{}')"
        ))
        await connection.execute(text(
            "INSERT INTO chat_sessions (id, session_key, title, content, data) "
            "VALUES ('old', 'platform:dm:old', 'Old', '[]', '{}')"
        ))
    await session_db.init_tables()
    await session_db.init_tables()
    row = await session_db.get_chat_session("platform:dm:old")
    assert row["kind"] == "im" and row["parent_id"] is None


@pytest.mark.anyio
async def test_queued_turn_and_steering_use_the_existing_executor_loop(agents):
    manager, sessions, parent, model = agents
    entered, release = asyncio.Event(), asyncio.Event()
    requests = []
    batches = []

    async def chat(request):
        requests.append([message.content for message in request.messages])
        event = manager._agents[info["id"]].executor.context.event
        batches.append((event.event_id, [message.message_str for message in event.messages]))
        if len(requests) == 1:
            entered.set()
            await release.wait()
        return LLMResponse(f"result {len(requests)}")

    model.chat.side_effect = chat
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await asyncio.wait_for(entered.wait(), 2)
    await manager.followup(info["id"], "focus on performance", steer=True)
    await manager.followup(info["id"], "second task")
    release.set()
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done" and result["turn"] == 2
    assert len(requests) == 3
    assert "focus on performance" in requests[1]
    assert "second task" in requests[2]
    assert [messages for _, messages in batches] == [
        ["first"], ["first", "focus on performance"], ["second task"],
    ]
    assert batches[0][0] == batches[1][0] != batches[2][0]
    saved = await sessions.resolve_session(info["id"])
    assert len(saved.content) == 2
    assert saved.content[0][0]["content"] == "first"
    assert saved.content[1][0]["content"] == "second task"


@pytest.mark.anyio
async def test_abort_finishes_current_call_and_discards_queued_turns(agents):
    manager, sessions, parent, model = agents
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()
        return LLMResponse("after abort")

    model.chat.side_effect = chat
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await asyncio.wait_for(entered.wait(), 2)
    await manager.followup(info["id"], "discard this")
    assert (await manager.interrupt(info["id"]))["status"] == "stopping"
    assert (await manager.wait(info["id"], timeout=0.01))["status"] == "stopping"
    release.set()
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "stopped"
    manager.event_bus.publish.assert_awaited_once()
    assert manager.event_bus.publish.await_args.args[0].payload["status"] == "stopped"
    assert model.chat.await_count == 1
    assert (await sessions.resolve_session(info["id"])).content[0][0]["content"] == "first"


@pytest.mark.anyio
async def test_concurrency_and_abort_while_waiting_for_a_slot(agents):
    manager, _, parent, model = agents
    manager.semaphore = asyncio.Semaphore(1)
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()
        return LLMResponse("finished")

    model.chat.side_effect = chat
    first = await manager.spawn("first", parent_id=parent.internal_id)
    await asyncio.wait_for(entered.wait(), 2)
    second = await manager.spawn("second", parent_id=parent.internal_id)
    await asyncio.sleep(0)
    assert model.chat.await_count == 1
    await manager.interrupt(second["id"])
    assert (await manager.wait(second["id"], timeout=2))["status"] == "stopped"
    assert model.chat.await_count == 1
    release.set()
    await manager.wait(first["id"], timeout=2)
    assert manager.semaphore._value == 1


@pytest.mark.anyio
async def test_shutdown_cancels_stuck_calls_and_does_not_leave_tasks(agents):
    manager, sessions, parent, model = agents
    entered = asyncio.Event()

    async def chat(request):
        entered.set()
        await asyncio.Event().wait()

    model.chat.side_effect = chat
    info = await manager.spawn("task", parent_id=parent.internal_id)
    await asyncio.wait_for(entered.wait(), 2)
    await manager.shutdown(timeout=0.01)
    assert manager._agents[info["id"]].task.done()
    assert (await sessions.resolve_session(info["id"])).data["subagent"]["status"] == "interrupted"
    manager.event_bus.publish.assert_not_awaited()
    with pytest.raises(RuntimeError, match="shutting down"):
        await manager.spawn("new")


@pytest.mark.anyio
async def test_deleting_an_active_agent_does_not_recreate_its_session(agents):
    manager, sessions, parent, model = agents
    entered = asyncio.Event()

    async def chat(request):
        entered.set()
        await asyncio.Event().wait()

    model.chat.side_effect = chat
    info = await manager.spawn("task", parent_id=parent.internal_id)
    await asyncio.wait_for(entered.wait(), 2)
    await sessions.delete_session(info["sid"])
    await manager.on_session_deleted(SimpleNamespace(payload={"session": info["sid"]}))
    assert await sessions.get_session(info["sid"]) is None
    manager.event_bus.publish.assert_not_awaited()
    with pytest.raises(ValueError, match="not found"):
        await manager.followup(info["id"], "cannot resurrect")


@pytest.mark.anyio
async def test_restart_retains_results_and_continues_the_saved_conversation(agents):
    manager, sessions, parent, model = agents
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    restored = SubAgentManager(
        sessions,
        manager.provider_manager,
        message_history=manager.message_history,
        event_bus=manager.event_bus,
    )
    try:
        await restored.initialize()
        assert (await restored.get(info["id"]))["result"] == "result"
        assert model.chat.await_count == 1
        await restored.followup(info["id"], "second", caller_id=parent.internal_id)
        await restored.wait(info["id"], timeout=2)
        saved = await sessions.resolve_session(info["id"])
        assert len(saved.content) == 2
        assert model.chat.await_count == 2
        assert len([message for message in model.chat.await_args.args[0].messages if message.role == "system"]) == 1
    finally:
        await restored.shutdown(timeout=0)


@pytest.mark.anyio
async def test_parent_deletion_keeps_child_history_and_clears_parent_reference(agents):
    manager, sessions, parent, _ = agents
    info = await manager.spawn("task", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    await sessions.delete_session(parent.sid)
    saved = await sessions.resolve_session(info["id"])
    assert saved.kind == "subagent" and saved.parent_id is None
    assert len(saved.content) == 1


@pytest.mark.anyio
async def test_tool_approval_can_replace_a_child_tool_result(agents, monkeypatch):
    from core.plugin.handlers import EventType, event_handler_reg

    manager, _, parent, model = agents
    tool = RecordingTool()
    model.chat.side_effect = [
        LLMResponse("", tool_calls=[{"id": "call", "function": {"name": "record", "arguments": "{}"}}]),
        LLMResponse("done"),
    ]
    contexts = []

    async def approve(ctx):
        contexts.append(ctx)
        ctx.set_result("Denied by approval")

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=approve)] if event_type == EventType.ON_TOOL_CALL else []
    ))
    info = await manager.spawn("task", parent_id=parent.internal_id, parent_tools=ToolSet([tool]))
    await manager.wait(info["id"], timeout=2)
    assert tool.events == []
    assert contexts[0].event.sid == parent.sid
    assert contexts[0].event.agent_session.internal_id == info["id"]


@pytest.mark.anyio
async def test_capacity_check_is_atomic_for_concurrent_spawns(agents):
    manager, sessions, parent, model = agents
    manager.max_agents = 1
    gate = asyncio.Event()

    async def chat(request):
        await gate.wait()
        return LLMResponse("done")

    model.chat.side_effect = chat
    results = await asyncio.gather(
        manager.spawn("one", parent_id=parent.internal_id),
        manager.spawn("two", parent_id=parent.internal_id),
        return_exceptions=True,
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len([result for result in results if isinstance(result, RuntimeError)]) == 1
    assert len([session for session in await sessions.get_sessions() if session.kind == "subagent"]) == 1
    gate.set()


@pytest.mark.anyio
async def test_native_tools_bind_the_caller_and_inherit_actual_request_tools(agents, tmp_path):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config.config_loader import KiraConfig
    from core.plugin.builtin_plugins.subagents.main import SubAgentsPlugin
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    tool = RecordingTool()
    config = dict.__new__(KiraConfig)
    config.update({"bot_config": {"agent": {"max_tool_loop": 2}}})
    registry = Mock(build_tool_set=Mock(return_value=ToolSet()))
    ctx = SimpleNamespace(
        session_mgr=sessions,
        subagent_mgr=manager,
        tool_mgr=registry,
        mcp_mgr=None,
        config=config,
    )
    request = LLMRequest(tool_set=ToolSet([tool]))
    plugin = SubAgentsPlugin(ctx, {})
    event = SimpleNamespace(session=parent)
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    await plugin.inject_tools(event, request)
    assert request.tool_set.get("spawn_agent") is None
    assert request.tool_set.get("followup_task") is not None
    preset = await manager.presets.save(SubAgentPreset(
        name="Default",
        instruction_source="custom",
    ))
    await plugin.inject_tools(event, request)
    schemas = request.tool_set.to_list()
    controls = schemas[-len(SUBAGENT_TOOL_NAMES):]
    assert {tool["function"]["name"] for tool in controls} == SUBAGENT_TOOL_NAMES
    for tool in controls:
        function = tool["function"]
        tool_type = type(request.tool_set.get(function["name"]))
        assert tool_type.get_schema() == function
        assert isinstance(function["description"], str) and function["description"]
        assert isinstance(function["parameters"], dict)
        assert function["parameters"]["type"] == "object"
    spawn_schema = next(tool["function"] for tool in controls if tool["function"]["name"] == "spawn_agent")
    assert spawn_schema["parameters"]["required"] == ["task", "preset_name"]
    assert set(spawn_schema["parameters"]["properties"]) == {"task", "preset_name", "name"}
    spawn = request.tool_set.get("spawn_agent")
    with pytest.raises(TypeError, match="preset_name"):
        await spawn.execute(event, task="delegate")
    for invalid in (None, "", " ", preset["id"]):
        with pytest.raises(ValueError, match="preset_name|Unknown subagent preset"):
            await spawn.execute(
                event,
                task="delegate",
                preset_name=invalid,
            )
    info = json.loads(await spawn.execute(
        event,
        task="delegate",
        preset_name=preset["name"],
    ))
    assert request.tool_set.get("wait_agent") is None
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done"
    child = await sessions.resolve_session(info["id"])
    assert child.data["subagent"]["settings"]["max_steps"] == -1
    registry.build_tool_set.assert_not_called()
    assert [tool.name for tool in model.chat.await_args.args[0].tool_set.tools] == ["record"]
    listed = json.loads(await request.tool_set.get("list_agents").execute(event))
    assert listed["agents"][0]["parent_id"] == parent.internal_id
    await request.tool_set.get("followup_task").execute(event, agent_id=info["id"], message="again")
    await manager.wait(info["id"], timeout=2)
    assert model.chat.await_count == 2


@pytest.mark.anyio
async def test_native_custom_tools_can_select_outside_the_parent_tool_list(agents, tmp_path):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config.config_loader import KiraConfig
    from core.plugin.builtin_plugins.subagents.main import SubAgentsPlugin
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    tool = RecordingTool()
    config = dict.__new__(KiraConfig)
    config.update({"bot_config": {"agent": {}}})
    ctx = SimpleNamespace(
        session_mgr=sessions,
        subagent_mgr=manager,
        tool_mgr=SimpleNamespace(build_tool_set=lambda: ToolSet([tool])),
        mcp_mgr=None,
        config=config,
    )
    request = LLMRequest(tool_set=ToolSet())
    event = SimpleNamespace(session=parent)
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        name="Custom",
        instruction_source="custom",
        tool_mode="custom",
        tools=["record"],
    ))
    await SubAgentsPlugin(ctx, {}).inject_tools(event, request)
    info = json.loads(await request.tool_set.get("spawn_agent").execute(
        event,
        task="custom",
        preset_name=preset["name"],
    ))
    await manager.wait(info["id"], timeout=2)
    assert [tool.name for tool in model.chat.await_args.args[0].tool_set.tools] == ["record"]
    ctx.mcp_mgr = SimpleNamespace(
        get_tool_server_map=lambda: {"record": "blocked"},
        is_server_allowed=lambda *_: False,
    )
    with pytest.raises(PermissionError):
        await request.tool_set.get("spawn_agent").execute(
            event,
            task="denied",
            preset_name=preset["name"],
        )


@pytest.mark.anyio
@pytest.mark.parametrize("persona_id", [None, "reviewer"])
async def test_preset_persona_follows_edits_for_existing_and_restored_agents(agents, tmp_path, persona_id):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.persona.model import PersonaInfo
    from core.plugin.builtin_plugins.subagents.tools import SpawnAgentTool
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    personas = manager.persona_manager
    await personas.create_persona(PersonaInfo(id="active", name="Active", content="Active persona"))
    await personas.create_persona(PersonaInfo(id="reviewer", name="Reviewer", content="Review persona"))
    await personas.set_active_persona("active")
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        name="Persona agent",
        persona_id=persona_id,
        instruction="This inactive custom prompt must be ignored",
    ))
    tool = SpawnAgentTool(
        ctx=SimpleNamespace(
            config=dict.__new__(KiraConfig),
            session_mgr=sessions,
            subagent_mgr=manager,
            persona_mgr=personas,
        ),
        source=parent,
        request=LLMRequest(tool_set=ToolSet()),
    )
    async def spawn():
        info = json.loads(await tool.execute(
            None,
            task="inspect",
            preset_name=preset["name"],
        ))
        await manager.wait(info["id"], timeout=2)
        return info

    first = await spawn()
    original = "Review persona" if persona_id else "Active persona"
    assert model.chat.await_args.args[0].messages[0].content == original
    child = await sessions.resolve_session(first["id"])
    settings = child.data["subagent"]["settings"]
    assert settings["instruction_source"] == "persona"
    assert settings["persona_id"] == persona_id
    assert settings["instruction"] == ""
    await personas.update_persona(PersonaInfo(
        id=persona_id or "active",
        content="Updated persona",
    ))
    second = await spawn()
    assert model.chat.await_args.args[0].messages[0].content == "Updated persona"
    assert second["id"] != first["id"]
    await manager.followup(first["id"], "continue", caller_id=parent.internal_id)
    await manager.wait(first["id"], timeout=2)
    assert model.chat.await_args.args[0].messages[0].content == "Updated persona"
    assert sum(message.role == "system" for message in model.chat.await_args.args[0].messages) == 1
    manager._agents.clear()
    await personas.update_persona(PersonaInfo(
        id=persona_id or "active",
        content="Updated again after restoration",
    ))
    await manager.followup(first["id"], "continue", caller_id=parent.internal_id)
    await manager.wait(first["id"], timeout=2)
    assert model.chat.await_args.args[0].messages[0].content == "Updated again after restoration"
    assert sum(message.role == "system" for message in model.chat.await_args.args[0].messages) == 1
    if persona_id is None:
        await personas.set_active_persona("reviewer")
        await manager.followup(first["id"], "active persona changed", caller_id=parent.internal_id)
        await manager.wait(first["id"], timeout=2)
        assert model.chat.await_args.args[0].messages[0].content == "Review persona"
    if persona_id:
        await personas.delete_persona(persona_id)
    else:
        async with sessions.db.db.engine.begin() as connection:
            await connection.execute(text("UPDATE personas SET is_active = 0"))
    before = model.chat.await_count
    await manager.followup(first["id"], "missing persona", caller_id=parent.internal_id)
    failure = await manager.wait(first["id"], timeout=2)
    assert failure["status"] == "error"
    assert "persona is unavailable" in failure["error"]
    assert model.chat.await_count == before


@pytest.mark.anyio
@pytest.mark.parametrize("boundary", ["tool", "provider_failover"])
async def test_persona_refreshes_between_calls_without_mutating_inflight_messages(agents, boundary):
    from httpx import Request
    from openai import APIConnectionError

    from core.persona.model import PersonaInfo

    manager, _, parent, model = agents
    personas = manager.persona_manager
    await personas.create_persona(PersonaInfo(id="live", name="Live", content="Original persona"))
    seen = []

    async def edit_persona():
        await personas.update_persona(PersonaInfo(id="live", content="Changed persona"))

    class EditPersonaTool(RecordingTool):
        async def execute(self, event):
            await edit_persona()
            return "changed"

    async def first_call(request):
        seen.append(request.messages[0])
        if boundary == "provider_failover":
            await edit_persona()
            raise APIConnectionError(request=Request("POST", "https://example.test"))
        return LLMResponse("", tool_calls=[{
            "id": "edit",
            "function": {"name": "record", "arguments": "{}"},
        }])

    async def next_call(request):
        seen.append(request.messages[0])
        return LLMResponse("done")

    if boundary == "tool":
        calls = iter([first_call, next_call])

        async def chat(request):
            return await next(calls)(request)

        model.chat.side_effect = chat
        models = [model]
    else:
        model.chat.side_effect = first_call
        fallback = SimpleNamespace(model=model.model, chat=AsyncMock(side_effect=next_call))
        models = [model, fallback]
    info = await manager.spawn(
        "task",
        parent_id=parent.internal_id,
        config=SubAgentConfig(
            instruction_source="persona",
            persona_id="live",
        ),
        parent_tools=ToolSet([EditPersonaTool()]),
        model_group=models,
    )
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done"
    assert [message.content for message in seen] == ["Original persona", "Changed persona"]
    assert seen[0] is not seen[1]
    context = manager._agents[info["id"]].executor.context
    assert sum(message.role == "system" for message in context.messages) == 1
    assert not any(message.role == "system" for message in context.new_messages)


@pytest.mark.anyio
async def test_native_preset_discovery_and_spawn_use_saved_settings(agents, tmp_path):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.plugin.builtin_plugins.subagents.main import SubAgentsPlugin
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Reviewer",
        description="Inspect performance",
        instruction="Focus only on performance",
        max_steps=2,
        tool_mode="exclude",
        tools=["record"],
    ))
    await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Hidden",
        enabled=False,
    ))
    config = dict.__new__(KiraConfig)
    request = LLMRequest(tool_set=ToolSet([RecordingTool()]))
    ctx = SimpleNamespace(
        config=config,
        session_mgr=sessions,
        subagent_mgr=manager,
    )
    plugin = SubAgentsPlugin(ctx, {})
    event = _source_batch(parent, ["text"])
    await plugin.inject_tools(event, request)
    await plugin.inject_tools(event, request)
    assert not request.system_prompt
    prompt = manager.presets.build_presets_prompt()
    assert not prompt.persist
    assert preset["id"] not in prompt.content
    assert preset["name"] in prompt.content
    assert "Inspect performance" in prompt.content
    assert "Hidden" not in prompt.content
    spawn = request.tool_set.get("spawn_agent")
    info = json.loads(await spawn.execute(
        event,
        task="inspect",
        preset_name=preset["name"],
    ))
    await manager.wait(info["id"], timeout=2)
    assert info["title"] == "Reviewer"
    assert manager._agents[info["id"]].executor.context.event.supported_elements == ["text"]
    used_request = model.chat.await_args.args[0]
    assert used_request.messages[0].content == "Focus only on performance"
    assert not used_request.tool_set.tools
    saved = await sessions.resolve_session(info["id"])
    assert saved.data["subagent"]["settings"]["max_steps"] == 2
    await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Changed",
        instruction="new",
        enabled=False,
    ), preset["id"])
    manager._agents.clear()
    followup_event = _source_batch(parent, ["text", "image"])
    await request.tool_set.get("followup_task").execute(
        followup_event,
        agent_id=info["id"],
        message="again",
    )
    assert (await manager.wait(info["id"], timeout=2))["status"] == "done"
    assert manager._agents[info["id"]].executor.context.event.supported_elements == ["text", "image"]
    assert model.chat.await_args.args[0].messages[0].content == "Focus only on performance"
    await manager.presets.delete(preset["id"])
    await manager.followup(info["id"], "after deletion", caller_id=parent.internal_id)
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "error"
    assert "Subagent preset is unavailable" in result["error"]
    assert model.chat.await_count == 2
    with pytest.raises(ValueError, match="Unknown subagent preset"):
        await spawn.execute(
            event,
            task="missing",
            preset_name=preset["name"],
        )


@pytest.mark.anyio
async def test_native_preset_cannot_bypass_disabled_state_or_custom_tool_permissions(agents, tmp_path):
    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.plugin.builtin_plugins.subagents.tools import SpawnAgentTool
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Custom",
        tool_mode="custom",
        tools=["record"],
    ))
    ctx = SimpleNamespace(
        config=dict.__new__(KiraConfig),
        session_mgr=sessions,
        subagent_mgr=manager,
        tool_mgr=SimpleNamespace(build_tool_set=lambda: ToolSet([RecordingTool()])),
        mcp_mgr=SimpleNamespace(
            get_tool_server_map=lambda: {"record": "blocked"},
            is_server_allowed=lambda *_: False,
        ),
    )
    spawn = SpawnAgentTool(
        ctx=ctx,
        source=parent,
        request=LLMRequest(tool_set=ToolSet()),
    )
    with pytest.raises(PermissionError, match="not allowed"):
        await spawn.execute(
            None,
            task="denied",
            preset_name=preset["name"],
        )
    with pytest.raises(TypeError, match="unexpected keyword argument"):
        await spawn.execute(
            None,
            task="override",
            preset_name=preset["name"],
            tools=[],
        )
    await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name=preset["name"],
        enabled=False,
    ), preset["id"])
    with pytest.raises(ValueError, match="disabled"):
        await spawn.execute(
            None,
            task="disabled",
            preset_name=preset["name"],
        )
    assert not await manager.list_agents()
    model.chat.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("restored", [False, True])
async def test_preset_model_is_resolved_for_each_turn_without_persisting_it(agents, tmp_path, restored):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.plugin.builtin_plugins.subagents.tools import SpawnAgentTool
    from core.provider import LLMRequest, ModelType

    manager, sessions, parent, model = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Selected model",
        model="test:test",
    ))
    providers = manager.provider_manager
    providers.get_model_client = Mock(return_value=model)
    default = SimpleNamespace(model=model.model, chat=AsyncMock(return_value=LLMResponse("default")))
    providers.get_default_llm = Mock(return_value=default)
    ctx = SimpleNamespace(
        config=dict.__new__(KiraConfig),
        session_mgr=sessions,
        subagent_mgr=manager,
    )
    tool = SpawnAgentTool(
        ctx=ctx,
        source=parent,
        request=LLMRequest(tool_set=ToolSet()),
    )
    info = json.loads(await tool.execute(
        None,
        task="first",
        preset_name=preset["name"],
    ))
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    assert child.data["subagent"]["preset_id"] == preset["id"]
    assert "models" not in child.data["subagent"]
    assert preset["id"] not in info.values()
    model.chat.assert_awaited_once()
    providers.get_model_client.assert_called_with("test", "test", ModelType.LLM)
    providers.get_default_llm.assert_not_called()
    await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Renamed model preset",
    ), preset["id"])
    if restored:
        manager._agents.clear()
        await manager.presets.initialize()
    await manager.followup(info["id"], "resumed", caller_id=parent.internal_id)
    assert (await manager.wait(info["id"], timeout=2))["result"] == "default"
    model.chat.assert_awaited_once()
    default.chat.assert_awaited_once()
    providers.get_default_llm.assert_called_once_with()
    assert "models" not in (await sessions.resolve_session(info["id"])).data["subagent"]


@pytest.mark.anyio
async def test_queued_subagent_turn_reads_model_changes_after_submission(agents, tmp_path):
    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.provider import ModelType

    manager, _, parent, model = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(name="Live model"))
    replacement = SimpleNamespace(model=model.model, chat=AsyncMock(return_value=LLMResponse("replacement")))
    manager.provider_manager.get_model_client = Mock(return_value=replacement)
    entered, release = asyncio.Event(), asyncio.Event()

    async def chat(request):
        entered.set()
        await release.wait()
        return LLMResponse("original")

    model.chat.side_effect = chat
    info = await manager.spawn(
        "first",
        parent_id=parent.internal_id,
        preset_id=preset["id"],
    )
    await asyncio.wait_for(entered.wait(), 2)
    await manager.followup(info["id"], "second")
    await manager.presets.save(SubAgentPreset(
        name=preset["name"],
        model="provider:replacement",
    ), preset["id"])
    release.set()
    result = await manager.wait(info["id"], timeout=2)
    assert result["turn"] == 2 and result["result"] == "replacement"
    model.chat.assert_awaited_once()
    replacement.chat.assert_awaited_once()
    manager.provider_manager.get_model_client.assert_called_once_with("provider", "replacement", ModelType.LLM)


@pytest.mark.anyio
@pytest.mark.parametrize("unavailable", [None, ValueError("Provider is disabled")])
async def test_unavailable_preset_model_does_not_silently_use_the_default(agents, tmp_path, unavailable):
    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.plugin.builtin_plugins.subagents.tools import SpawnAgentTool
    from core.provider import LLMRequest

    manager, sessions, parent, model = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    preset = await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Unavailable",
        model="provider:missing",
    ))
    providers = manager.provider_manager
    providers.get_model_client = Mock(
        return_value=None,
        side_effect=unavailable,
    )
    providers.get_default_llm = Mock(return_value=model)
    tool = SpawnAgentTool(
        ctx=SimpleNamespace(
            config=dict.__new__(KiraConfig),
            session_mgr=sessions,
            subagent_mgr=manager,
        ),
        source=parent,
        request=LLMRequest(tool_set=ToolSet()),
    )
    with pytest.raises(ValueError, match="disabled|unavailable"):
        await tool.execute(
            None,
            task="unavailable",
            preset_name=preset["name"],
        )
    providers.get_default_llm.assert_not_called()
    assert not await manager.list_agents()


@pytest.mark.anyio
async def test_archive_records_link_to_child_memory_and_usage_is_recorded(agents):
    manager, _, parent, _ = agents
    info = await manager.spawn("input", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    page = await manager.message_history.list_messages(info["sid"])
    assert {message.direction for message in page.messages} == {"incoming", "outgoing"}
    for message in page.messages:
        assert message.platform == "subagent"
        linked = await manager.message_history.get_linked_memory(message)
        assert linked["content"] in {"input", "result"}


@pytest.mark.anyio
@pytest.mark.parametrize(("content", "archived_text"), [
    ({"task": "检查"}, '{"task": "检查"}'),
    ({"type": "text", "text": "check"}, "check"),
    ([{"type": "image_url", "image_url": {}}], None),
])
async def test_archive_content_conversion_preserves_completion_notice(agents, content, archived_text):
    manager, sessions, parent, _ = agents
    info = await manager.spawn(
        OpenAIMessage(role="user", content=content),
        parent_id=parent.internal_id,
    )
    result = await manager.wait(info["id"], timeout=2)

    assert result["status"] == "done"
    manager.event_bus.publish.assert_awaited_once()
    assert manager.event_bus.publish.await_args.args[0].payload == result
    saved = await sessions.resolve_session(info["id"])
    assert saved.content[0][0]["content"] == content
    page = await manager.message_history.list_messages(info["sid"])
    archived = {message.direction: message.chain[0].text for message in page.messages}
    assert archived["outgoing"] == "result"
    assert archived.get("incoming") == archived_text


@pytest.mark.anyio
async def test_resume_uses_default_for_ephemeral_model_and_requires_reauthorized_tools(agents):
    manager, sessions, parent, model = agents
    tool = RecordingTool()
    info = await manager.spawn(
        "first",
        parent_id=parent.internal_id,
        model_group=[model],
        config=SubAgentConfig(tool_mode="custom", tool_names=("record",)),
        tools=ToolSet([tool]),
    )
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    assert "models" not in child.data["subagent"]
    assert "preset_id" not in child.data["subagent"]
    default = SimpleNamespace(model=model.model, chat=AsyncMock(return_value=LLMResponse("default")))
    provider = SimpleNamespace(
        get_model_client=Mock(return_value=model),
        get_default_llm=Mock(return_value=default),
    )
    restored = SubAgentManager(
        sessions,
        provider,
        message_history=manager.message_history,
        event_bus=manager.event_bus,
    )
    try:
        with pytest.raises(ValueError, match="tool set"):
            await restored.followup(info["id"], "missing tools")
        await restored.followup(info["id"], "second", tools=ToolSet([tool]))
        assert (await restored.wait(info["id"], timeout=2))["result"] == "default"
        provider.get_model_client.assert_not_called()
        provider.get_default_llm.assert_called_once_with()
        assert len((await sessions.resolve_session(info["id"])).content) == 2
    finally:
        await restored.shutdown(timeout=0)


@pytest.mark.anyio
async def test_event_bus_uses_child_target_instead_of_permission_sid(agents):
    from core.event_bus import EventBus

    manager, sessions, parent, _ = agents
    info = await manager.spawn("first", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    router = MessageRouter(sessions)
    router.register_route(SubAgentRoute(manager))
    bus = EventBus(Mock(), asyncio.Queue())
    im_handler = AsyncMock()
    bus.subscribe(KiraMessageBatchEvent, im_handler)
    bus.subscribe(SubAgentEvent, router.handle_event)
    event = SubAgentEvent(session=parent, agent_session=child, source_session=parent, content="next")
    await bus.publish(event)
    await bus._process_event(bus.event_queue.get_nowait())
    await manager.wait(info["id"], timeout=2)
    im_handler.assert_not_awaited()
    assert event.sid == parent.sid
    assert len((await sessions.resolve_session(info["id"])).content) == 2


@pytest.mark.anyio
async def test_new_turn_recomputes_tool_choice_when_inherited_tools_change(agents):
    manager, _, parent, model = agents
    info = await manager.spawn("no tools", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    await manager.followup(info["id"], "tools available", parent_tools=ToolSet([RecordingTool()]))
    await manager.wait(info["id"], timeout=2)
    assert model.chat.await_args.args[0].tool_choice == "auto"


@pytest.mark.anyio
async def test_forged_session_snapshot_does_not_bypass_owner_check(agents):
    from dataclasses import replace

    manager, sessions, parent, _ = agents
    other = await sessions.get_session("platform:dm:other", ensure_session=True)
    info = await manager.spawn("task", parent_id=other.internal_id)
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    forged = replace(child, parent_id=parent.internal_id, data={"subagent": {"scope_id": parent.internal_id}})
    with pytest.raises(PermissionError):
        await manager.get(forged, caller_id=parent.internal_id)


@pytest.mark.anyio
async def test_startup_preserves_malformed_legacy_im_data_and_marks_unfinished_children(agents):
    manager, sessions, parent, model = agents
    await sessions.db.save_chat_session("platform:dm:legacy", data=["original malformed data"])
    child = await sessions.create_subagent_session(
        parent_id=parent.internal_id,
        data={"subagent": {"status": "running"}},
    )
    await manager.initialize()
    assert (await sessions.resolve_session(child.internal_id)).data["subagent"]["status"] == "interrupted"
    assert (await sessions.db.get_chat_session("platform:dm:legacy"))["data"] == ["original malformed data"]
    model.chat.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failed", [False, True])
async def test_completed_turn_publishes_persisted_result_for_parent(agents, failed):
    manager, sessions, parent, model = agents
    if failed:
        model.chat.side_effect = ValueError("complete failure details")
    info = await manager.spawn("task", parent_id=parent.internal_id)
    result = await manager.wait(info["id"], timeout=2)
    manager.event_bus.publish.assert_awaited_once()
    event = manager.event_bus.publish.await_args.args[0]
    assert event.event_name == SUBAGENT_COMPLETED_EVENT
    assert event.source_plugin == "subagents"
    assert event.payload == result
    saved = await sessions.resolve_session(info["id"])
    assert saved.content
    assert saved.data["subagent"]["status"] == result["status"]
    assert result["status"] == ("error" if failed else "done")
    if failed:
        assert "complete failure details" in event.payload["error"]
    else:
        assert event.payload["result"] == "result"
        await manager.followup(info["id"], "next task")
        await manager.wait(info["id"], timeout=2)
        assert manager.event_bus.publish.await_count == 2
        assert [call.args[0].payload["turn"] for call in manager.event_bus.publish.await_args_list] == [1, 2]


@pytest.mark.anyio
async def test_root_agent_does_not_notify_its_permission_session(agents):
    manager, _, parent, _ = agents
    info = await manager.spawn("independent task", permission_session=parent)
    assert (await manager.wait(info["id"], timeout=2))["status"] == "done"
    manager.event_bus.publish.assert_not_awaited()


@pytest.mark.anyio
async def test_completion_notice_reaches_parent_through_event_bus_and_router(agents, monkeypatch):
    from core.chat.im_message_route import IMMessageRoute
    from core.chat.message_utils import KiraMessageEvent
    from core.event_bus import EventBus
    from core.plugin.builtin_plugins.subagents.main import SubAgentsPlugin
    from core.plugin.handlers import EventType, event_handler_reg
    from core.plugin.plugin_context import PluginContext

    manager, sessions, parent, _ = agents
    bus = EventBus(Mock(), asyncio.Queue())
    manager.event_bus = bus
    adapter = SimpleNamespace(
        info=SimpleNamespace(name="platform", platform="platform"),
        config={"self_id": "bot"},
        get_capability=Mock(side_effect=ValueError("No IM metadata")),
    )
    ctx = object.__new__(PluginContext)
    ctx.session_mgr = sessions
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = bus
    plugin = SubAgentsPlugin(ctx, {})
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(handler=plugin.notify_parent, exec_handler=plugin.notify_parent)]
        if event_type == EventType.ON_CUSTOM_EVENT else []
    ))
    workflow = SimpleNamespace(handle_event=AsyncMock())
    router = MessageRouter(sessions)
    router.register_route(IMMessageRoute(Mock(), ctx.adapter_mgr, workflow))
    bus.subscribe(KiraMessageEvent, router.handle_event)
    info = await manager.spawn("task", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    await bus._process_event(bus.event_queue.get_nowait())
    assert bus.event_queue.qsize() == 1
    notice = bus.event_queue.get_nowait()
    assert isinstance(notice, KiraMessageEvent)
    assert notice.session.internal_id == parent.internal_id
    assert notice.is_notice and notice.is_mentioned
    assert info["id"] in notice.message_repr
    assert "result" in notice.message_repr
    await bus._process_event(notice)
    workflow.handle_event.assert_awaited_once_with(notice)
    assert bus.event_queue.empty()


@pytest.mark.anyio
async def test_pending_notice_is_ignored_after_parent_deletion(agents):
    from core.plugin.builtin_plugins.subagents.main import SubAgentsPlugin

    manager, sessions, parent, _ = agents
    info = await manager.spawn("task", parent_id=parent.internal_id)
    await manager.wait(info["id"], timeout=2)
    event = manager.event_bus.publish.await_args.args[0]
    await sessions.delete_session(parent.sid)
    ctx = SimpleNamespace(session_mgr=sessions, publish_notice=AsyncMock())
    await SubAgentsPlugin(ctx, {}).notify_parent(event)
    ctx.publish_notice.assert_not_awaited()


@pytest.mark.anyio
async def test_notice_failure_preserves_completed_state_and_result(agents):
    manager, sessions, parent, _ = agents
    manager.event_bus.publish.side_effect = RuntimeError("notice queue failed")
    info = await manager.spawn("task", parent_id=parent.internal_id)
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done" and result["result"] == "result"
    assert (await sessions.resolve_session(info["id"])).data["subagent"]["status"] == "done"


@pytest.mark.anyio
async def test_subagent_default_has_no_step_limit_and_restores_it_for_followups(agents):
    manager, sessions, parent, model = agents
    tool = RecordingTool()
    model.chat.side_effect = [
        LLMResponse("", tool_calls=[{
            "id": f"call-{index}",
            "function": {"name": "record", "arguments": "{}"},
        }]) for index in range(7)
    ] + [LLMResponse("complete"), LLMResponse("follow-up complete")]
    assert SubAgentConfig().execution.max_steps == -1
    assert AgentExecutionConfig().max_steps == 5
    info = await manager.spawn(
        "task",
        parent_id=parent.internal_id,
        parent_tools=ToolSet([tool]),
    )
    result = await manager.wait(info["id"], timeout=2)
    assert result["status"] == "done"
    assert result["step_index"] == 8
    assert len(tool.events) == 7
    manager._agents.clear()
    await manager.followup(
        info["id"],
        "another task",
        caller_id=parent.internal_id,
        parent_tools=ToolSet([tool]),
    )
    result = await manager.wait(info["id"], timeout=2)
    assert result["result"] == "follow-up complete"
    child = await sessions.resolve_session(info["id"])
    assert child.data["subagent"]["settings"]["max_steps"] == -1
    assert result["step_index"] == 1


@pytest.mark.anyio
async def test_native_spawn_accepts_preset_step_limits_above_fifty(agents, tmp_path):
    import json

    from core.agent.subagent_presets import SubAgentPreset, SubAgentPresetStore
    from core.config import KiraConfig
    from core.plugin.builtin_plugins.subagents.tools import SpawnAgentTool
    from core.provider import LLMRequest

    manager, sessions, parent, _ = agents
    manager.presets = SubAgentPresetStore(tmp_path / "presets.json")
    tool = SpawnAgentTool(
        ctx=SimpleNamespace(
            config=dict.__new__(KiraConfig),
            session_mgr=sessions,
            subagent_mgr=manager,
        ),
        source=parent,
        request=LLMRequest(tool_set=ToolSet()),
    )
    preset = await manager.presets.save(SubAgentPreset(
        instruction_source="custom",
        name="Long task",
        max_steps=100,
    ))
    info = json.loads(await tool.execute(
        None,
        task="task",
        preset_name=preset["name"],
    ))
    await manager.wait(info["id"], timeout=2)
    child = await sessions.resolve_session(info["id"])
    assert child.data["subagent"]["settings"]["max_steps"] == 100
