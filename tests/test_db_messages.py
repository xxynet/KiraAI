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
