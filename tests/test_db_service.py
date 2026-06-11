import time

import pytest

from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService


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
