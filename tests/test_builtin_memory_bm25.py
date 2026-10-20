"""BM25 relevance, token frequencies, scoped statistics, and index maintenance."""

import json
import math

import pytest

from tests.test_builtin_memory import event, plugin_at, scope, store_at


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_bm25_matches_reference_and_rewards_frequency_without_ignoring_length(tmp_path):
    store, _ = await store_at(tmp_path)
    once, _ = await store.add(scope(), text="猫")
    repeated, _ = await store.add(scope(), text="猫 猫")
    long, _ = await store.add(scope(), text="猫 " + "狗 " * 8)
    results = await store.search(scope(), "猫")
    assert [row["id"] for row in results] == [repeated["id"], once["id"], long["id"]]
    # These documents contain 2, 4 and 18 emitted tokens; both query tokens occur in all three.
    idf = math.log(1 + 0.5 / 3.5)
    expected = {}
    for record, frequency, length in ((once, 1, 2), (repeated, 2, 4), (long, 1, 18)):
        expected[record["id"]] = 3.25 * idf * frequency * 2.2 / (
            frequency + 1.2 * (0.25 + 0.75 * length / 8)
        )
    assert [row["score"] for row in results] == pytest.approx([expected[row["id"]] for row in results])
    assert [row["id"] for row in await store.search(scope(), "猫 猫")] == [row["id"] for row in results]


@pytest.mark.anyio
async def test_bm25_rare_terms_rank_above_common_terms_and_importance(tmp_path):
    store, _ = await store_at(tmp_path)
    rare, _ = await store.add(scope(), text="猫", importance=1)
    for index in range(1, 6):
        await store.add(scope(), text="狗" + "!" * index, importance=5)
    results = await store.search(scope(), "猫 狗")
    assert len(results) == 6 and results[0]["id"] == rare["id"]
    assert results[0]["score"] > max(row["score"] for row in results[1:])


@pytest.mark.anyio
async def test_bm25_statistics_exclude_other_scopes_and_inactive_memories(tmp_path):
    store, _ = await store_at(tmp_path)
    await store.add(scope(), text="猫")
    await store.add(scope(), text="狗")
    baseline = {row["id"]: row["score"] for row in await store.search(scope(), "猫 狗")}
    for context in (scope(persona="other"), scope(adapter="other"), scope(target="bob", users=("bob",))):
        await store.add(context, text="猫 " * 100)
    await store.add(scope(), text="猫 expired " * 50, expires_at=1)
    completed, _ = await store.add(scope(), text="狗 completed " * 50)
    await store.admin_update(completed["id"], 1, text=completed["text"], status="completed")
    actual = {row["id"]: row["score"] for row in await store.search(scope(), "猫 狗")}
    assert actual == pytest.approx(baseline)
    preview = await store.search_preview("猫 狗", persona_id=scope().persona_id, session_id=scope().session_id)
    assert {row["id"]: row["score"] for row in preview} == pytest.approx(baseline)


@pytest.mark.anyio
async def test_token_frequency_and_length_survive_normalization_and_are_replaced_on_edit(tmp_path):
    store, _ = await store_at(tmp_path)
    row, _ = await store.add(scope(), text="Ｃａｆé café 咖啡咖啡")
    assert row["term_count"] == 30
    async with store.connection() as db:
        async with db.execute("SELECT term,frequency FROM memory_terms WHERE memory_id=?", (row["id"],)) as cursor:
            frequencies = dict(await cursor.fetchall())
    assert frequencies["w:café"] == frequencies["g2:fé"] == 2
    assert frequencies["g2:咖啡"] == frequencies["g1:咖"] == 2
    assert frequencies["g3:咖啡咖"] == frequencies["g3:啡咖啡"] == 1
    updated = await store.admin_update(row["id"], 1, text="猫 猫")
    assert updated["term_count"] == 4
    async with store.connection() as db:
        async with db.execute("SELECT term,frequency FROM memory_terms WHERE memory_id=?", (row["id"],)) as cursor:
            assert dict(await cursor.fetchall()) == {"w:猫": 2, "g1:猫": 2}
    assert not await store.search(scope(), "café")
    await store.admin_remove(row["id"], 2)
    async with store.connection() as db:
        async with db.execute("SELECT COUNT(*) FROM memory_terms") as cursor:
            assert (await cursor.fetchone())[0] == 0


@pytest.mark.anyio
async def test_bm25_document_frequency_updates_after_add_edit_and_delete(tmp_path):
    store, _ = await store_at(tmp_path)
    first, _ = await store.add(scope(), text="猫")
    await store.add(scope(), text="狗")

    async def first_score():
        return next(row["score"] for row in await store.search(scope(), "猫") if row["id"] == first["id"])

    assert await first_score() == pytest.approx(3.25 * math.log(2))
    extra, _ = await store.add(scope(), text="猫!")
    assert await first_score() == pytest.approx(3.25 * math.log(1 + 1.5 / 2.5))
    await store.admin_update(extra["id"], 1, text="狗!")
    assert await first_score() == pytest.approx(3.25 * math.log(1 + 2.5 / 1.5))
    await store.remove(scope(), extra["id"], 2)
    assert await first_score() == pytest.approx(3.25 * math.log(2))


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
    assert row["term_count"] == 1
    assert [item["id"] for item in await store.search(scope())] == [row["id"]]
    assert await store.search(scope(), "!!!") == []
    assert await store.search(scope(), "猫") == []


@pytest.mark.anyio
async def test_bm25_frequency_gain_saturates_for_equal_length_memories(tmp_path):
    store, _ = await store_at(tmp_path)
    by_frequency = {}
    for frequency in (1, 2, 20):
        row, _ = await store.add(scope(), text="猫 " * frequency + "狗 " * (50 - frequency))
        assert row["term_count"] == 100
        by_frequency[row["id"]] = frequency
    scores = {by_frequency[row["id"]]: row["score"] for row in await store.search(scope(), "猫")}
    assert scores[1] < scores[2] < scores[20] < 2.2 * scores[1]
    assert (scores[20] - scores[2]) / 18 < scores[2] - scores[1]
