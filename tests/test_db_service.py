import time
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.telemetry.client import TelemetryClient


@pytest.fixture
async def svc():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await manager.init()
    service = DatabaseService(manager)
    await service.init_tables()
    yield service
    await manager.dispose()


@pytest.mark.anyio
async def test_sticker_crud(svc):
    await svc.add_sticker("s1", "desc1", "path1.png", extra={"tags": ["a", "b"]})

    item = await svc.get_sticker("s1")
    assert item is not None
    assert item["id"] == "s1"
    assert item["desc"] == "desc1"
    assert item["path"] == "path1.png"
    assert item["extra"] == {"tags": ["a", "b"]}

    items = await svc.list_stickers()
    assert len(items) == 1
    assert items[0]["id"] == "s1"

    deleted = await svc.delete_sticker("s1")
    assert deleted is True

    item = await svc.get_sticker("s1")
    assert item is None

    deleted = await svc.delete_sticker("s1")
    assert deleted is False


@pytest.mark.anyio
async def test_image_desc_cache_crud(svc):
    await svc.add_image_desc_cache(
        "abc123", "a cute cat", count=1, last_seen=1000
    )

    item = await svc.get_image_desc_cache("abc123")
    assert item is not None
    assert item["md5"] == "abc123"
    assert item["description"] == "a cute cat"
    assert item["count"] == 1
    assert item["last_seen"] == 1000

    updated = await svc.update_image_desc_cache(
        "abc123", description="a cute dog", count=5, last_seen=2000
    )
    assert updated is True

    item = await svc.get_image_desc_cache("abc123")
    assert item["description"] == "a cute dog"
    assert item["count"] == 5
    assert item["last_seen"] == 2000

    deleted = await svc.delete_image_desc_cache("abc123")
    assert deleted is True

    item = await svc.get_image_desc_cache("abc123")
    assert item is None

    updated = await svc.update_image_desc_cache("not_exist", count=1)
    assert updated is False


@pytest.mark.anyio
async def test_persona_crud(svc):
    await svc.add_persona("default", "Default Persona", "Hello, I am Kira.", format="text")

    item = await svc.get_persona("default")
    assert item is not None
    assert item["id"] == "default"
    assert item["name"] == "Default Persona"
    assert item["format"] == "text"
    assert item["content"] == "Hello, I am Kira."

    updated = await svc.update_persona("default", name="Updated Name", content="Updated content.", format="markdown")
    assert updated is True

    item = await svc.get_persona("default")
    assert item["name"] == "Updated Name"
    assert item["content"] == "Updated content."
    assert item["format"] == "markdown"

    items = await svc.list_personas()
    assert len(items) == 1
    assert items[0]["id"] == "default"

    deleted = await svc.delete_persona("default")
    assert deleted is True

    item = await svc.get_persona("default")
    assert item is None

    updated = await svc.update_persona("not_exist", content="x")
    assert updated is False


@pytest.mark.anyio
async def test_sticker_update(svc):
    await svc.add_sticker("s1", "old desc", "old.png", extra={"v": 1})

    updated = await svc.update_sticker("s1", desc="new desc", path="new.png", extra={"v": 2})
    assert updated is True

    item = await svc.get_sticker("s1")
    assert item["desc"] == "new desc"
    assert item["path"] == "new.png"
    assert item["extra"] == {"v": 2}

    updated = await svc.update_sticker("s1", desc="partial")
    item = await svc.get_sticker("s1")
    assert item["desc"] == "partial"
    assert item["path"] == "new.png"

    updated = await svc.update_sticker("not_exist", desc="x")
    assert updated is False


@pytest.mark.anyio
async def test_cleanup_expired_image_desc_cache(svc):
    now = int(time.time())
    fifteen_days = 15 * 24 * 60 * 60
    thirty_days = 30 * 24 * 60 * 60

    await svc.add_image_desc_cache("old_low", "old low count", count=1, last_seen=now - fifteen_days - 1)
    await svc.add_image_desc_cache("old_med", "old med count", count=2, last_seen=now - thirty_days - 1)
    await svc.add_image_desc_cache("fresh", "fresh entry", count=1, last_seen=now)
    await svc.add_image_desc_cache("old_high", "old high count", count=5, last_seen=now - thirty_days - 1)

    deleted = await svc.cleanup_expired_image_desc_cache()
    assert deleted == 2

    assert await svc.get_image_desc_cache("old_low") is None
    assert await svc.get_image_desc_cache("old_med") is None
    assert await svc.get_image_desc_cache("fresh") is not None
    assert await svc.get_image_desc_cache("old_high") is not None


@pytest.mark.anyio
async def test_plugin_store_source_crud(svc):
    await svc.add_plugin_store_source(
        "src1", "Official", "https://example.com/plugins",
        cache_file="official.json", updated_at=1000, is_current=True, created_at=1000,
    )

    item = await svc.get_plugin_store_source("src1")
    assert item is not None
    assert item["id"] == "src1"
    assert item["name"] == "Official"
    assert item["url"] == "https://example.com/plugins"
    assert item["cache_file"] == "official.json"
    assert item["updated_at"] == 1000
    assert item["is_current"] is True
    assert item["created_at"] == 1000

    by_url = await svc.get_plugin_store_source_by_url("https://example.com/plugins")
    assert by_url is not None
    assert by_url["id"] == "src1"

    assert await svc.get_plugin_store_source_by_url("https://nope.com") is None

    await svc.add_plugin_store_source(
        "src2", "Community", "https://community.com/plugins",
        cache_file="community.json", updated_at=2000, created_at=2000,
    )

    items = await svc.list_plugin_store_sources()
    assert len(items) == 2
    assert items[0]["id"] == "src1"
    assert items[1]["id"] == "src2"

    updated = await svc.update_plugin_store_source(
        "src2", name="Community v2", url="https://community.com/v2",
        cache_file="community_v2.json", updated_at=3000,
    )
    assert updated is True

    item = await svc.get_plugin_store_source("src2")
    assert item["name"] == "Community v2"
    assert item["url"] == "https://community.com/v2"
    assert item["cache_file"] == "community_v2.json"
    assert item["updated_at"] == 3000

    updated = await svc.update_plugin_store_source("not_exist", name="x")
    assert updated is False

    deleted = await svc.delete_plugin_store_source("src1")
    assert deleted is True
    assert await svc.get_plugin_store_source("src1") is None

    deleted = await svc.delete_plugin_store_source("src1")
    assert deleted is False


@pytest.mark.anyio
async def test_plugin_store_source_is_current_invariant(svc):
    await svc.add_plugin_store_source("a", "A", "https://a.com", is_current=True)
    await svc.add_plugin_store_source("b", "B", "https://b.com", is_current=False)

    item_a = await svc.get_plugin_store_source("a")
    item_b = await svc.get_plugin_store_source("b")
    assert item_a["is_current"] is True
    assert item_b["is_current"] is False

    await svc.add_plugin_store_source("c", "C", "https://c.com", is_current=True)

    item_a = await svc.get_plugin_store_source("a")
    item_c = await svc.get_plugin_store_source("c")
    assert item_a["is_current"] is False
    assert item_c["is_current"] is True

    await svc.update_plugin_store_source("b", is_current=True)

    item_b = await svc.get_plugin_store_source("b")
    item_c = await svc.get_plugin_store_source("c")
    assert item_b["is_current"] is True
    assert item_c["is_current"] is False


# ------------------------------------------------------------------
# Telemetry raw records
# ------------------------------------------------------------------

HOUR = 3600


@pytest.mark.anyio
async def test_telemetry_messages_aggregation(svc):
    # hour 10: 1718000000 // 3600 * 3600 = exact boundary
    h10 = 10 * HOUR  # epoch 36000
    h11 = 11 * HOUR  # epoch 39600

    # 3 messages in hour 10 (two QQ, one Telegram)
    await svc.add_telemetry_message(h10 + 100, "QQ")
    await svc.add_telemetry_message(h10 + 200, "QQ")
    await svc.add_telemetry_message(h10 + 300, "Telegram")

    # 1 message in hour 11 (also unreported, should show up)
    await svc.add_telemetry_message(h11 + 100, "Discord")

    rows = await svc.get_unreported_telemetry_messages_by_hour(since_ts=0)
    assert len(rows) == 3  # QQ, Telegram, Discord
    by_platform = {(r["hour_ts"], r["platform"]): r["count"] for r in rows}
    assert by_platform[(h10, "QQ")] == 2
    assert by_platform[(h10, "Telegram")] == 1
    assert by_platform[(h11, "Discord")] == 1

    # Mark all as reported, then query again — should be empty
    await svc.mark_telemetry_reported()
    rows = await svc.get_unreported_telemetry_messages_by_hour(since_ts=0)
    assert rows == []


@pytest.mark.anyio
async def test_telemetry_messages_empty_range(svc):
    rows = await svc.get_unreported_telemetry_messages_by_hour(since_ts=0)
    assert rows == []


@pytest.mark.anyio
async def test_llm_usage_source_survives_migration_and_is_reported(svc, monkeypatch):
    now = int(time.time())
    async with svc.db.engine.begin() as connection:
        await connection.execute(text("ALTER TABLE telemetry_llm_usage DROP COLUMN source"))
        await connection.execute(text(
            "INSERT INTO telemetry_llm_usage "
            "(id, timestamp, model, input_tokens, output_tokens, response_time_ms, success, reported) "
            "VALUES ('legacy', :timestamp, 'shared', 20, 10, 100, true, false)"
        ), {"timestamp": now})
    await svc.init_tables()
    for source, count in [("main", 1), ("subagent", 3)]:
        for _ in range(count):
            await svc.add_telemetry_llm_usage(now, "shared", 20, 10, 5, 200, True, source=source)
    await svc.init_tables()

    client = TelemetryClient(svc, SimpleNamespace(get_config=lambda *args, **kwargs: {}))
    reports = []
    monkeypatch.setattr(client, "send_event", lambda event_type, data, on_success: reports.append(
        (event_type, data, on_success)
    ))
    await client._report_stats()

    (event_type, data, on_success), = reports
    assert event_type == "llm_usage"
    assert data["total_calls"] == data["models"]["shared"]["total_calls"] == 5
    main = data["models_by_source"]["main"]["shared"]
    subagent = data["models_by_source"]["subagent"]["shared"]
    assert (main["total_calls"], subagent["total_calls"]) == (2, 3)
    assert (main["total_input_tokens"], subagent["total_input_tokens"]) == (40, 60)
    assert (main["avg_response_time_ms"], subagent["avg_response_time_ms"]) == (150, 200)
    await on_success()
    assert await svc.get_unreported_telemetry_llm_usage_rows(0) == []


@pytest.mark.anyio
async def test_telemetry_llm_usage_aggregation(svc):
    h10 = 10 * HOUR

    # 2 successful calls on gpt-4o
    await svc.add_telemetry_llm_usage(h10 + 100, "gpt-4o", 1000, 500, 100, 800, True)
    await svc.add_telemetry_llm_usage(h10 + 200, "gpt-4o", 2000, 800, 200, 1200, True)
    # 1 failed call on deepseek
    await svc.add_telemetry_llm_usage(h10 + 300, "deepseek", 500, 0, None, 5000, False)

    rows = await svc.get_unreported_telemetry_llm_usage_by_hour(since_ts=0)
    assert len(rows) == 2
    by_model = {r["model"]: r for r in rows}

    gpt = by_model["gpt-4o"]
    assert gpt["call_count"] == 2
    assert gpt["success_count"] == 2
    assert gpt["total_input"] == 3000
    assert gpt["total_output"] == 1300
    assert gpt["total_cached"] == 300
    assert gpt["total_response_ms"] == 2000

    ds = by_model["deepseek"]
    assert ds["call_count"] == 1
    assert ds["success_count"] == 0
    assert ds["total_input"] == 500
    assert ds["total_output"] == 0

    # Mark and verify
    await svc.mark_telemetry_reported()
    rows = await svc.get_unreported_telemetry_llm_usage_by_hour(since_ts=0)
    assert rows == []


@pytest.mark.anyio
async def test_llm_summary_derives_totals_from_model_rows():
    model_rows = [
        {
            "model": "gpt-4o",
            "calls": 2,
            "success": 2,
            "input_tokens": 3000,
            "output_tokens": 1300,
            "cached_tokens": 300,
            "total_response_ms": 2000,
        },
        {
            "model": "deepseek",
            "calls": 1,
            "success": 0,
            "input_tokens": 500,
            "output_tokens": 0,
            "cached_tokens": 0,
            "total_response_ms": 5000,
        },
    ]

    class SummaryDatabase:
        async def fetch_all(self, _stmt):
            return model_rows

        async def fetch_one(self, _stmt):
            raise AssertionError("LLM summary totals must use the per-model query snapshot")

    summary = await DatabaseService(SummaryDatabase()).get_llm_summary(since_ts=0)

    assert summary["total_calls"] == 3
    assert summary["total_input_tokens"] == 3500
    assert summary["total_output_tokens"] == 1300
    assert summary["total_cached_tokens"] == 300
    assert summary["success_count"] == 2
    assert summary["total_response_ms"] == 7000
    assert len(summary["by_model"]) == 2


@pytest.mark.anyio
async def test_main_cache_hit_hourly_filters_and_weights(svc):
    h10 = 10 * HOUR

    # Only main calls that report cached_tokens and consumed input tokens count.
    await svc.add_telemetry_llm_usage(h10 + 100, "gpt-4o", 1000, 500, 800, 800, True, source="main")
    await svc.add_telemetry_llm_usage(h10 + 200, "gpt-4o", 200, 100, None, 800, True, source="main")
    await svc.add_telemetry_llm_usage(h10 + 300, "gpt-4o", 1000, 100, 900, 800, True, source="subagent")
    await svc.add_telemetry_llm_usage(h10 + 400, "gpt-4o", 0, 0, 0, 800, True, source="main")

    rows = await svc.get_main_cache_hit_hourly(since_ts=0)
    assert len(rows) == 1
    row = rows[0]
    assert row["hour_ts"] == h10
    assert row["model"] == "gpt-4o"
    assert row["calls"] == 1
    assert row["cached_tokens"] == 800
    assert row["input_tokens"] == 1000
    assert row["hit_rate"] == 80.0

    # A second main call in the same hour is token-weighted into the same bucket.
    await svc.add_telemetry_llm_usage(h10 + 500, "gpt-4o", 3000, 100, 600, 800, True, source="main")
    rows = await svc.get_main_cache_hit_hourly(since_ts=0)
    assert len(rows) == 1
    row = rows[0]
    assert row["calls"] == 2
    assert row["cached_tokens"] == 1400
    assert row["input_tokens"] == 4000
    assert row["hit_rate"] == 35.0


@pytest.mark.anyio
async def test_main_cache_hit_hourly_boundaries_and_empty(svc):
    h10 = 10 * HOUR

    # No reportable rows yet.
    assert await svc.get_main_cache_hit_hourly(since_ts=0) == []

    await svc.add_telemetry_llm_usage(h10, "m", 100, 10, 50, 100, True, source="main")
    await svc.add_telemetry_llm_usage(h10 + 3599, "m", 100, 10, 50, 100, True, source="main")

    # Both timestamps fall into the same hour bucket (boundary is inclusive).
    rows = await svc.get_main_cache_hit_hourly(since_ts=h10)
    assert len(rows) == 1
    assert rows[0]["hour_ts"] == h10
    assert rows[0]["model"] == "m"
    assert rows[0]["calls"] == 2
    assert rows[0]["hit_rate"] == 50.0

    # since_ts is inclusive: the row exactly at h10 drops out, the bucket stays.
    rows = await svc.get_main_cache_hit_hourly(since_ts=h10 + 1)
    assert len(rows) == 1
    assert rows[0]["hour_ts"] == h10
    assert rows[0]["calls"] == 1

    # Excluding the whole hour yields nothing.
    assert await svc.get_main_cache_hit_hourly(since_ts=h10 + HOUR) == []


@pytest.mark.anyio
async def test_main_cache_hit_hourly_splits_by_model(svc):
    h10 = 10 * HOUR
    h11 = 11 * HOUR

    # Two gpt-4o calls in the same hour merge into one bucket.
    await svc.add_telemetry_llm_usage(h10 + 100, "gpt-4o", 1000, 500, 800, 800, True, source="main")
    await svc.add_telemetry_llm_usage(h10 + 200, "gpt-4o", 1000, 500, 200, 800, True, source="main")
    # A different model keeps its own curve.
    await svc.add_telemetry_llm_usage(h10 + 300, "deepseek", 1000, 100, 100, 800, True, source="main")
    # Subagent calls and NULL cache reports must not leak into the main curve.
    await svc.add_telemetry_llm_usage(h10 + 400, "deepseek", 1000, 100, 900, 800, True, source="subagent")
    await svc.add_telemetry_llm_usage(h10 + 500, "deepseek", 1000, 100, None, 800, True, source="main")
    await svc.add_telemetry_llm_usage(h11 + 100, "deepseek", 500, 100, 0, 800, True, source="main")

    rows = await svc.get_main_cache_hit_hourly(since_ts=0)
    assert [(r["hour_ts"], r["model"]) for r in rows] == [
        (h10, "deepseek"),
        (h10, "gpt-4o"),
        (h11, "deepseek"),
    ]

    by_bucket = {(r["hour_ts"], r["model"]): r for r in rows}
    gpt = by_bucket[(h10, "gpt-4o")]
    assert (gpt["cached_tokens"], gpt["input_tokens"], gpt["calls"]) == (1000, 2000, 2)
    assert gpt["hit_rate"] == 50.0
    deepseek = by_bucket[(h10, "deepseek")]
    assert (deepseek["cached_tokens"], deepseek["input_tokens"], deepseek["calls"]) == (100, 1000, 1)
    assert deepseek["hit_rate"] == 10.0
    assert by_bucket[(h11, "deepseek")]["hit_rate"] == 0.0


@pytest.mark.anyio
async def test_telemetry_message_rows_and_mark_by_ids(svc):
    h10 = 10 * HOUR
    await svc.add_telemetry_message(h10 + 100, "QQ")
    await svc.add_telemetry_message(h10 + 200, "QQ")
    await svc.add_telemetry_message(h10 + 300, "Telegram")

    rows = await svc.get_unreported_telemetry_message_rows(since_ts=0)
    assert len(rows) == 3
    assert all(r["id"] for r in rows)
    # Per-row data aggregates to the same counts as the SQL aggregate query.
    counts: dict = {}
    for r in rows:
        counts[(r["hour_ts"], r["platform"])] = counts.get((r["hour_ts"], r["platform"]), 0) + 1
    assert counts[(h10, "QQ")] == 2
    assert counts[(h10, "Telegram")] == 1

    # Marking exactly those ids clears them (and only them).
    await svc.mark_telemetry_messages_by_ids([r["id"] for r in rows])
    assert await svc.get_unreported_telemetry_message_rows(since_ts=0) == []


@pytest.mark.anyio
async def test_telemetry_llm_usage_rows_fields(svc):
    h10 = 10 * HOUR
    await svc.add_telemetry_llm_usage(h10 + 100, "gpt-4o", 1000, 500, 100, 800, True)
    await svc.add_telemetry_llm_usage(h10 + 300, "deepseek", 500, 0, None, 5000, False)

    rows = await svc.get_unreported_telemetry_llm_usage_rows(since_ts=0)
    assert len(rows) == 2
    by_model = {r["model"]: r for r in rows}
    assert by_model["gpt-4o"]["input_tokens"] == 1000
    assert by_model["gpt-4o"]["cached_tokens"] == 100
    assert by_model["gpt-4o"]["success"] in (True, 1)
    # None cached_tokens is normalized to 0.
    assert by_model["deepseek"]["cached_tokens"] == 0
    assert by_model["deepseek"]["success"] in (False, 0)
    assert all(r["id"] for r in rows)

    await svc.mark_telemetry_llm_by_ids([r["id"] for r in rows])
    assert await svc.get_unreported_telemetry_llm_usage_rows(since_ts=0) == []


@pytest.mark.anyio
async def test_mark_telemetry_messages_by_ids_chunks_over_limit(svc):
    # More than SQLite's ~999 bound-parameter limit, to exercise the chunked
    # WHERE id IN (...) marking and ensure it doesn't raise "too many SQL variables".
    h10 = 10 * HOUR
    for i in range(1100):
        await svc.add_telemetry_message(h10 + i, "QQ")
    rows = await svc.get_unreported_telemetry_message_rows(since_ts=0)
    assert len(rows) == 1100
    await svc.mark_telemetry_messages_by_ids([r["id"] for r in rows])
    assert await svc.get_unreported_telemetry_message_rows(since_ts=0) == []


@pytest.mark.anyio
async def test_delete_telemetry_records_before(svc):
    h10 = 10 * HOUR
    h20 = 20 * HOUR
    h30 = 30 * HOUR

    await svc.add_telemetry_message(h10 + 100, "QQ")
    await svc.add_telemetry_message(h20 + 100, "QQ")
    await svc.add_telemetry_message(h30 + 100, "QQ")
    await svc.add_telemetry_llm_usage(h10 + 100, "gpt-4o", 100, 50, None, 500, True)
    await svc.add_telemetry_llm_usage(h20 + 100, "gpt-4o", 100, 50, None, 500, True)

    # Delete everything before h20 — should remove h10 records only
    await svc.delete_telemetry_records_before(h20)

    rows_msg = await svc.get_unreported_telemetry_messages_by_hour(since_ts=0)
    hour_ts_set = {r["hour_ts"] for r in rows_msg}
    assert h10 not in hour_ts_set
    assert h20 in hour_ts_set
    assert h30 in hour_ts_set

    rows_llm = await svc.get_unreported_telemetry_llm_usage_by_hour(since_ts=0)
    assert len(rows_llm) == 1
    assert rows_llm[0]["hour_ts"] == h20
