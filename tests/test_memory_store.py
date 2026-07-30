import asyncio
from types import SimpleNamespace
from pathlib import Path

from core.plugin.builtin_plugins.memory.memory_store import MemoryStore, tokenize
from core.plugin.builtin_plugins.memory.main import MemoryPlugin


def run(coro):
    return asyncio.run(coro)


def test_tokenize_supports_mixed_language_without_external_tokenizer():
    terms = tokenize("用户喜欢 Rust 和冰美式")

    assert "rust" in terms
    assert "冰美" in terms
    assert "美式" in terms


def test_memory_store_scopes_deduplicates_and_updates_index(tmp_path: Path):
    async def scenario():
        store = MemoryStore(tmp_path / "memory.db")
        await store.initialize()
        try:
            user_item = await store.add("用户喜欢冰美式", "user", "qq:1")
            await store.add("用户喜欢冰美式", "user", "qq:1")
            await store.add("用户喜欢绿茶", "user", "qq:2")

            results = await store.search("冰美式", [("user", "qq:1")])
            assert [item["id"] for item in results] == [user_item["id"]]

            await store.update(user_item["id"], "用户现在喜欢绿茶")
            assert await store.search("冰美式", [("user", "qq:1")]) == []
            assert await store.search("绿茶", [("user", "qq:1")])
        finally:
            await store.close()

    run(scenario())


def test_legacy_core_txt_migration_is_idempotent(tmp_path: Path):
    async def scenario():
        legacy = tmp_path / "core.txt"
        legacy.write_text("喜欢咖啡\n\n喜欢旅行\n", encoding="utf-8")
        store = MemoryStore(tmp_path / "memory.db")
        await store.initialize()
        try:
            assert await store.migrate_legacy(legacy) == 2
            assert await store.migrate_legacy(legacy) == 0
            memories = await store.list([("global", "")])
            assert {item["text"] for item in memories} == {"喜欢咖啡", "喜欢旅行"}
        finally:
            await store.close()

    run(scenario())


def test_memory_limit_is_enforced_per_scope(tmp_path: Path):
    async def scenario():
        store = MemoryStore(tmp_path / "memory.db", max_memories=1)
        await store.initialize()
        try:
            global_item = await store.add("global fact", "global", "", importance=0.1)
            user_item = await store.add("important user fact", "user", "qq:1", importance=0.9)
            await store.add("temporary user fact", "user", "qq:1", importance=0.1)

            global_items = await store.list([("global", "")])
            user_items = await store.list([("user", "qq:1")])
            assert [item["id"] for item in global_items] == [global_item["id"]]
            assert [item["id"] for item in user_items] == [user_item["id"]]
        finally:
            await store.close()

    run(scenario())


def test_private_and_group_scope_semantics():
    plugin = MemoryPlugin(None, {})
    private_event = SimpleNamespace(
        session=SimpleNamespace(sid="qq:dm:100"),
        adapter=SimpleNamespace(name="qq"),
        messages=[SimpleNamespace(
            sender=SimpleNamespace(user_id="100"),
            group=None,
        )],
    )
    group_event = SimpleNamespace(
        session=SimpleNamespace(sid="qq:gm:200"),
        adapter=SimpleNamespace(name="qq"),
        messages=[SimpleNamespace(
            sender=SimpleNamespace(user_id="100"),
            group=SimpleNamespace(group_id="200"),
        )],
    )

    assert plugin._scope_owner(private_event, "") == ("user", "qq:100")
    assert plugin._scopes(private_event) == [("global", ""), ("user", "qq:100")]
    assert plugin._scope_owner(group_event, "") == ("session", "qq:gm:200")
    assert plugin._scopes(group_event) == [
        ("global", ""), ("session", "qq:gm:200"), ("user", "qq:100")
    ]
