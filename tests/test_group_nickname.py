"""Tests for group/server member nickname support across User, adapters, and LLM formatting."""

import importlib
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.chat import Group, KiraIMMessage, MessageChain, User
from core.chat.message_elements import Text
from tests.test_qq_adapter import make_adapter as make_qq_adapter
from tests.test_telegram_discord_adapters import adapter_factory, dc_message


def test_user_group_nickname_defaults_none_and_is_keyword_only():
    user = User("u1", "Alice")
    assert user.nickname == "Alice"
    assert user.group_nickname is None

    with_group = User("u1", "Alice", group_nickname="Dev Alice")
    assert with_group.group_nickname == "Dev Alice"

    with pytest.raises(TypeError):
        User("u1", "Alice", {}, "Dev Alice")


@pytest.mark.asyncio
async def test_qq_group_nickname_per_group_empty_missing_and_private():
    adapter = make_qq_adapter(config={"permission_mode": "deny_list"})
    adapter.bot = AsyncMock()
    adapter.bot.self_nickname = "Kira"
    adapter.bot.get_group_info = AsyncMock(return_value={"data": {"group_name": "G"}})

    def payload(group_id, sender):
        return {
            "message_type": "group" if group_id else "private",
            "group_id": group_id,
            "user_id": 456,
            "self_id": 10000,
            "time": 1700000000,
            "message_id": "m1",
            "sender": sender,
            "message": [{"type": "text", "data": {"text": "hi"}}],
        }

    # Same user with different cards in two groups
    await adapter.im._on_group_message(payload(101, {"nickname": "Alice", "card": "Team Lead"}))
    await adapter.im._on_group_message(payload(202, {"nickname": "Alice", "card": "Gamer Alice"}))
    # Empty, whitespace, and missing card normalize to None
    await adapter.im._on_group_message(payload(101, {"nickname": "Alice", "card": ""}))
    await adapter.im._on_group_message(payload(101, {"nickname": "Alice", "card": "   "}))
    await adapter.im._on_group_message(payload(101, {"nickname": "Alice"}))
    # Private message keeps group_nickname as None
    await adapter.im._on_private_message(payload(None, {"nickname": "Alice", "card": "Ignored"}))

    events = [adapter._event_queue.get_nowait() for _ in range(6)]
    assert [(e.message.sender.nickname, e.message.sender.group_nickname) for e in events] == [
        ("Alice", "Team Lead"),
        ("Alice", "Gamer Alice"),
        ("Alice", None),
        ("Alice", None),
        ("Alice", None),
        ("Alice", None),
    ]


@pytest.mark.asyncio
async def test_discord_server_nickname_per_guild_empty_missing_and_dm(adapter_factory):
    adapter = adapter_factory("Discord", {"permission_mode": "deny_list"})

    # Same user with different server nicknames in two channels/guilds
    await adapter.im._handle_message(dc_message(adapter, True, author=SimpleNamespace(id=123, display_name="Alice", nick="Server One")))
    await adapter.im._handle_message(dc_message(adapter, True, author=SimpleNamespace(id=123, display_name="Alice", nick="Server Two")))
    # Missing or empty nick normalizes to None
    await adapter.im._handle_message(dc_message(adapter, True, author=SimpleNamespace(id=123, display_name="Alice", nick=None)))
    await adapter.im._handle_message(dc_message(adapter, True, author=SimpleNamespace(id=123, display_name="Alice", nick="  ")))
    await adapter.im._handle_message(dc_message(adapter, True, author=SimpleNamespace(id=123, display_name="Alice")))
    # Direct message keeps group_nickname as None
    await adapter.im._handle_message(dc_message(adapter, False, author=SimpleNamespace(id=123, display_name="Alice", nick="Ignored")))

    events = [adapter.ctx.event_queue.get_nowait() for _ in range(6)]
    assert [(e.message.sender.nickname, e.message.sender.group_nickname) for e in events] == [
        ("Alice", "Server One"),
        ("Alice", "Server Two"),
        ("Alice", None),
        ("Alice", None),
        ("Alice", None),
        ("Alice", None),
    ]


def test_format_user_message_includes_group_nickname_only_when_present():
    main = importlib.import_module("core.plugin.builtin_plugins.kira-ai.main")
    plugin = main.DefaultPlugin(SimpleNamespace(get_timezone=lambda: timezone.utc), {})
    ts = int(datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc).timestamp())

    with_card = KiraIMMessage(
        timestamp=ts,
        message_id="1",
        self_id="bot",
        group=Group("g1", "Dev"),
        sender=User("u1", "Alice", group_nickname="Team Lead"),
        chain=MessageChain([Text("hello")]),
    )
    without_card = KiraIMMessage(
        timestamp=ts,
        message_id="2",
        self_id="bot",
        group=Group("g1", "Dev"),
        sender=User("u1", "Alice"),
        chain=MessageChain([Text("hello")]),
    )
    direct = KiraIMMessage(
        timestamp=ts,
        message_id="3",
        self_id="bot",
        sender=User("u1", "Alice", group_nickname="Ignored"),
        chain=MessageChain([Text("hello")]),
    )
    for msg in (with_card, without_card, direct):
        msg.message_str = "hello"

    assert plugin._format_user_message(with_card) == (
        "[Jan 01 2026 12:00 Thu] [message_id: 1] "
        "[group_name: Dev group_id: g1 user_nickname: Alice, group_nickname: Team Lead, user_id: u1] | hello"
    )
    assert plugin._format_user_message(without_card) == (
        "[Jan 01 2026 12:00 Thu] [message_id: 2] "
        "[group_name: Dev group_id: g1 user_nickname: Alice, user_id: u1] | hello"
    )
    assert plugin._format_user_message(direct) == (
        "[Jan 01 2026 12:00 Thu] [message_id: 3] [user_nickname: Alice, user_id: u1] | hello"
    )
