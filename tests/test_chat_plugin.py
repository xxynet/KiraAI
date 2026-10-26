import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.chat import Group, KiraIMMessage, KiraMessageEvent, MessageChain, User
from core.chat.message_elements import Text
from core.config.config_field import build_fields
from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin


def _plugin():
    ctx = SimpleNamespace(
        config={"bot_config": {"bot": {"max_message_interval": 0}}},
        get_buffer=lambda _sid: SimpleNamespace(get_length=lambda: 1),
        flush_session_messages=AsyncMock(),
    )
    plugin = DefaultChatPlugin(ctx, {})
    return plugin


@pytest.mark.anyio
async def test_terminate_cancels_pending_debounce_tasks():
    plugin = _plugin()
    sid = "test:dm:1"
    event = asyncio.Event()
    task = asyncio.create_task(plugin._debounce_loop(sid, event))
    plugin.session_events[sid] = event
    plugin.session_tasks[sid] = task
    await asyncio.sleep(0)

    await plugin.terminate()

    assert task.done()
    assert task.cancelled()
    assert plugin.session_tasks == {}
    assert plugin.session_events == {}


@pytest.mark.anyio
async def test_completed_debounce_task_releases_session_state():
    plugin = _plugin()
    sid = "test:dm:1"
    event = asyncio.Event()
    event.set()
    task = asyncio.create_task(plugin._debounce_loop(sid, event))
    plugin.session_events[sid] = event
    plugin.session_tasks[sid] = task

    await task

    plugin.ctx.flush_session_messages.assert_awaited_once_with(sid)
    assert sid not in plugin.session_tasks
    assert sid not in plugin.session_events


@pytest.mark.anyio
async def test_terminate_rejects_messages_arriving_during_cleanup():
    plugin = _plugin()
    sid = "test:dm:1"
    cancellation_received = asyncio.Event()
    release = asyncio.Event()

    async def wait_for_termination():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancellation_received.set()
            await release.wait()
            raise

    task = asyncio.create_task(wait_for_termination())
    plugin.session_events[sid] = asyncio.Event()
    plugin.session_tasks[sid] = task
    terminate_task = asyncio.create_task(plugin.terminate())
    await cancellation_received.wait()

    event = SimpleNamespace(buffer=Mock(), flush=Mock())
    try:
        await plugin.handle_msg(event)
        event.buffer.assert_not_called()
        event.flush.assert_not_called()
        assert plugin.session_tasks == {}
        assert plugin.session_events == {}
    finally:
        release.set()

    await terminate_task

@pytest.mark.anyio
async def test_buffer_threshold_uses_updated_bot_config():
    plugin = _plugin()
    event = SimpleNamespace(
        message=SimpleNamespace(chain=[]), is_mentioned=True,
        session=SimpleNamespace(sid="test:dm:1"), buffer=Mock(), flush=Mock(),
    )
    try:
        await plugin.handle_msg(event)
        event.flush.assert_not_called()
        plugin.ctx.config["bot_config"]["bot"] = {"max_buffer_messages": 2}
        await plugin.handle_msg(event)
        event.flush.assert_called_once()
    finally:
        await plugin.terminate()


@pytest.mark.anyio
async def test_debounce_uses_current_interval_when_wait_begins(monkeypatch):
    plugin = _plugin()
    sid = "test:dm:1"
    trigger = asyncio.Event()
    task = asyncio.create_task(plugin._debounce_loop(sid, trigger))
    plugin.session_events[sid] = trigger
    plugin.session_tasks[sid] = task
    await asyncio.sleep(0)
    plugin.ctx.config["bot_config"]["bot"] = {"max_message_interval": "0.25"}
    sleep = AsyncMock()
    monkeypatch.setattr("core.plugin.builtin_plugins.chat.main.asyncio.sleep", sleep)
    trigger.set()
    await task

    sleep.assert_awaited_once_with(0.25)
    plugin.ctx.flush_session_messages.assert_awaited_once_with(sid)


@pytest.mark.parametrize("name,value", [
    ("max_unmentioned_messages", 2),
    ("receive_unmentioned", False),
    ("group_chat_prompt", "updated"),
    ("group_proactive_chat", True),
    ("group_proactive_chat_probability", 0.75),
    ("waking_words", ["wake"]),
])
def test_chat_properties_use_replaced_plugin_config(name, value):
    plugin = _plugin()
    plugin.plugin_cfg = {name: value}
    assert getattr(plugin, name) == value


def _message(session_type="gm", *, mentioned=False, text="hello"):
    return KiraMessageEvent(
        supported_elements=["Text"], timestamp=0,
        adapter=SimpleNamespace(name="test"),
        message=KiraIMMessage(
            message_id="message", self_id="bot", timestamp=0,
            chain=MessageChain([Text(text)]), sender=User("1"),
            group=Group("1") if session_type == "gm" else None,
            is_mentioned=mentioned,
        ),
    )


_SESSION_POLICIES = [
    ("allow_list", ["test:{kind}:1"], True),
    ("allow_list", ["test:{kind}:2"], False),
    ("allow_list", [], False),
    ("deny_list", ["test:{kind}:1"], False),
    ("deny_list", ["test:{kind}:2"], True),
    ("deny_list", [], True),
    ("allow_list", ["other:{kind}:1"], False),
    ("deny_list", ["other:{kind}:1"], True),
]


@pytest.mark.anyio
@pytest.mark.parametrize("session_type", ["gm", "dm"])
@pytest.mark.parametrize("mode,sessions,allowed", _SESSION_POLICIES)
async def test_unmentioned_session_policy_controls_buffering(session_type, mode, sessions, allowed):
    plugin = _plugin()
    plugin.plugin_cfg = {
        "receive_unmentioned": True,
        "receive_unmentioned_access": {
            "permission_mode": mode,
            "session_list": [sid.format(kind=session_type) for sid in sessions],
        },
    }
    plugin.ctx.get_buffer = Mock(return_value=SimpleNamespace(get_length=lambda: 1))
    event = _message(session_type)

    await plugin.handle_msg(event)

    assert event.process_strategy == ("buffer" if allowed else "discard")
    if allowed:
        plugin.ctx.get_buffer.assert_called_once_with(event.session.sid)
    else:
        plugin.ctx.get_buffer.assert_not_called()
    assert plugin.session_tasks == {}


@pytest.mark.anyio
@pytest.mark.parametrize("mode,sessions,allowed", _SESSION_POLICIES)
async def test_proactive_session_policy_keeps_unmentioned_context(monkeypatch, mode, sessions, allowed):
    plugin = _plugin()
    plugin.plugin_cfg = {
        "receive_unmentioned": True,
        "group_proactive_chat": True,
        "group_proactive_chat_probability": 1,
        "group_proactive_chat_access": {
            "permission_mode": mode,
            "session_list": [sid.format(kind="gm") for sid in sessions],
        },
    }
    random = Mock(return_value=0)
    monkeypatch.setattr("core.plugin.builtin_plugins.chat.main.random.random", random)
    event = _message()

    await plugin.handle_msg(event)

    assert event.process_strategy == ("flush" if allowed else "buffer")
    assert random.call_count == int(allowed)


@pytest.mark.anyio
@pytest.mark.parametrize("config,session_type,expected", [
    ({}, "gm", "flush"),
    ({"receive_unmentioned": False}, "gm", "discard"),
    ({"receive_unmentioned_access": {"permission_mode": "allow_list"}}, "gm", "discard"),
    ({"group_proactive_chat": False}, "gm", "buffer"),
    ({}, "dm", "buffer"),
    ({"group_proactive_chat_probability": 0}, "gm", "buffer"),
])
async def test_proactive_chat_requires_enabled_unmentioned_group_and_probability(
    monkeypatch, config, session_type, expected,
):
    plugin = _plugin()
    plugin.plugin_cfg = {
        "receive_unmentioned": True,
        "group_proactive_chat": True,
        "group_proactive_chat_probability": 1,
        **config,
    }
    monkeypatch.setattr("core.plugin.builtin_plugins.chat.main.random.random", lambda: 0.5)
    event = _message(session_type)

    await plugin.handle_msg(event)

    assert event.process_strategy == expected


@pytest.mark.anyio
@pytest.mark.parametrize("mentioned", [True, False])
async def test_session_lists_do_not_block_mentions_or_waking_words(mentioned):
    plugin = _plugin()
    plugin.ctx.config["bot_config"]["bot"]["max_buffer_messages"] = 2
    plugin.plugin_cfg = {
        "waking_words": ["hello"],
        "receive_unmentioned_access": {"permission_mode": "allow_list"},
        "group_proactive_chat_access": {"permission_mode": "allow_list"},
    }
    event = _message(mentioned=mentioned, text="ordinary" if mentioned else "hello")

    await plugin.handle_msg(event)

    assert event.is_mentioned
    assert event.process_strategy == "flush"


@pytest.mark.anyio
@pytest.mark.parametrize("allowed,expected_waits", [(True, 1), (False, 2)])
async def test_debounce_uses_session_unmentioned_permission(monkeypatch, allowed, expected_waits):
    plugin = _plugin()
    sid = "test:gm:1"
    plugin.plugin_cfg = {
        "receive_unmentioned": True,
        "receive_unmentioned_access": {
            "permission_mode": "allow_list",
            "session_list": [sid] if allowed else [],
        },
    }
    trigger = asyncio.Event()
    trigger.set()
    waits = 0

    async def receive_another_mention(_delay):
        nonlocal waits
        waits += 1
        if waits == 1:
            trigger.set()

    flush_waits = []
    plugin.ctx.flush_session_messages.side_effect = lambda _sid: flush_waits.append(waits)
    monkeypatch.setattr("core.plugin.builtin_plugins.chat.main.asyncio.sleep", receive_another_mention)
    task = asyncio.create_task(plugin._debounce_loop(sid, trigger))
    plugin.session_events[sid] = trigger
    plugin.session_tasks[sid] = task

    try:
        await task
        assert flush_waits[0] == expected_waits
        plugin.ctx.flush_session_messages.assert_any_await(sid)
    finally:
        await plugin.terminate()
    assert plugin.session_tasks == {}


@pytest.mark.parametrize("key", ["receive_unmentioned_access", "group_proactive_chat_access"])
@pytest.mark.parametrize("section", [None, [], "invalid", {"permission_mode": "invalid"},
                                    {"session_list": "test:gm:1"}, {"session_list": None}])
def test_malformed_session_policy_is_denied(key, section):
    plugin = _plugin()
    plugin.plugin_cfg = {key: section}
    assert not plugin._session_allowed(key, "test:gm:1")


@pytest.mark.anyio
async def test_session_permissions_follow_replaced_plugin_config():
    plugin = _plugin()
    config = {"receive_unmentioned": True, "group_proactive_chat": True,
              "group_proactive_chat_probability": 1}
    for key, expected in [("receive_unmentioned_access", "discard"),
                          ("group_proactive_chat_access", "buffer")]:
        plugin.plugin_cfg = {**config, key: {"permission_mode": "allow_list"}}
        event = _message()
        await plugin.handle_msg(event)
        assert event.process_strategy == expected

        plugin.plugin_cfg = config.copy()
        event = _message()
        await plugin.handle_msg(event)
        assert event.process_strategy == "flush"


def test_session_policy_schema_preserves_selectors_defaults_and_translations():
    schema_path = Path(__file__).parents[1] / "core/plugin/builtin_plugins/chat/schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    serialized = {field.key: field.to_dict() for field in build_fields(schema)}
    for key in ("receive_unmentioned_access", "group_proactive_chat_access"):
        section = serialized[key]
        mode = section["fields"]["permission_mode"]
        sessions = section["fields"]["session_list"]
        assert mode["options"] == ["allow_list", "deny_list"]
        assert mode["default"] == "deny_list"
        assert sessions["default"] == []
        assert sessions["source"] == "session"
        assert sessions["allow_custom"] is True
        for field in (section, mode, sessions):
            assert field["name"] and field["hint"]
            assert set(field["locales"]["zh"]) == {"name", "hint"}
            assert all(field["locales"]["zh"].values())
