import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from tests.test_db_service import svc


def message_values(**overrides):
    return {
        "session_id": "test:dm:user", "platform": "test", "direction": "incoming",
        "timestamp": 1, "chain": [{"type": "text", "text": "original"}],
        "status": "received", **overrides,
    }


@pytest.mark.anyio
async def test_database_message_dedup_and_failed_write_rollback(svc):
    identity = await svc.add_message_record(**message_values(dedup_key="same"))
    duplicate = await svc.add_message_record(**message_values(
        dedup_key="same", chain=[{"type": "text", "text": "duplicate"}],
    ))
    assert duplicate == identity
    record = await svc.get_message_record(identity)
    assert record["chain"] == [{"type": "text", "text": "original"}]
    assert "dedup_key" not in record
    with pytest.raises(IntegrityError):
        await svc.add_message_record(**message_values(session_id=None))
    assert await svc.list_message_sessions() == [
        {"session_id": "test:dm:user", "message_count": 1},
    ]
    await svc.delete_session_message_records("test:dm:user")
    assert await svc.get_message_record(identity) is None


@pytest.mark.anyio
@pytest.mark.parametrize("raise_error", [False, True])
async def test_message_chain_stream_releases_connection_on_early_exit(svc, raise_error):
    for _ in range(3):
        await svc.add_message_record(**message_values())
    connections = {"active": 0}

    def checkout(*_):
        connections["active"] += 1

    def checkin(*_):
        connections["active"] -= 1

    engine = svc.db.engine.sync_engine
    event.listen(engine, "checkout", checkout)
    event.listen(engine, "checkin", checkin)
    try:
        try:
            async with svc.stream_message_chains() as chains:
                async for chain in chains:
                    assert chain == [{"type": "text", "text": "original"}]
                    if raise_error:
                        raise RuntimeError("consumer failed")
                    break
        except RuntimeError as exc:
            assert raise_error and str(exc) == "consumer failed"
        assert connections["active"] == 0
        assert len((await svc.list_message_records("test:dm:user"))["messages"]) == 3
    finally:
        event.remove(engine, "checkout", checkout)
        event.remove(engine, "checkin", checkin)


@pytest.mark.anyio
async def test_database_pruning_without_limits_preserves_records(svc):
    identity = await svc.add_message_record(**message_values())
    assert await svc.prune_message_records(
        cutoff=None, max_messages_per_session=0, protected=set(),
    ) == 0
    with pytest.raises(ValueError):
        await svc.prune_message_records(
            cutoff=None, max_messages_per_session=-1, protected=set(),
        )
    assert await svc.get_message_record(identity) is not None


@pytest.mark.anyio
@pytest.mark.parametrize("platform_id", ["123", 123])
async def test_platform_message_lookup_is_scoped_to_session_account_and_direction(svc, platform_id):
    incoming_id = await svc.add_message_record(**message_values(
        platform_message_id="123", self_id="bot",
    ))
    outgoing_id = await svc.add_message_record(**message_values(
        platform_message_id="123", self_id="bot", direction="outgoing", status="sent",
    ))
    other_bot_id = await svc.add_message_record(**message_values(
        platform_message_id="123", self_id="other-bot",
    ))
    for sid in ["test:gm:user", "other:dm:user"]:
        await svc.add_message_record(**message_values(
            session_id=sid, platform_message_id="123", self_id="bot",
        ))
    lookup = svc.get_message_record
    for bot, direction, expected in [
        ("bot", "incoming", incoming_id),
        ("bot", "outgoing", outgoing_id),
        ("other-bot", "incoming", other_bot_id),
    ]:
        record = await lookup(session_id="test:dm:user", platform_message_id=platform_id, self_id=bot, direction=direction)
        assert record["id"] == expected
        assert record["chain"] == [{"type": "text", "text": "original"}]
        assert "dedup_key" not in record
    assert (await lookup(session_id="test:dm:user", platform_message_id=platform_id, direction="outgoing"))["id"] == outgoing_id
    assert (await lookup(session_id="test:dm:user", platform_message_id=platform_id, self_id="other-bot"))["id"] == other_bot_id
    assert await lookup(session_id="missing:dm:user", platform_message_id=platform_id) is None
    assert await lookup(session_id="test:dm:user", platform_message_id="missing") is None
    assert await lookup(session_id="test:dm:user", platform_message_id=platform_id, self_id="missing") is None
    assert await lookup(session_id="test:dm:user", platform_message_id=platform_id, self_id="other-bot", direction="outgoing") is None


@pytest.mark.anyio
async def test_platform_message_lookup_returns_latest_archive_with_stable_ties(svc, monkeypatch):
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 1_000_000)
    older = await svc.add_message_record(**message_values(platform_message_id="same"))
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 2_000_000)
    recent = [
        await svc.add_message_record(**message_values(platform_message_id="same"))
        for _ in range(2)
    ]
    record = await svc.get_message_record(session_id="test:dm:user", platform_message_id="same")
    assert record["id"] == max(recent)
    assert record["id"] != older
    record["chain"][0]["text"] = "caller mutation"
    assert (await svc.get_message_record(
        session_id="test:dm:user", platform_message_id="same",
    ))["chain"][0]["text"] == "original"


@pytest.mark.anyio
async def test_platform_message_lookup_rejects_invalid_direction(svc):
    with pytest.raises(ValueError, match="direction"):
        await svc.get_message_record(
            session_id="test:dm:user", platform_message_id="123", direction="invalid",
        )


@pytest.mark.anyio
async def test_message_lookup_preserves_falsy_filter_values(svc):
    expected = await svc.add_message_record(**message_values(
        session_id="", platform_message_id="0", self_id="",
    ))
    await svc.add_message_record(**message_values(platform_message_id="different", self_id="other"))
    record = await svc.get_message_record(session_id="", platform_message_id=0, self_id="")
    assert record["id"] == expected
    assert await svc.get_message_record(session_id="test:dm:user", platform_message_id=0) is None
    with pytest.raises(ValueError, match="At least one message filter"):
        await svc.get_message_record()


@pytest.mark.anyio
async def test_batch_message_query_filters_and_paginates_all_matches(svc, monkeypatch):
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 1_000_000)
    expected = {
        await svc.add_message_record(**message_values(platform_message_id="123", self_id="bot"))
        for _ in range(5)
    }
    excluded = []
    for overrides in [
        {"session_id": "test:gm:user"},
        {"session_id": "other:dm:user"},
        {"self_id": "other-bot"},
        {"direction": "outgoing", "status": "sent"},
        {"platform_message_id": "456"},
    ]:
        excluded.append(await svc.add_message_record(**message_values(
            **{"platform_message_id": "123", "self_id": "bot", **overrides},
        )))
    filters = {
        "session_id": "test:dm:user", "platform_message_id": 123,
        "self_id": "bot", "direction": "incoming",
    }
    found = []
    page = await svc.list_message_records(**filters, limit=2)
    while True:
        assert 1 <= len(page["messages"]) <= 2
        for record in page["messages"]:
            assert record["chain"] == [{"type": "text", "text": "original"}]
            assert "dedup_key" not in record
            found.append(record["id"])
        if page["next_cursor"] is None:
            break
        assert page["next_cursor"] == page["messages"][-1]["id"]
        page = await svc.list_message_records(**filters, cursor=page["next_cursor"], limit=2)
    assert found == sorted(expected, reverse=True)
    assert len(found) == len(set(found)) == 5
    assert (await svc.get_message_record(**filters))["id"] == found[0]
    for cursor in [*excluded, "missing"]:
        with pytest.raises(ValueError, match="Invalid message cursor"):
            await svc.list_message_records(**filters, cursor=cursor)
    assert await svc.list_message_records(
        **filters, cursor=found[-1],
    ) == {"messages": [], "next_cursor": None}


@pytest.mark.anyio
async def test_batch_message_query_orders_by_archive_time_before_internal_id(svc, monkeypatch):
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 1_000_000)
    old = await svc.add_message_record(**message_values())
    monkeypatch.setattr("core.db.mixins.messages.time.time_ns", lambda: 2_000_000)
    new = await svc.add_message_record(**message_values())
    page = await svc.list_message_records("test:dm:user", limit=1)
    assert [record["id"] for record in page["messages"]] == [new]
    assert page["next_cursor"] == new
    page = await svc.list_message_records("test:dm:user", cursor=new, limit=1)
    assert [record["id"] for record in page["messages"]] == [old]
    assert page["next_cursor"] is None
