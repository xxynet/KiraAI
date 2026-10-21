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


def event(*, session="dm", target="alice", users=("alice",), adapter="test", account="bot", notice=False,
          platform="test-platform"):
    return SimpleNamespace(
        session=Session(adapter, session, target),
        adapter=SimpleNamespace(name=adapter, platform=platform),
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
    for other in (scope(persona="other"), scope(adapter="other"),
                  scope(target="bob", users=("bob",))):
        assert await store.get(other, private["id"]) is None
        assert await store.get(other, own["id"]) is None
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
        async with db.execute("SELECT COUNT(*) FROM memory_fts") as cursor:
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
        get_persona=AsyncMock(return_value=SimpleNamespace(id="persona-one", name="Kira")),
        list_personas=AsyncMock(return_value=[SimpleNamespace(id="persona-one", name="Kira")]),
    ), adapter_mgr=SimpleNamespace(get_adapter=Mock(return_value=SimpleNamespace(platform="test-platform"))),
        session_mgr=SimpleNamespace(get_sessions=AsyncMock(return_value=[])),
        message_history=SimpleNamespace(list_sessions=AsyncMock(return_value=[]),
                                        get_messages=AsyncMock(return_value=SimpleNamespace(messages=[]))))
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
    def check_fields(items):
        for field in items.values():
            assert field["name"] and field["hint"]
            assert field["locales"]["zh"]["name"] and field["locales"]["zh"]["hint"]
            if field["type"] == "section":
                check_fields(field["fields"])
    check_fields(fields)


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
    monkeypatch.setattr(plugin.store, "_search", AsyncMock(side_effect=OSError("private-memory-content")))
    request = LLMRequest(system_prompt=[Prompt("base", name="memory")])
    await plugin.inject_memory(event(), request)
    assert request.system_prompt[0].content == "base"
    result = json.loads(await plugin.memory_search(event()))
    assert result["ok"] is False
    assert "private-memory-content" not in str(logger.mock_calls)
    assert "private-memory-content" not in str(result)


# ---------------------------------------------------------------------------
# Maintenance page (WebUI)
# ---------------------------------------------------------------------------


def test_maintenance_page_and_api_are_registered():
    from core.plugin import registry

    component = registry._plugin_components["kira_plugin_simple_memory"]
    pages = [(page["route"], page["menu"].label) for page in component.pages]
    # A non-empty sub-path keeps the host's page cleanup able to unmount it.
    assert pages == [("/dashboard", {"zh": "记忆管理", "en": "Memory"})]
    assert {route["path"] for route in component.api_routes} == {
        "/memory/overview", "/memory/records", "/memory/records/{memory_id}",
        "/memory/facets", "/memory/config", "/memory/recall",
        "/memory/recall-options", "/memory/recall-context",
        "/memory/vector/status", "/memory/vector/install", "/memory/vector/rebuild",
    }
    assert all(route["auth"] for route in component.api_routes)


def test_page_assets_are_present_and_reference_each_other():
    root = Path(__file__).parents[1] / "core/plugin/builtin_plugins/memory/web"
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "./theme.css" in html and "./i18n.js" in html
    assert "/plugin-bridge.js" in html
    for name in ("theme.css", "i18n.js", "custom-select.css", "custom-select.js"):
        assert f"./{name}" in html
        assert (root / name).stat().st_size > 0


def test_page_strings_cover_both_locales():
    import re

    root = Path(__file__).parents[1] / "core/plugin/builtin_plugins/memory/web"
    script = (root / "i18n.js").read_text(encoding="utf-8")
    blocks = {}
    for locale in ("zh", "en"):
        start = script.index("    %s: {" % locale)
        end = script.index("\n    },", start)
        blocks[locale] = dict(re.findall(r"'([\w.]+)': '((?:[^'\\]|\\.)*)'", script[start:end]))
    assert blocks["zh"].keys() == blocks["en"].keys()
    assert blocks["zh"]["app.title"] != blocks["en"]["app.title"]


def test_page_references_only_defined_keys():
    import re

    root = Path(__file__).parents[1] / "core/plugin/builtin_plugins/memory/web"
    script = (root / "i18n.js").read_text(encoding="utf-8")
    known = set(re.findall(r"'([\w.]+)': '", script))
    # Machine-value keys are built at runtime as "<group>.<value>".
    known |= {"kind." + k for k in ("semantic", "episodic", "procedural")}
    known |= {"status." + k for k in ("active", "completed", "cancelled", "superseded")}
    known |= {"owner." + k for k in ("user", "group", "self", "legacy")}
    known |= {"origin." + k for k in ("conversation", "legacy")}
    html = (root / "index.html").read_text(encoding="utf-8")
    # I18N.value("kind", value) takes a group name, not a key; the concrete
    # "<group>.<value>" keys it resolves to are listed above.
    groups = {"kind", "status", "owner", "origin"}
    used = set(re.findall(r'I18N\.(?:t|value)\(\s*"([\w.]+)"', html)) - groups
    assert used <= known, used - known


@pytest.mark.anyio
async def test_admin_listing_filters_and_paginates(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    for i in range(5):
        await plugin.memory_add(event(), text=f"coffee note {i}", core=(i == 0))
    await plugin.memory_add(event(target="bob", users=("bob",)), text="zebra stripes", importance=5)

    page = await plugin.store.admin_list(size=2, page=1)
    assert page["total"] == 6 and len(page["items"]) == 2
    second = await plugin.store.admin_list(size=2, page=3)
    assert len(second["items"]) == 2 and not {r["id"] for r in page["items"]} & {r["id"] for r in second["items"]}

    assert (await plugin.store.admin_list(core=True))["total"] == 1
    assert (await plugin.store.admin_list(kind="semantic"))["total"] == 6
    assert (await plugin.store.admin_list(status="completed"))["total"] == 0
    assert (await plugin.store.admin_list(query="coffee"))["total"] == 5
    # A content query and an attribute filter combine (AND), not replace each other.
    # "zebra" shares no word or character gram with "coffee note", so it really
    # discriminates the way a user expects from a filtered search.
    assert (await plugin.store.admin_list(query="coffee", core=True))["total"] == 1
    assert (await plugin.store.admin_list(query="zebra"))["total"] == 1
    assert (await plugin.store.admin_list(query="zebra", owner_type="group"))["total"] == 0
    assert (await plugin.store.admin_list(query="zzzqqq"))["total"] == 0


@pytest.mark.anyio
async def test_admin_listing_rejects_bad_input(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    from core.plugin.builtin_plugins.memory import webui

    for kwargs in ({"size": 0}, {"size": 101}, {"page": 0}, {"page": True}):
        with pytest.raises(MemoryInputError):
            await plugin.store.admin_list(**kwargs)
    with pytest.raises(MemoryInputError):
        await plugin.store.admin_list(kind="nonsense")
    with pytest.raises(MemoryInputError):
        await plugin.store.admin_list(status="nonsense")
    with pytest.raises(MemoryInputError):
        await plugin.store.admin_list(origin="nonsense")
    with pytest.raises(MemoryInputError):
        await plugin.store.admin_list(core="yes")
    with pytest.raises(MemoryInputError):
        webui.parse_filters({"kind": "nonsense"})
    with pytest.raises(MemoryInputError):
        webui.parse_page("abc", 1, 1, 100)
    assert webui.parse_page(None, 20, 1, 100) == 20
    assert webui.parse_page("9999", 20, 1, 100) == 100


@pytest.mark.anyio
async def test_admin_detail_and_facets(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    added = json.loads(await plugin.memory_add(event(), text="likes coffee", core=True))
    record = await plugin.store.admin_get(added["memory_id"])
    assert record["text"] == "likes coffee" and record["terms"] > 0
    assert await plugin.store.admin_get("missing") is None

    from core.plugin.builtin_plugins.memory import webui

    payload = webui.serialize(record)
    # Internal search artefacts never leave the server.
    assert "normalized" not in payload and "term_count" not in payload
    assert payload["core"] is True and payload["owner_type"] == "user"
    assert payload["subject"] == "alice" and payload["adapter"] == "test"

    facets = await plugin.store.facets()
    assert facets["personas"] == ["persona-one"]
    assert facets["sessions"] == ["test:dm:alice"]


@pytest.mark.anyio
async def test_overview_counts(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="core fact", core=True)
    await plugin.memory_add(event(), text="plain fact")
    row = json.loads(await plugin.memory_add(event(), text="removable fact"))
    # Removal is physical, so the totals drop rather than gaining a "deleted" bucket.
    await plugin.memory_remove(event(), row["memory_id"], row["revision"])

    data = await plugin.store.overview()
    assert data["total"] == 2 and data["active"] == 2 and data["core"] == 1
    assert data["statuses"] == {"active": 2}
    assert data["kinds"] == {"semantic": 2}
    assert data["owners"] == {"user": 2}
    assert data["origins"] == {"conversation": 2}
    assert data["last_updated"] is not None

    from core.plugin.builtin_plugins.memory import webui

    payload = webui.overview_payload(data, max_core=10, max_recall=6)
    assert payload["limits"] == {"core": 10, "recall": 6}


@pytest.mark.anyio
async def test_admin_search_paginates_before_loading_results(tmp_path, monkeypatch):
    store, _ = await store_at(tmp_path)
    for index in range(24):
        await store.add(
            scope(), text=f"coffee preference {index}", importance=index % 5 + 1,
            core=index % 2 == 0, kind="episodic" if index % 3 == 0 else "semantic",
            expires_at=1 if index % 4 == 0 else None,
        )
    await store.add(
        scope(session="gm", target="group"), text="coffee group rule",
        owner_type="group", core=True,
    )
    await store.add(scope(), text="tea only", core=True)
    expected = await store.search(
        scope(), "coffee", kind="semantic", core_only=True, include_inactive=True, limit=50,
    )
    assert len(expected) == 8

    batch_sizes = []
    original_fetchall = aiosqlite.Cursor.fetchall

    async def tracked_fetchall(cursor):
        batch = await original_fetchall(cursor)
        batch_sizes.append(len(batch))
        return batch

    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", tracked_fetchall)
    records = []
    for page in range(1, 5):
        result = await store.admin_list(
            query="coffee", kind="semantic", owner_type="user", origin="conversation",
            core=True, page=page, size=3,
        )
        assert result["total"] == len(expected)
        assert result["page"] == page and result["size"] == 3
        records.extend(result["items"])
    assert [row["id"] for row in records] == [row["id"] for row in expected]
    assert [row["score"] for row in records] == pytest.approx([row["score"] for row in expected])
    assert batch_sizes and max(batch_sizes) <= 3


@pytest.mark.anyio
async def test_memory_records_api_returns_bad_request_for_invalid_parameters(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="coffee fact")
    plugin_id = "kira_plugin_simple_memory"
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin,
        is_plugin_enabled=lambda _: True,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    path = f"/api/plugin/{plugin_id}/memory/records"
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        app.dependency_overrides[require_auth] = lambda: {"sub": "test-user"}
        response = await client.get(path, params={"q": "coffee", "page": "1", "size": "1"})
        assert response.status_code == 200
        assert response.json()["total"] == 1 and len(response.json()["items"]) == 1
        for params, code in (
            ({"kind": "nonsense"}, "invalid_category"),
            ({"status": "nonsense"}, "invalid_category"),
            ({"owner_type": "nonsense"}, "invalid_category"),
            ({"origin": "nonsense"}, "invalid_category"),
            ({"core": "yes"}, "invalid_priority"),
            ({"page": "abc"}, "invalid_limit"),
            ({"size": "abc"}, "invalid_limit"),
        ):
            response = await client.get(path, params=params)
            assert response.status_code == 400, (params, response.text)
            assert response.json() == {"detail": code}
        plugin._ready = False
        assert (await client.get(path)).status_code == 503


@pytest.mark.anyio
async def test_overview_active_counts_match_recall_expiry(tmp_path, monkeypatch):
    import core.plugin.builtin_plugins.memory.store as module

    monkeypatch.setattr(module, "time", SimpleNamespace(time=lambda: 1000.0))
    store, _ = await store_at(tmp_path)
    for index, expiry in enumerate((None, 999, 1000, 1001)):
        await store.add(scope(), text=f"active fact {index}", core=True, expires_at=expiry)
    for status in ("completed", "cancelled", "superseded"):
        row, _ = await store.add(scope(), text=f"{status} fact", core=True, expires_at=1001)
        await store.update(scope(), row["id"], 1, text=row["text"], status=status)

    data = await store.overview()
    assert data["total"] == 7
    assert data["active"] == len(await store.search(scope())) == 2
    assert data["inactive"] == 5
    assert data["core"] == len(await store.search(scope(), core_only=True)) == 2
    assert data["expiring"] == 1
    assert data["statuses"] == {"active": 4, "completed": 1, "cancelled": 1, "superseded": 1}

@pytest.mark.anyio
async def test_recall_preview_matches_chat_payload_without_writes(tmp_path, monkeypatch):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "core.txt").write_text("legacy coffee", encoding="utf-8")
    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="daily routine", core=True)
    added = json.loads(await plugin.memory_add(event(), text="likes coffee"))
    await plugin.memory_add(event(), text="expired coffee", expires_at=1)
    await plugin.memory_add(event(target="bob", users=("bob",)), text="bob coffee")
    other_account = json.loads(await plugin.memory_add(event(account="other-bot"), text="other account coffee"))
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-two")
    await plugin.memory_add(event(), text="other persona coffee")
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-one")
    current = scope()
    payload = {"persona_id": current.persona_id, "adapter": current.adapter,
               "session_id": current.session_id, "messages": ["coffee 咖啡"]}
    before = plugin.store.path.read_bytes()
    result = await plugin.api_recall(payload)
    assert {row["text"] for row in result["core"]} == {"daily routine", "legacy coffee"}
    assert {row["id"] for row in result["recalled"]} == {added["memory_id"], other_account["memory_id"]}
    assert len({row["id"] for row in result["core"] + result["recalled"]}) == 4
    request = LLMRequest(system_prompt=[Prompt("base", name="memory", persona_id="persona-one")])
    await plugin.inject_memory(event(), request)
    assert json.loads(request.system_prompt[0].content.rsplit("\n", 1)[1]) == result["core"] + result["recalled"]
    legacy_only = await plugin.api_recall(payload | {"persona_id": "new-persona"})
    assert [row["text"] for row in legacy_only["core"]] == ["legacy coffee"]
    assert legacy_only["recalled"] == []
    assert plugin.store.path.read_bytes() == before
    assert (memory_dir / "core.txt").read_text(encoding="utf-8") == "legacy coffee"


@pytest.mark.anyio
async def test_recall_preview_group_speaker_visibility(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    turn = event(session="gm", target="group-one", users=("alice", "bob"))
    for user, source in (("alice", "msg-0"), ("bob", "msg-1")):
        result = json.loads(await plugin.memory_add(
            turn, text=f"{user} coffee", user_id=user, source_message_id=source,
        ))
        assert result["ok"]
    for owner in ("group", "self"):
        result = json.loads(await plugin.memory_add(
            turn, text=f"{owner} coffee", owner_type=owner, source_message_id="msg-0",
        ))
        assert result["ok"]
    context = scope(session="gm", target="group-one", users=("alice", "bob"))
    payload = {"persona_id": context.persona_id, "adapter": context.adapter,
               "session_id": context.session_id, "messages": ["coffee"]}
    for users, expected in (([], {"group coffee", "self coffee"}),
                            (["alice"], {"group coffee", "self coffee", "alice coffee"}),
                            (["alice", "bob"], {"group coffee", "self coffee", "alice coffee", "bob coffee"})):
        result = await plugin.api_recall(payload | {"user_ids": users})
        assert {row["text"] for row in result["recalled"]} == expected
    result = await plugin.api_recall(payload | {"persona_id": "other-persona", "user_ids": ["alice"]})
    assert result["core"] == result["recalled"] == []


@pytest.mark.anyio
async def test_recall_preview_query_and_budget_match_runtime(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={
        "core_limit": 1, "recall_limit": 1, "prompt_char_budget": 1500,
    })
    await plugin.memory_add(event(), text="x" * 3000, core=True)
    await plugin.memory_add(event(), text="coffee" * 500)
    context = scope()
    payload = {"persona_id": context.persona_id, "adapter": context.adapter,
               "session_id": context.session_id,
               "messages": ["a" * 200, "coffee " + "b" * 200, "c" * 200]}
    result = await plugin.api_recall(payload)
    assert result["query"] == " ".join(payload["messages"])
    assert len(result["core"]) == len(result["recalled"]) == 1
    assert all(row["truncated"] for row in result["core"] + result["recalled"])
    assert result["prompt_chars"] == len(plugin.encode(result["core"] + result["recalled"])) <= 1500
    assert result["limits"] == {"core": 1, "recall": 1, "prompt_chars": 1500}
    empty = await plugin.api_recall(payload | {"messages": []})
    assert empty["query"] == "" and empty["recalled"] == [] and len(empty["core"]) == 1


@pytest.mark.anyio
async def test_recall_api_auth_validation_and_contexts(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="coffee fact")
    await plugin.memory_add(event(), text="another fact")
    await plugin.memory_add(event(account="second-bot"), text="second account fact")
    plugin_id = "kira_plugin_simple_memory"
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin, is_plugin_enabled=lambda _: True,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    path = f"/api/plugin/{plugin_id}/memory/recall"
    context = scope()
    payload = {"persona_id": context.persona_id, "adapter": context.adapter,
               "session_id": context.session_id, "messages": ["coffee"]}
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        assert (await client.post(path, json=payload)).status_code == 401
        assert (await client.post(path, json={"messages": ["coffee"]})).status_code == 401
        assert (await client.get(f"/api/plugin/{plugin_id}/memory/recall-options")).status_code == 401
        assert (await client.get(f"/api/plugin/{plugin_id}/memory/recall-context",
                                 params={"session_id": context.session_id})).status_code == 401
        app.dependency_overrides[require_auth] = lambda: {"sub": "operator"}
        response = await client.post(path, json=payload)
        assert response.status_code == 200
        assert {row["text"] for row in response.json()["recalled"]} == {"coffee fact", "second account fact"}
        broad = await client.post(path, json={"messages": ["fact"]})
        assert broad.status_code == 200
        assert len(broad.json()["recalled"]) == 3
        for invalid in (
            {"persona_id": ""}, {"adapter": None}, {"adapter": []},
            {"adapter": ""}, {"adapter": "wrong"}, {"adapter": "test:dm"},
            {"session_id": "wrong:dm:alice"},
            {"session_id": "test:other:alice"}, {"user_ids": "alice"},
            {"user_ids": ["bob"]}, {"user_ids": [None]}, {"messages": "coffee"},
            {"messages": ["coffee"] * 4},
        ):
            response = await client.post(path, json=payload | invalid)
            assert response.status_code == 400, (invalid, response.text)
            assert response.json() == {"detail": "invalid_recall"}
        response = await client.get(f"/api/plugin/{plugin_id}/memory/facets")
        contexts = response.json()["contexts"]
        assert len(contexts) == 1
        assert {row["session_id"] for row in contexts} == {scope().session_id}
        plugin._ready = False
        assert (await client.post(path, json=payload)).status_code == 503

@pytest.mark.anyio
async def test_recall_options_include_real_sessions_and_named_personas(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    plugin.ctx.persona_mgr.list_personas.return_value.append(SimpleNamespace(id="persona-two", name="Other"))
    plugin.ctx.session_mgr.get_sessions.return_value = [
        Session("test", "dm", "alice", session_title="Alice"),
        Session("test", "unsupported", "skip"),
    ]
    plugin.ctx.message_history.list_sessions.return_value = [
        SimpleNamespace(session_id="test:gm:group"), SimpleNamespace(session_id="test:dm:alice"),
    ]
    result = await plugin.api_recall_options()
    assert result["personas"] == [{"id": "persona-one", "name": "Kira"}, {"id": "persona-two", "name": "Other"}]
    assert result["active_persona"] == "persona-one"
    assert result["sessions"] == [{"id": "test:dm:alice", "name": "Alice"},
                                   {"id": "test:gm:group", "name": "test:gm:group"}]
    plugin.ctx.session_mgr.get_sessions.assert_awaited_once_with(include_content=False)


@pytest.mark.anyio
async def test_recall_context_includes_speakers_across_bot_accounts(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    def message(user, name, account="bot", notice=False):
        return SimpleNamespace(self_id=account, platform="test-platform", sender_id=user,
                               sender_name=name, is_notice=notice)
    plugin.ctx.message_history.get_messages.return_value.messages = [
        message("ignored", "Notice", notice=True), message("alice", "Alice"),
        message("bob", "Bob"), message("wrong", "Old account", account="old-bot"),
    ]
    before = plugin.store.path.read_bytes()
    result = await plugin.api_recall_context("test:gm:group")
    assert result["adapter"] == "test"
    assert result["speakers"] == [{"id": "alice", "name": "Alice"}, {"id": "bob", "name": "Bob"},
                                  {"id": "wrong", "name": "Old account"}]
    assert result["default_user_ids"] == ["alice"] and result["group"] is True
    plugin.ctx.message_history.get_messages.assert_awaited_once_with(
        session_id="test:gm:group", direction="incoming", limit=50,
    )
    dm = await plugin.api_recall_context("test:dm:alice")
    assert dm["speakers"] == [] and dm["default_user_ids"] == ["alice"] and dm["group"] is False
    assert plugin.store.path.read_bytes() == before


@pytest.mark.anyio
async def test_recall_context_uses_stored_speakers_when_history_is_empty(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="coffee")
    result = await plugin.api_recall_context("test:dm:alice")
    assert result["adapter"] == scope().adapter
    assert result["default_user_ids"] == ["alice"]
    group = event(session="gm", target="group", users=("alice", "bob"))
    await plugin.memory_add(group, text="alice tea", user_id="alice", source_message_id="msg-0")
    await plugin.memory_add(group, text="bob coffee", user_id="bob", source_message_id="msg-1")
    result = await plugin.api_recall_context("test:gm:group")
    assert {item["id"] for item in result["speakers"]} == {"alice", "bob"}
    assert result["default_user_ids"] == [result["speakers"][0]["id"]]


@pytest.mark.anyio
async def test_recall_context_without_history_needs_no_platform_or_adapter_lookup(tmp_path, monkeypatch):
    from fastapi import HTTPException

    plugin = await plugin_at(tmp_path, monkeypatch)
    result = await plugin.api_recall_context("test:dm:alice")
    assert result["adapter"] == scope().adapter
    assert result["default_user_ids"] == ["alice"]
    plugin.ctx.adapter_mgr.get_adapter.assert_not_called()
    group = await plugin.api_recall_context("test:gm:no-history")
    assert group["adapter"] == scope().adapter and group["speakers"] == []
    with pytest.raises(HTTPException) as invalid:
        await plugin.api_recall_context("malformed-session")
    assert invalid.value.status_code == 400 and invalid.value.detail == "invalid_recall"


@pytest.mark.anyio
async def test_operator_recall_needs_no_account_or_message_history(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="alice coffee")
    await plugin.memory_add(event(account="other-bot"), text="other bot coffee")
    await plugin.memory_add(event(target="bob", users=("bob",)), text="bob coffee")
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-two")
    await plugin.memory_add(event(), text="other persona coffee")
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-one")
    await plugin.memory_add(event(), text="expired coffee", expires_at=1)
    done = json.loads(await plugin.memory_add(event(), text="completed coffee"))
    await plugin.memory_update(event(), done["memory_id"], done["revision"],
                               text="completed coffee", status="completed")
    before = plugin.store.path.read_bytes()
    result = await plugin.api_recall({"messages": ["coffee"]})
    assert {row["text"] for row in result["recalled"]} == {
        "alice coffee", "other bot coffee", "bob coffee", "other persona coffee",
    }
    plugin.ctx.message_history.get_messages.assert_not_awaited()
    assert plugin.store.path.read_bytes() == before
    # Runtime tools still enforce persona, session and speaker isolation.
    assert {row["text"] for row in await plugin.store.search(scope(), "coffee")} == {"alice coffee", "other bot coffee"}


@pytest.mark.anyio
async def test_operator_recall_optional_filters_and_legacy_visibility(tmp_path, monkeypatch):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "core.txt").write_text("legacy coffee", encoding="utf-8")
    plugin = await plugin_at(tmp_path, monkeypatch)
    await plugin.memory_add(event(), text="alice coffee")
    await plugin.memory_add(event(account="other-bot"), text="other bot coffee")
    await plugin.memory_add(event(target="bob", users=("bob",)), text="bob coffee")
    plugin.ctx.persona_mgr.get_persona.return_value = SimpleNamespace(id="persona-two")
    await plugin.memory_add(event(), text="other persona coffee")
    before = plugin.store.path.read_bytes()
    cases = [
        ({}, {"alice coffee", "other bot coffee", "bob coffee", "other persona coffee"}),
        ({"persona_id": "persona-one"}, {"alice coffee", "other bot coffee", "bob coffee"}),
        ({"session_id": "test:dm:alice"}, {"alice coffee", "other bot coffee", "other persona coffee"}),
        ({"persona_id": "persona-one", "session_id": "test:dm:alice"}, {"alice coffee", "other bot coffee"}),
        ({"persona_id": "missing"}, set()),
        ({"session_id": "test:dm:no-history"}, set()),
        ({"persona_id": "", "session_id": None}, {"alice coffee", "other bot coffee", "bob coffee", "other persona coffee"}),
    ]
    for filters, expected in cases:
        result = await plugin.api_recall({"messages": ["coffee"]} | filters)
        assert {row["text"] for row in result["recalled"]} == expected
        assert [row["text"] for row in result["core"]] == ["legacy coffee"]
    assert plugin.store.path.read_bytes() == before


@pytest.mark.anyio
async def test_operator_recall_group_includes_all_speakers(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    turn = event(session="gm", target="group", users=("alice", "bob"))
    for user, mid in (("alice", "msg-0"), ("bob", "msg-1")):
        await plugin.memory_add(turn, text=f"{user} coffee", user_id=user, source_message_id=mid)
    result = await plugin.api_recall({"session_id": "test:gm:group", "messages": ["coffee"]})
    assert {row["text"] for row in result["recalled"]} == {"alice coffee", "bob coffee"}


@pytest.mark.anyio
async def test_operator_recall_uses_shared_query_and_budget(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={
        "core_limit": 1, "recall_limit": 1, "prompt_char_budget": 1500,
    })
    await plugin.memory_add(event(), text="x" * 3000, core=True)
    await plugin.memory_add(event(), text="coffee" * 500)
    messages = ["a" * 200, "coffee " + "b" * 200, "c" * 200]
    broad = await plugin.api_recall({"messages": messages})
    scoped = await plugin.recall(scope(), messages)
    assert broad == scoped
    assert broad["prompt_chars"] <= 1500
    empty = await plugin.api_recall({})
    assert empty["query"] == "" and empty["recalled"] == []
    assert len(empty["core"]) == 1


@pytest.mark.anyio
async def test_operator_recall_rejects_invalid_optional_filters(tmp_path, monkeypatch):
    from fastapi import HTTPException

    plugin = await plugin_at(tmp_path, monkeypatch)
    for payload in (
        {"persona_id": 0}, {"persona_id": " "}, {"persona_id": "x" * 513},
        {"session_id": []}, {"session_id": "broken"}, {"session_id": "test:other:user"},
        {"session_id": "test:dm:"}, {"messages": "coffee"}, {"messages": [None]},
        {"messages": ["coffee"] * 4}, {"user_ids": ["alice"]},
    ):
        with pytest.raises(HTTPException) as error:
            await plugin.api_recall(payload)
        assert error.value.status_code == 400 and error.value.detail == "invalid_recall"


@pytest.mark.anyio
@pytest.mark.parametrize("owner_type,session", [("user", "dm"), ("user", "gm"), ("group", "gm"), ("self", "dm"), ("self", "gm")])
async def test_transport_metadata_changes_preserve_memory_crud_and_deduplication(tmp_path, owner_type, session):
    store, _ = await store_at(tmp_path)
    options = {"session": session, "target": "group" if session == "gm" else "alice"}
    original = scope(account="old-bot", **options)
    changed = scope(account="new-bot", platform="renamed-platform", **options)
    missing = scope(account=None, platform=None, **options)
    assert original.adapter == changed.adapter == missing.adapter == "test"
    assert original.owner(owner_type) == changed.owner(owner_type) == missing.owner(owner_type)
    if owner_type != "self":
        assert json.loads(original.owner(owner_type)) == ["test", "group" if owner_type == "group" else "alice"]
    row, added = await store.add(original, text="coffee preference", owner_type=owner_type)
    assert added
    duplicate, added = await store.add(changed, text="coffee preference", owner_type=owner_type)
    assert not added and duplicate["id"] == row["id"]
    assert [item["id"] for item in await store.search(missing, "coffee")] == [row["id"]]
    assert await store.update(changed, row["id"], 1, text="tea preference") == 2
    assert (await store.get(missing, row["id"]))["text"] == "tea preference"
    await store.remove(missing, row["id"], 2)
    assert await store.get(original, row["id"]) is None


def test_scope_needs_no_platform_or_bot_account_fields():
    turn = event(session="gm", target="group", users=("alice", "bob"))
    del turn.messages[0].self_id
    turn.messages[1].self_id = "another-bot"
    del turn.adapter.platform
    current = MemoryScope.from_event(turn, "persona-one")
    assert current.adapter == "test"
    assert current.users == ("alice", "bob")
    assert current.sources == (("msg-0", "alice"), ("msg-1", "bob"))


@pytest.mark.anyio
async def test_owner_serialization_and_speaker_lookup_use_adapter_keys(tmp_path, monkeypatch):
    from core.plugin.builtin_plugins.memory import webui

    plugin = await plugin_at(tmp_path, monkeypatch)
    added = json.loads(await plugin.memory_add(event(), text="coffee"))
    payload = webui.serialize(await plugin.store.admin_get(added["memory_id"]))
    assert "namespace" not in payload
    assert json.loads(payload["owner_id"]) == ["test", "alice"]
    assert payload["subject"] == "alice" and payload["adapter"] == "test"
    assert "account" not in payload and "platform" not in payload
    assert await plugin.store.recall_users("test:dm:alice") == ["alice"]


@pytest.mark.anyio
async def test_operator_update_preserves_scope_and_source_and_reindexes(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    context = scope(persona="other", adapter="other", target="bob", users=("bob",))
    row, _ = await plugin.store.add(context, text="coffee", expires_at=2000000000)
    original = await plugin.store.admin_get(row["id"])
    changed = await plugin.api_record_update(row["id"], {
        "revision": 1, "text": "  Jasmine tea  ", "kind": "episodic",
        "status": "completed", "importance": 5, "core": True, "expires_at": None,
    })
    assert changed["revision"] == 2 and changed["text"] == "Jasmine tea"
    assert changed["kind"] == "episodic" and changed["status"] == "completed"
    assert changed["importance"] == 5 and changed["core"] is True
    assert changed["expires_at"] is None and changed["terms"] > 0
    for key in ("id", "owner_type", "owner_id", "persona_id", "session_id",
                "source_message_id", "created_at", "origin"):
        assert changed[key] == original[key], key
    assert not await plugin.store.search(context, "coffee", include_inactive=True)
    assert (await plugin.store.search(context, "jasmine", include_inactive=True))[0]["id"] == row["id"]
    assert not await plugin.store.search(context, "jasmine")
    assert not await plugin.store.search(scope(), "jasmine", include_inactive=True)
    await plugin.api_record_update(row["id"], {"revision": 2, "text": "Jasmine tea",
                                              "status": "active", "expires_at": 2100000000})
    assert (await plugin.store.search(context, "jasmine"))[0]["expires_at"] == 2100000000
    # Conversation writes must still require a real incoming source.
    with pytest.raises(MemoryInputError, match="source_required"):
        await plugin.store.update(
            MemoryScope(context.persona_id, context.session_id, context.adapter, context.users,
                        context.group_id, ()),
            row["id"], 3, text="forged",
        )


@pytest.mark.anyio
async def test_operator_update_legacy_and_concurrent_edits(tmp_path, monkeypatch):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory" / "core.txt").write_text("legacy coffee", encoding="utf-8")
    plugin = await plugin_at(tmp_path, monkeypatch)
    legacy = (await plugin.store.admin_list())["items"][0]
    changed = await plugin.api_record_update(legacy["id"], {"revision": 1, "text": "legacy tea"})
    assert changed["origin"] == "legacy" and changed["owner_id"] == "shared"
    assert changed["source_message_id"] is None
    assert (await plugin.store.search(scope(), "tea"))[0]["id"] == legacy["id"]
    row, _ = await plugin.store.add(scope(), text="original")
    results = await asyncio.gather(
        plugin.store.admin_update(row["id"], 1, text="operator tea"),
        plugin.store.update(scope(), row["id"], 1, text="conversation water"),
        return_exceptions=True,
    )
    assert sum(isinstance(result, MemoryInputError) for result in results) == 1
    assert str(next(result for result in results if isinstance(result, MemoryInputError))) == "conflict"
    assert (await plugin.store.admin_get(row["id"]))["revision"] == 2


@pytest.mark.anyio
async def test_memory_update_api_auth_validation_and_conflict(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch)
    row, _ = await plugin.store.add(scope(), text="original coffee")
    plugin_id = "kira_plugin_simple_memory"
    enabled = True
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin, is_plugin_enabled=lambda _: enabled,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    path = f"/api/plugin/{plugin_id}/memory/records/{row['id']}"
    payload = {"revision": 1, "text": "updated tea"}
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        assert (await client.post(path, json=payload)).status_code == 401
        app.dependency_overrides[require_auth] = lambda: {"sub": "operator"}
        for invalid, code in (
            ({"revision": True}, "invalid_revision"), ({"revision": 0}, "invalid_revision"),
            ({"revision": "1"}, "invalid_revision"), ({"text": ""}, "invalid_text"),
            ({"text": "x" * 4001}, "invalid_text"), ({"text": "\x00"}, "invalid_text"),
            ({"text": None}, "invalid_text"), ({"kind": []}, "invalid_category"),
            ({"kind": None}, "invalid_category"), ({"status": "bad"}, "invalid_category"),
            ({"core": 1}, "invalid_priority"), ({"importance": True}, "invalid_priority"),
            ({"importance": 6}, "invalid_priority"), ({"expires_at": -1}, "invalid_expiry"),
            ({"expires_at": "tomorrow"}, "invalid_expiry"),
            ({"owner_id": "other"}, "invalid_update"), ({"persona_id": "other"}, "invalid_update"),
            ({"adapter": "other"}, "invalid_update"), ({"session_id": "other"}, "invalid_update"),
            ({"source_message_id": "forged"}, "invalid_update"),
            ({"origin": "legacy"}, "invalid_update"),
        ):
            response = await client.post(path, json=payload | invalid)
            assert response.status_code == 400, (invalid, response.text)
            assert response.json() == {"detail": code}
            assert (await plugin.store.admin_get(row["id"]))["revision"] == 1
        assert (await client.post(path, json={"revision": 1})).json() == {"detail": "invalid_text"}
        response = await client.post(path, json=payload)
        assert response.status_code == 200 and response.json()["revision"] == 2
        assert (await client.post(path, json=payload)).json() == {"detail": "conflict"}
        assert (await plugin.store.admin_get(row["id"]))["text"] == "updated tea"
        assert not await plugin.store.search(scope(), "coffee")
        assert (await plugin.store.search(scope(), "tea"))[0]["id"] == row["id"]
        missing = await client.post(path.rsplit("/", 1)[0] + "/missing", json=payload)
        assert missing.status_code == 400 and missing.json() == {"detail": "not_found"}
        plugin._ready = False
        assert (await client.post(path, json=payload)).status_code == 503
        enabled = False
        assert (await client.post(path, json=payload)).status_code == 404


@pytest.mark.anyio
async def test_memory_delete_api_auth_revision_and_keyword_cleanup(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from core.plugin import registry
    from webui.plugin_bindings import PluginWebBindings
    from webui.routes.auth import require_auth

    plugin = await plugin_at(tmp_path, monkeypatch)
    row, _ = await plugin.store.add(scope(), text="coffee to delete")
    kept, _ = await plugin.store.add(scope(), text="tea to keep")
    await plugin.store.admin_update(row["id"], 1, text="updated coffee")
    changed = Mock()
    monkeypatch.setattr(plugin.vectors, "changed", changed)
    plugin_id = "kira_plugin_simple_memory"
    enabled = True
    manager = SimpleNamespace(
        get_plugin_components=lambda: {plugin_id: registry._plugin_components[plugin_id]},
        get_plugin_inst=lambda _: plugin, is_plugin_enabled=lambda _: enabled,
    )
    app = FastAPI()
    PluginWebBindings(manager, app).register_apis(plugin_id)
    path = f"/api/plugin/{plugin_id}/memory/records/{row['id']}"
    async with AsyncClient(transport=ASGITransport(app=app, raise_app_exceptions=False),
                           base_url="http://test") as client:
        assert (await client.delete(path, params={"revision": 2})).status_code == 401
        app.dependency_overrides[require_auth] = lambda: {"sub": "operator"}
        assert (await client.delete(path)).status_code == 422
        assert (await client.delete(path, params={"revision": "invalid"})).status_code == 422
        for revision, code in ((0, "invalid_revision"), (-1, "invalid_revision"), (1, "conflict")):
            response = await client.delete(path, params={"revision": revision})
            assert response.status_code == 400 and response.json() == {"detail": code}
        assert (await plugin.store.admin_get(row["id"]))["revision"] == 2
        changed.assert_not_called()
        plugin._ready = False
        assert (await client.delete(path, params={"revision": 2})).status_code == 503
        plugin._ready = True
        enabled = False
        assert (await client.delete(path, params={"revision": 2})).status_code == 404
        enabled = True
        response = await client.delete(path, params={"revision": 2})
        assert response.status_code == 200 and response.json() == {"ok": True, "memory_id": row["id"]}
        changed.assert_called_once_with()
        missing = await client.delete(path, params={"revision": 2})
        assert missing.status_code == 400 and missing.json() == {"detail": "not_found"}
    assert await plugin.store.admin_get(row["id"]) is None
    assert (await plugin.store.admin_get(kept["id"]))["text"] == "tea to keep"
    assert all(item["id"] != row["id"] for item in await plugin.store.search(scope(), "coffee"))
    async with plugin.store.connection() as db:
        async with db.execute("SELECT COUNT(*) FROM memory_fts WHERE memory_id=?", (row["id"],)) as cursor:
            assert (await cursor.fetchone())[0] == 0
    await plugin.terminate()


@pytest.mark.anyio
async def test_operator_delete_legacy_memory_keeps_other_records(tmp_path, monkeypatch):
    (tmp_path / "memory").mkdir()
    (tmp_path / "memory/core.txt").write_text("legacy coffee", encoding="utf-8")
    plugin = await plugin_at(tmp_path, monkeypatch)
    legacy = (await plugin.store.admin_list())["items"][0]
    kept, _ = await plugin.store.add(scope(persona="other"), text="keep coffee")
    for invalid in (True, "1", 0):
        with pytest.raises(MemoryInputError, match="invalid_revision"):
            await plugin.store.admin_remove(legacy["id"], invalid)
    await plugin.api_record_remove(legacy["id"], 1)
    assert await plugin.store.admin_get(legacy["id"]) is None
    assert (await plugin.store.admin_get(kept["id"]))["text"] == "keep coffee"
    await plugin.terminate()


def test_memory_schema_exposes_nested_embedding_and_rerank_settings():
    from core.config.config_field import build_fields

    path = Path(__file__).parents[1] / "core/plugin/builtin_plugins/memory/schema.json"
    schema = json.loads(path.read_text(encoding="utf-8-sig"))
    fields = {field.key: field.to_dict() for field in build_fields(schema)}
    assert fields["embedding"]["type"] == fields["rerank"]["type"] == "section"
    assert set(fields["embedding"]["fields"]) == {"enabled", "model", "timeout", "min_similarity", "candidates"}
    assert set(fields["rerank"]["fields"]) == {"enabled", "model", "timeout", "candidates"}
    assert fields["embedding"]["fields"]["model"]["model_type"] == "embedding"
    assert fields["rerank"]["fields"]["model"]["model_type"] == "rerank"
    assert not fields["embedding"]["fields"]["enabled"]["default"]
    assert not fields["rerank"]["fields"]["enabled"]["default"]
    assert fields["bm25_candidates"]["default"] == fields["embedding"]["fields"]["candidates"]["default"] == 50


@pytest.mark.anyio
@pytest.mark.parametrize("entry", ["runtime", "scoped_preview", "operator_preview"])
async def test_core_matches_do_not_consume_ordinary_recall_candidates(tmp_path, monkeypatch, entry):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={
        "core_limit": 6, "recall_limit": 6, "bm25_candidates": 6,
    })
    try:
        core = [await plugin.store.add(scope(), text=f"coffee {i}", core=True, importance=5)
                for i in range(6)]
        ordinary = [await plugin.store.add(scope(), text=f"coffee ordinary reminder {i}")
                    for i in range(6)]
        core_ids = {row["id"] for row, _ in core}
        ordinary_ids = {row["id"] for row, _ in ordinary}
        assert {row["id"] for row in await plugin.store.search(scope(), "coffee", limit=6)} == core_ids
        if entry == "runtime":
            result = await plugin.recall(scope(), ["coffee"])
        else:
            payload = {"messages": ["coffee"]}
            if entry == "scoped_preview":
                payload.update(adapter=scope().adapter, persona_id=scope().persona_id,
                               session_id=scope().session_id)
            result = await plugin.api_recall(payload)
        assert {row["id"] for row in result["core"]} == core_ids
        assert {row["id"] for row in result["recalled"]} == ordinary_ids
        assert len({row["id"] for row in result["core"] + result["recalled"]}) == 12
        assert result["prompt_chars"] <= 6000
        tool = json.loads(await plugin.memory_search(event(), query="coffee", limit=6))
        assert {row["id"] for row in tool["records"]} == core_ids
    finally:
        await plugin.terminate()


@pytest.mark.anyio
async def test_core_beyond_selected_core_limit_remains_retrievable(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={
        "core_limit": 1, "recall_limit": 1, "bm25_candidates": 1,
    })
    try:
        selected, _ = await plugin.store.add(scope(), text="coffee priority", core=True, importance=5)
        extra, _ = await plugin.store.add(scope(), text="coffee extra", core=True)
        result = await plugin.recall(scope(), ["coffee"])
        assert [row["id"] for row in result["core"]] == [selected["id"]]
        assert [row["id"] for row in result["recalled"]] == [extra["id"]]
    finally:
        await plugin.terminate()


@pytest.mark.anyio
@pytest.mark.parametrize("large_core", [False, True])
@pytest.mark.parametrize("with_other", [False, True])
async def test_recall_shares_unused_character_budget_in_both_directions(
        tmp_path, monkeypatch, large_core, with_other):
    plugin = await plugin_at(tmp_path, monkeypatch, cfg={
        "core_limit": 1, "recall_limit": 1, "prompt_char_budget": 6000,
    })
    try:
        text = "coffee " + "猫" * 3500
        large, _ = await plugin.store.add(scope(), text=text, core=large_core)
        if with_other:
            await plugin.store.add(scope(), text="coffee small record", core=not large_core)
        result = await plugin.recall(scope(), ["coffee"])
        assert await plugin.api_recall({"messages": ["coffee"]}) == result
        records = result["core"] + result["recalled"]
        saved = next(row for row in records if row["id"] == large["id"])
        assert saved["text"] == text and not saved.get("truncated")
        assert len(records) == 1 + with_other
        assert 3000 < result["prompt_chars"] == len(plugin.encode(records)) <= 6000
        request = LLMRequest(system_prompt=[Prompt("", name="memory")])
        await plugin.inject_memory(event(), request)
        assert json.loads(request.system_prompt[0].content.rsplit("\n", 1)[1]) == records
    finally:
        await plugin.terminate()
