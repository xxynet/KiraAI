"""Native FTS5 BM25 ranking, exact N-gram matching, and transactional index maintenance."""

from collections import Counter
import json
import math

import pytest

from core.plugin.builtin_plugins.memory.search import FTS_COLUMNS, match_query
from tests.test_builtin_memory import event, plugin_at, scope, store_at


@pytest.fixture
def anyio_backend():
    return "asyncio"


def reference_score(frequency, length, average_length, documents, document_frequency):
    """Reference the native BM25 formula for one-character queries in two columns."""
    idf = max(1e-6, math.log((documents - document_frequency + 0.5) / (document_frequency + 0.5)))
    norm = 1.2 * (0.25 + 0.75 * length / average_length)
    return -sum(idf * frequency * weight * 2.2 / (frequency * weight + norm) for weight in (3, 0.25))


@pytest.mark.anyio
async def test_bm25_matches_native_formula_and_rewards_frequency_without_ignoring_length(tmp_path):
    store, _ = await store_at(tmp_path)
    once, _ = await store.add(scope(), text="猫")
    repeated, _ = await store.add(scope(), text="猫 猫")
    long, _ = await store.add(scope(), text="猫 " + "狗 " * 8)
    results = await store.search(scope(), "猫")
    assert [row["id"] for row in results] == [repeated["id"], once["id"], long["id"]]
    expected = {}
    for record, frequency, length in ((once, 1, 2), (repeated, 2, 4), (long, 1, 18)):
        expected[record["id"]] = reference_score(frequency, length, 8, 3, 3)
    assert [row["score"] for row in results] == pytest.approx([expected[row["id"]] for row in results])
    assert all(row["score"] < 0 for row in results)
    assert [row["id"] for row in await store.search(scope(), "猫 猫")] == [row["id"] for row in results]


@pytest.mark.anyio
async def test_bm25_rare_terms_rank_above_common_terms_and_importance(tmp_path):
    store, _ = await store_at(tmp_path)
    rare, _ = await store.add(scope(), text="猫", importance=1)
    for index in range(1, 6):
        await store.add(scope(), text="狗" + "!" * index, importance=5)
    results = await store.search(scope(), "猫 狗")
    assert len(results) == 6 and results[0]["id"] == rare["id"]
    assert results[0]["score"] < min(row["score"] for row in results[1:])


@pytest.mark.anyio
async def test_fts_statistics_are_global_but_visibility_and_eligibility_are_filtered_before_limit(tmp_path):
    store, _ = await store_at(tmp_path)
    visible = [await store.add(scope(), text=text) for text in ("猫", "狗")]
    baseline = {row["id"]: row["score"] for row in await store.search(scope(), "猫 狗")}
    for context in (scope(persona="other"), scope(adapter="other"), scope(target="bob", users=("bob",))):
        await store.add(context, text="猫 " * 100)
    await store.add(scope(), text="猫 expired " * 50, expires_at=1)
    completed, _ = await store.add(scope(), text="狗 completed " * 50)
    await store.admin_update(completed["id"], 1, text=completed["text"], status="completed")
    actual = {row["id"]: row["score"] for row in await store.search(scope(), "猫 狗")}
    assert set(actual) == {row["id"] for row, _ in visible}
    assert actual != pytest.approx(baseline)
    preview = await store.search_preview("猫 狗", persona_id=scope().persona_id, session_id=scope().session_id)
    assert {row["id"]: row["score"] for row in preview} == pytest.approx(actual)
    assert len(await store.search(scope(), "猫 狗", limit=1)) == 1


@pytest.mark.anyio
async def test_token_frequency_survives_normalization_and_is_replaced_on_edit(tmp_path):
    store, _ = await store_at(tmp_path)
    row, _ = await store.add(scope(), text="Ｃａｆé café 咖啡咖啡")

    async def frequencies():
        async with store.connection() as db:
            async with db.execute("SELECT w,g1,g2,g3 FROM memory_fts WHERE memory_id=?", (row["id"],)) as cursor:
                columns = await cursor.fetchone()
        return {
            f"{name}:{bytes.fromhex(token).decode('utf-8')}": frequency
            for name, column in zip(FTS_COLUMNS, columns)
            for token, frequency in Counter(column.split()).items()
        }

    indexed = await frequencies()
    assert sum(indexed.values()) == 30
    assert indexed["w:café"] == indexed["g2:fé"] == 2
    assert indexed["g2:咖啡"] == indexed["g1:咖"] == 2
    assert indexed["g3:咖啡咖"] == indexed["g3:啡咖啡"] == 1
    assert (await store.admin_get(row["id"]))["terms"] == len(indexed)
    updated = await store.admin_update(row["id"], 1, text="猫 猫")
    assert updated["terms"] == 2
    assert await frequencies() == {"w:猫": 2, "g1:猫": 2}
    assert not await store.search(scope(), "café")
    await store.admin_remove(row["id"], 2)
    async with store.connection() as db:
        async with db.execute("SELECT COUNT(*) FROM memory_fts") as cursor:
            assert (await cursor.fetchone())[0] == 0
        async with db.execute("SELECT name FROM sqlite_master WHERE name='memory_terms'") as cursor:
            assert await cursor.fetchone() is None


@pytest.mark.anyio
async def test_bm25_document_frequency_updates_after_add_edit_and_delete(tmp_path):
    store, _ = await store_at(tmp_path)
    first, _ = await store.add(scope(), text="猫")
    await store.add(scope(), text="狗")

    async def first_score():
        return next(row["score"] for row in await store.search(scope(), "猫") if row["id"] == first["id"])

    assert await first_score() == pytest.approx(reference_score(1, 2, 2, 2, 1))
    extra, _ = await store.add(scope(), text="猫!")
    assert await first_score() == pytest.approx(reference_score(1, 2, 2, 3, 2))
    await store.admin_update(extra["id"], 1, text="狗!")
    assert await first_score() == pytest.approx(reference_score(1, 2, 2, 3, 1))
    await store.remove(scope(), extra["id"], 2)
    assert await first_score() == pytest.approx(reference_score(1, 2, 2, 2, 1))


@pytest.mark.anyio
async def test_bm25_order_is_shared_by_tools_preview_admin_and_pagination(tmp_path, monkeypatch):
    plugin = await plugin_at(tmp_path, monkeypatch)
    for text in ("猫", "猫 猫", "猫 " + "狗 " * 8):
        await plugin.store.add(scope(), text=text)
    expected = [row["id"] for row in await plugin.search(scope(), "猫")]
    tool = json.loads(await plugin.memory_search(event(), query="猫"))
    assert [row["id"] for row in tool["records"]] == expected
    preview = await plugin.api_recall({"messages": ["猫"]})
    assert [row["id"] for row in preview["recalled"]] == expected
    assert preview["retrieval"]["mode"] == "keyword"
    admin = await plugin.api_records(q="猫")
    assert [row["id"] for row in admin["items"]] == expected
    assert [(await plugin.store.admin_list(query="猫", page=page, size=1))["items"][0]["id"]
            for page in range(1, 4)] == expected
    assert [(await plugin.store.search(scope(), "猫", limit=1, offset=offset))[0]["id"]
            for offset in range(3)] == expected
    await plugin.terminate()


@pytest.mark.anyio
async def test_bm25_handles_empty_corpus_punctuation_and_unmatched_queries(tmp_path):
    store, _ = await store_at(tmp_path)
    assert await store.search(scope(), "猫") == []
    assert (await store.admin_list(query="猫"))["total"] == 0
    row, _ = await store.add(scope(), text="!!!")
    assert [item["id"] for item in await store.search(scope())] == [row["id"]]
    assert (await store.admin_get(row["id"]))["terms"] == 0
    assert await store.search(scope(), "!!!") == []
    assert await store.search(scope(), "猫") == []


@pytest.mark.anyio
async def test_bm25_frequency_gain_saturates_for_equal_length_memories(tmp_path):
    store, _ = await store_at(tmp_path)
    by_frequency = {}
    for frequency in (1, 2, 20):
        row, _ = await store.add(scope(), text="猫 " * frequency + "狗 " * (50 - frequency))
        by_frequency[row["id"]] = frequency
    scores = {by_frequency[row["id"]]: -row["score"] for row in await store.search(scope(), "猫")}
    assert scores[1] < scores[2] < scores[20] < 4.4e-6
    assert (scores[20] - scores[2]) / 18 < scores[2] - scores[1]


@pytest.mark.anyio
@pytest.mark.parametrize("text,query,matched", [
    ("Ｃａｆé", "café", True),
    ("café", "cafe", True),
    ("é", "e", False),
    ("किरण", "किरण", True),
    ("が", "が", True),
    ("甲乙", "甲丙", False),
    ("a b", "ab", False),
    ("牛奶咖啡", "咖啡", True),
    ("single", "s", True),
    ("狗", '" OR 猫* NOT (狗) : NEAR', True),
])
async def test_fts_preserves_exact_unicode_tokens_and_gram_boundaries(tmp_path, text, query, matched):
    store, _ = await store_at(tmp_path)
    await store.add(scope(), text=text)
    assert bool(await store.search(scope(), query)) is matched
    assert (await store.admin_list(query=query))["total"] == int(matched)
    assert len(await store.search(scope())) == 1


@pytest.mark.anyio
async def test_fts_long_query_keeps_tail_and_does_not_accept_match_or_sql_syntax(tmp_path):
    store, _ = await store_at(tmp_path)
    tail, _ = await store.add(scope(), text="海风计划")
    await store.add(scope(persona="other"), text="海风计划 海风计划")
    query = " ".join(f"prefix{index}" for index in range(600)) + ' " OR 海风计划*; DROP TABLE memories; --'
    assert len(match_query(query).split(" OR ")) > 512
    assert [row["id"] for row in await store.search(scope(), query)] == [tail["id"]]
    assert (await store.admin_list(query=query))["total"] == 2
    assert len(await store.search(scope())) == 1
    assert await store.search(scope(), '"" * () : + -') == []


@pytest.mark.anyio
async def test_fts_index_and_memory_changes_rollback_together(tmp_path):
    store, _ = await store_at(tmp_path)
    row, _ = await store.add(scope(), text="咖啡")
    with pytest.raises(RuntimeError):
        async with store.connection(write=True) as db:
            await db.execute("UPDATE memories SET text='茶' WHERE id=?", (row["id"],))
            await store._index(db, row["id"], "茶")
            raise RuntimeError("rollback")
    assert [r["id"] for r in await store.search(scope(), "咖啡")] == [row["id"]]
    assert await store.search(scope(), "茶") == []
    with pytest.raises(RuntimeError):
        async with store.connection(write=True) as db:
            await db.execute("DELETE FROM memories WHERE id=?", (row["id"],))
            raise RuntimeError("rollback")
    assert [r["id"] for r in await store.search(scope(), "咖啡")] == [row["id"]]
    async with store.connection(write=True) as db:
        await db.execute("DELETE FROM memories WHERE id=?", (row["id"],))
    assert await store.search(scope(), "咖啡") == []


@pytest.mark.anyio
async def test_fts_survives_restart_and_vacuum_without_rowid_coupling(tmp_path):
    store, _ = await store_at(tmp_path)
    first, _ = await store.add(scope(), text="猫")
    second, _ = await store.add(scope(), text="狗")
    await store.admin_remove(first["id"], 1)
    async with store.connection() as db:
        await db.execute("VACUUM")
    assert await store.initialize(tmp_path / "core.txt") == 0
    assert [r["id"] for r in await store.search(scope(), "狗")] == [second["id"]]
    await store.admin_update(second["id"], 1, text="茶")
    assert await store.search(scope(), "狗") == []
    assert [r["id"] for r in await store.search(scope(), "茶")] == [second["id"]]
    await store.admin_remove(second["id"], 2)
    assert await store.search(scope(), "茶") == []
