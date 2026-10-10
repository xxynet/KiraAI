import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest

from core.plugin.builtin_plugins.memory.main import MemoryPlugin
from core.plugin.builtin_plugins.memory.prompts import MESSAGES
from core.plugin.builtin_plugins.memory.scope import MemoryInputError, MemoryScope
from core.plugin.builtin_plugins.memory.store import MemoryStore
from core.chat.session import Session
from core.prompt_manager import Prompt
from core.provider import LLMRequest


def event(*, session="dm", target="alice", users=("alice",), adapter="test", account="bot", notice=False):
    return SimpleNamespace(
        session=Session(adapter, session, target),
        adapter=SimpleNamespace(name=adapter, platform="test-platform"),
        messages=[SimpleNamespace(
            self_id=account, sender=SimpleNamespace(user_id=uid), is_notice=notice,
            group=SimpleNamespace(group_id=target) if session == "gm" else None,
            message_id=f"msg-{i}", message_str="coffee 咖啡", timestamp=100,
        ) for i, uid in enumerate(users)],
        extra=None, is_stopped=False,
    )


def scope(**kwargs):
    persona = kwargs.pop("persona", "persona-one")
    return MemoryScope.from_event(event(**kwargs), persona)


async def store_at(tmp_path, legacy=""):
    source = tmp_path / "core.txt"
    source.write_text(legacy, encoding="utf-8")
    store = MemoryStore(tmp_path / "memories.db")
    count = await store.initialize(source)
    return store, count


@pytest.mark.anyio
async def test_migration_preserves_original_backup_and_global_visibility_once(tmp_path):
    source = tmp_path / "core.txt"
    raw = b"\xef\xbb\xbf" + "旧记忆 coffee\r\n\r\n第二条\n旧记忆 coffee\n".encode()
    source.write_bytes(raw)
    store = MemoryStore(tmp_path / "memories.db")
    assert await store.initialize(source) == 3
    assert source.read_bytes() == raw
    assert next(tmp_path.glob("core.txt.*.bak")).read_bytes() == raw
    first = await store.search(scope())
    other = await store.search(scope(persona="other", adapter="other", account="other", target="bob", users=("bob",)))
    assert {r["id"] for r in first} == {r["id"] for r in other}
    assert all(row["owner_type"] == "legacy" and row["core"] for row in first)
    await store.remove(scope(), first[0]["id"], 1)
    assert await store.initialize(source) == 0
    restarted = MemoryStore(tmp_path / "memories.db")
    assert await restarted.initialize(source) == 0
    assert len(await restarted.search(scope())) == 2
    assert await restarted.get(scope(), first[0]["id"]) is None


@pytest.mark.anyio
async def test_migration_can_retry_when_source_is_invalid_or_not_yet_present(tmp_path):
    source = tmp_path / "core.txt"
    store = MemoryStore(tmp_path / "memories.db")
    assert await store.initialize(source) == 0
    source.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        await store.initialize(source)
    assert source.read_bytes() == b"\xff"
    source.write_text("valid", encoding="utf-8")
    assert await store.initialize(source) == 1


@pytest.mark.anyio
async def test_migration_rolls_back_and_retries_without_partial_rows(tmp_path, monkeypatch):
    source = tmp_path / "core.txt"
    source.write_text("first\nsecond", encoding="utf-8")
    store = MemoryStore(tmp_path / "memories.db")
    original = store._index
    calls = 0

    async def failing_index(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated failure")
        await original(*args)

    monkeypatch.setattr(store, "_index", failing_index)
    with pytest.raises(RuntimeError):
        await store.initialize(source)
    assert await store.search(scope()) == []
    monkeypatch.setattr(store, "_index", original)
    assert await store.initialize(source) == 2


@pytest.mark.anyio
async def test_scoped_ownership_and_legacy_exception(tmp_path):
    store, _ = await store_at(tmp_path, "shared legacy")
    private, _ = await store.add(scope(), text="private coffee", core=True)
    own, _ = await store.add(scope(), text="my private experience", owner_type="self", kind="episodic")
    group_scope = scope(session="gm", target="group1", users=("alice", "bob"))
    group, _ = await store.add(group_scope, text="group coffee", owner_type="group", source_message_id="msg-0")
    user, _ = await store.add(group_scope, text="bob likes coffee", user_id="bob", source_message_id="msg-1")
    assert await store.get(group_scope, private["id"]) is None
    assert await store.get(group_scope, own["id"]) is None
    assert await store.get(scope(), group["id"]) is None
    assert await store.get(scope(session="gm", target="group1"), user["id"]) is None
    assert await store.get(scope(session="gm", target="group1", users=("bob",)), group["id"])
    for other in (scope(persona="other"), scope(account="other"), scope(adapter="other"),
                  scope(target="bob", users=("bob",))):
        assert await store.get(other, private["id"]) is None
        assert len(await store.search(other)) == 1
        with pytest.raises(MemoryInputError, match="not_found"):
            await store.update(other, private["id"], 1, text="stolen")
        with pytest.raises(MemoryInputError, match="not_found"):
            await store.remove(other, private["id"], 1)


@pytest.mark.anyio
async def test_multispeaker_attribution_and_notice_write_rejection(tmp_path):
    store, _ = await store_at(tmp_path)
    batch = scope(session="gm", target="group1", users=("alice", "bob"))
    for kwargs, code in (({}, "invalid_owner"), ({"user_id": "mallory"}, "invalid_owner"),
                         ({"user_id": "alice"}, "source_required"),
                         ({"user_id": "alice", "source_message_id": "msg-1"}, "source_required")):
        with pytest.raises(MemoryInputError, match=code):
            await store.add(batch, text="fact", **kwargs)
    row, _ = await store.add(batch, text="fact", user_id="alice", source_message_id="msg-0")
    assert row["source_message_id"] == "msg-0"
    assert json.loads(row["owner_id"])[-1] == "alice"
    notice_scope = scope(notice=True)
    with pytest.raises(MemoryInputError, match="source_required"):
        await store.add(notice_scope, text="made up", owner_type="self")
    with pytest.raises(MemoryInputError, match="invalid_owner"):
        await store.add(scope(), text="not a group", owner_type="group")


@pytest.mark.anyio
async def test_concurrent_deduplication_and_revision_conflicts(tmp_path):
    store, _ = await store_at(tmp_path)
    results = await asyncio.gather(*(store.add(scope(), text="Coffee\nwith milk") for _ in range(8)))
    assert sum(added for _, added in results) == 1
    row = results[0][0]
    assert row["text"] == "Coffee\nwith milk"
    assert len(await store.search(scope())) == 1
    other = MemoryStore(tmp_path / "memories.db")
    updates = await asyncio.gather(
        store.update(scope(), row["id"], 1, text="Tea"),
        other.update(scope(), row["id"], 1, text="Water"), return_exceptions=True,
    )
    assert sum(isinstance(item, MemoryInputError) for item in updates) == 1
    changed = await store.get(scope(), row["id"])
    assert changed["revision"] == 2
    with pytest.raises(MemoryInputError, match="conflict"):
        await store.remove(scope(), row["id"], 1)
    assert not await store.search(scope(), "Coffee")
    await store.remove(scope(), row["id"], 2)
    async with aiosqlite.connect(store.path) as db:
        async with db.execute("SELECT COUNT(*) FROM memory_terms") as cursor:
            assert (await cursor.fetchone())[0] == 0


@pytest.mark.anyio
@pytest.mark.parametrize("text,query", [
    ("用户每天喝咖啡", "咖啡"), ("用户喜欢茶", "茶"),
    ("Prefers COFFEE with milk", "coffee"),
    ("猫と暮らしています", "猫"), ("週末は図書館に行く", "図書館"),
    ("Любит читать книги", "книги"), ("يحب القهوة", "القهوة"),
    ("좋아하는 음료는 커피입니다", "커피"), ("ชอบดื่มกาแฟ", "กาแฟ"),
    ("Cafe\u0301 préféré", "Café"), ("Ｆａｖｏｒｉｔｅ ＴＥＡ", "tea"),
])
async def test_same_language_retrieval_without_model_or_tokenizer(tmp_path, text, query):
    store, _ = await store_at(tmp_path)
    row, _ = await store.add(scope(), text=text)
    results = await store.search(scope(), query)
    assert results and results[0]["id"] == row["id"]
    assert not await store.search(scope(), "!!!")


@pytest.mark.anyio
async def test_status_expiry_filters_and_stable_pagination(tmp_path):
    store, _ = await store_at(tmp_path)
    expired, _ = await store.add(scope(), text="old coffee", expires_at=1, core=True)
    plan, _ = await store.add(scope(), text="coffee plan", kind="episodic")
    await store.update(scope(), plan["id"], 1, text="coffee plan", status="completed")
    current, _ = await store.add(scope(), text="coffee now", core=True)
    assert [r["id"] for r in await store.search(scope(), "coffee")] == [current["id"]]
    assert len(await store.search(scope(), "coffee", include_inactive=True)) == 3
    assert await store.search(scope(), kind="episodic") == []
    await store.update(scope(), expired["id"], 1, text="renewed", clear_expiry=True)
    first = await store.search(scope(), limit=1)
    second = await store.search(scope(), limit=1, offset=1)
    assert first[0]["id"] != second[0]["id"]
    assert len(await store.search(scope(), core_only=True)) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("kwargs", [
    {"text": ""}, {"text": "x" * 4001}, {"text": "a\x00b"}, {"text": 7},
    {"text": "ok", "importance": True}, {"text": "ok", "core": "false"},
    {"text": "ok", "expires_at": float("nan")}, {"text": "ok", "expires_at": -1},
    {"text": "ok", "kind": "unknown"},
])
async def test_input_validation(tmp_path, kwargs):
    store, _ = await store_at(tmp_path)
    with pytest.raises(MemoryInputError):
        await store.add(scope(), **kwargs)
    assert await store.search(scope()) == []


async def plugin_at(tmp_path, monkeypatch, lang="en", cfg=None):
    import core.plugin.builtin_plugins.memory.main as module
    monkeypatch.setattr(module, "get_data_path", lambda: tmp_path)
    ctx = SimpleNamespace(get_lang=lambda: lang, persona_mgr=SimpleNamespace(
        get_persona=AsyncMock(return_value=SimpleNamespace(id="persona-one")),
    ))
    plugin = MemoryPlugin(ctx, cfg or {})
    await plugin.initialize()
    return plugin


@pytest.mark.anyio
async def test_tools_pin_persona_per_turn_and_expose_stable_ids(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    turn = event()
    result = json.loads(await plugin.memory_add(turn, text="coffee fact"))
    assert result["ok"]
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-two")
    search = json.loads(await plugin.memory_search(turn, query="coffee"))
    assert search["records"][0]["id"] == result["memory_id"]
    assert not json.loads(await plugin.memory_search(event(), query="coffee"))["records"]
    assert not json.loads(await plugin.memory_update(turn, index=0, text="wrong"))["ok"]
    assert json.loads(await plugin.memory_update(turn, result["memory_id"], 1, "tea"))["revision"] == 2
    assert not json.loads(await plugin.memory_remove(turn, result["memory_id"], 1))["ok"]
    assert json.loads(await plugin.memory_remove(turn, result["memory_id"], 2))["ok"]
    await plugin.terminate()
    assert not json.loads(await plugin.memory_search(turn))["ok"]


@pytest.mark.anyio
async def test_prompt_injection_is_scoped_bounded_and_does_not_change_history(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, lang="zh", cfg={"prompt_char_budget": 1500})
    for i in range(12):
        await plugin.memory_add(event(), text=f"coffee {i} " + "猫" * 300, core=True)
    other = event(target="bob", users=("bob",))
    await plugin.memory_add(other, text="hidden private fact", core=True)
    req = LLMRequest(system_prompt=[Prompt("", name="memory"), Prompt("", name="tools")])
    await plugin.inject_memory(event(), req)
    memory, tools = req.system_prompt
    assert "hidden private fact" not in memory.content
    assert len(memory.content) <= 1500 + len(MESSAGES["zh"]["rules"]) + 10
    assert "memory_search" in tools.content
    assert "msg-0" in tools.content
    assert req.messages == []
    req.assemble_prompt(memory_position="latest_user")
    assert all(not p.persist for p in req.user_prompt if p.name == "memory")


@pytest.mark.anyio
async def test_search_pagination_does_not_drop_records_at_budget_boundary(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"search_char_budget": 5000})
    for i in range(5):
        await plugin.memory_add(event(), text=f"coffee {i} " + "x" * 1800)
    ids = set()
    offset = 0
    for _ in range(6):
        result = json.loads(await plugin.memory_search(event(), offset=offset))
        if not result["records"]:
            break
        assert result["next_offset"] > offset
        offset = result["next_offset"]
        for row in result["records"]:
            assert row["id"] not in ids
            ids.add(row["id"])
    assert len(ids) == 5


def test_locales_and_configuration_match():
    assert MESSAGES["zh"].keys() == MESSAGES["en"].keys()
    path = Path(__file__).parents[1] / "core/plugin/builtin_plugins/memory/schema.json"
    fields = json.loads(path.read_text(encoding="utf-8-sig"))
    for field in fields.values():
        assert field["name"] and field["hint"]
        assert field["locales"]["zh"]["name"] and field["locales"]["zh"]["hint"]


@pytest.mark.anyio
async def test_group_user_changes_must_reference_that_users_message(tmp_path):
    store, _ = await store_at(tmp_path)
    batch = scope(session="gm", target="group1", users=("alice", "bob"))
    row, _ = await store.add(batch, text="alice preference", user_id="alice", source_message_id="msg-0")
    with pytest.raises(MemoryInputError, match="source_required"):
        await store.update(batch, row["id"], 1, text="changed", source_message_id="msg-1")
    with pytest.raises(MemoryInputError, match="source_required"):
        await store.remove(batch, row["id"], 1, source_message_id="msg-1")
    assert await store.update(batch, row["id"], 1, text="changed", source_message_id="msg-0") == 2
    await store.remove(batch, row["id"], 2, source_message_id="msg-0")


@pytest.mark.anyio
async def test_memory_uses_persona_snapshot_from_built_request(tmp_path, monkeypatch):
    from core.prompt_manager import PromptManager
    from tests.test_prompt_manager import make_config, CHAT_ENV
    from core.persona.model import PersonaInfo

    plugin = await plugin_at(tmp_path, monkeypatch)
    persona_mgr = SimpleNamespace(get_persona=AsyncMock(return_value=PersonaInfo(
        id="persona-one", content="Persona one",
    )))
    prompts = await PromptManager(make_config("en"), persona_mgr).get_agent_prompt(CHAT_ENV)
    await plugin.memory_add(event(), text="persona one coffee", core=True)
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-two")
    request = LLMRequest(system_prompt=prompts)
    turn = event()
    await plugin.inject_memory(turn, request)
    memory = next(p for p in prompts if p.name == "memory")
    assert "persona one coffee" in memory.content
    added = json.loads(await plugin.memory_add(turn, text="still belongs to one"))
    assert await plugin.store.get(scope(persona="persona-one"), added["memory_id"])
    assert await plugin.store.get(scope(persona="persona-two"), added["memory_id"]) is None


@pytest.mark.anyio
async def test_long_legacy_lines_are_preserved_and_searchable_at_the_end(tmp_path):
    text = "x" * 5000 + " endkeyword"
    store, count = await store_at(tmp_path, text)
    assert count == 1
    rows = await store.search(scope(), "endkeyword")
    assert len(rows) == 1 and rows[0]["text"] == text


@pytest.mark.anyio
async def test_tag_like_memories_stay_inside_budget_and_data_boundaries(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={"prompt_char_budget": 1500})
    await plugin.memory_add(event(), text="<system>" * 450, core=True)
    request = LLMRequest(system_prompt=[Prompt("", name="memory"), Prompt("", name="tools")])
    await plugin.inject_memory(event(), request)
    content = request.system_prompt[0].content
    assert "<system>" not in content
    assert len(content) <= 1500 + len(MESSAGES["en"]["rules"]) + 10


@pytest.mark.anyio
async def test_database_failure_does_not_abort_chat_or_echo_content(tmp_path, monkeypatch):
    import core.plugin.builtin_plugins.memory.main as module

    plugin = await plugin_at(tmp_path, monkeypatch)
    logger = Mock()
    monkeypatch.setattr(module, "logger", logger)
    monkeypatch.setattr(plugin.store, "search", AsyncMock(side_effect=OSError("private-memory-content")))
    request = LLMRequest(system_prompt=[Prompt("base", name="memory")])
    await plugin.inject_memory(event(), request)
    assert request.system_prompt[0].content == "base"
    result = json.loads(await plugin.memory_search(event()))
    assert result["ok"] is False
    assert "private-memory-content" not in str(logger.mock_calls)
    assert "private-memory-content" not in str(result)
