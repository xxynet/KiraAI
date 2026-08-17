from types import SimpleNamespace

import pytest

pytest.importorskip("psutil", reason="core.telemetry imports core.utils.system_info")

from core.telemetry.client import TelemetryClient  # noqa: E402
from core.telemetry.models import TelemetryEventType  # noqa: E402


class FakeDatabase:
    """Minimal telemetry store: rows stay unreported until marked by id."""

    def __init__(self):
        self.message_rows = [
            {"hour_ts": 36000, "platform": "QQ", "id": "m1"},
            {"hour_ts": 36000, "platform": "Telegram", "id": "m2"},
        ]
        self.llm_rows = [
            {
                "hour_ts": 36000, "id": "l1", "model": "gpt-4o", "success": True,
                "input_tokens": 100, "output_tokens": 50, "cached_tokens": 0,
                "response_time_ms": 800,
            },
        ]
        self.marked_messages: list[str] = []
        self.marked_llm: list[str] = []

    async def get_unreported_telemetry_message_rows(self, since_ts):
        return [row for row in self.message_rows if row["id"] not in self.marked_messages]

    async def get_unreported_telemetry_llm_usage_rows(self, since_ts):
        return [row for row in self.llm_rows if row["id"] not in self.marked_llm]

    async def mark_telemetry_messages_by_ids(self, ids):
        self.marked_messages.extend(ids)

    async def mark_telemetry_llm_by_ids(self, ids):
        self.marked_llm.extend(ids)

    async def delete_telemetry_records_before(self, cutoff_ts):
        return None


def _client(db: FakeDatabase) -> TelemetryClient:
    config = SimpleNamespace(get_config=lambda *_args, **_kwargs: {})
    client = TelemetryClient(db, config)
    client.enabled = True
    client.client_uuid = "test-uuid"
    client.secret_key = "test-secret"
    return client


def _drain(client: TelemetryClient) -> list:
    events = []
    while not client._send_queue.empty():
        events.append(client._send_queue.get_nowait())
    return events


@pytest.mark.anyio
async def test_second_report_does_not_requeue_inflight_rows():
    db = FakeDatabase()
    client = _client(db)

    await client._report_stats()
    first = _drain(client)

    await client._report_stats()
    second = _drain(client)

    assert {event.event_type for event in first} == {
        TelemetryEventType.MESSAGE_STATS, TelemetryEventType.LLM_USAGE,
    }
    assert second == []


@pytest.mark.anyio
async def test_successful_send_marks_rows_and_releases_them():
    db = FakeDatabase()
    client = _client(db)

    await client._report_stats()
    for event in _drain(client):
        await event._on_success()

    assert sorted(db.marked_messages) == ["m1", "m2"]
    assert db.marked_llm == ["l1"]
    assert client._inflight_message_ids == set()
    assert client._inflight_llm_ids == set()

    await client._report_stats()
    assert _drain(client) == []


@pytest.mark.anyio
async def test_failed_send_lets_rows_be_retried():
    db = FakeDatabase()
    client = _client(db)

    await client._report_stats()
    for event in _drain(client):
        await event._on_failure()

    assert db.marked_messages == []
    assert client._inflight_message_ids == set()

    await client._report_stats()
    retried = _drain(client)

    assert {event.event_type for event in retried} == {
        TelemetryEventType.MESSAGE_STATS, TelemetryEventType.LLM_USAGE,
    }
    message_event = next(
        e for e in retried if e.event_type == TelemetryEventType.MESSAGE_STATS
    )
    assert message_event.data["total_messages"] == 2


@pytest.mark.anyio
async def test_report_only_counts_rows_it_queues():
    db = FakeDatabase()
    client = _client(db)

    await client._report_stats()
    message_event = next(
        e for e in _drain(client) if e.event_type == TelemetryEventType.MESSAGE_STATS
    )
    await message_event._on_success()

    # A row inserted after the first aggregation must still be reported on its own.
    db.message_rows.append({"hour_ts": 36000, "platform": "QQ", "id": "m3"})

    await client._report_stats()
    followup = next(
        e for e in _drain(client) if e.event_type == TelemetryEventType.MESSAGE_STATS
    )

    assert followup.data["total_messages"] == 1
