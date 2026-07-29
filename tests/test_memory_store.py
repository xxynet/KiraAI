import asyncio
from pathlib import Path

from core.plugin.builtin_plugins.memory.memory_store import MemoryStore, tokenize


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
