import asyncio

import pytest
from sqlalchemy import Column, Integer, String, select, text

from core.db.db_mgr import DatabaseManager, Base


class SampleItem(Base):
    __tablename__ = "sample_items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)


@pytest.fixture
async def db():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await manager.init()
    yield manager
    await manager.dispose()


@pytest.mark.anyio
async def test_init_and_dispose():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    assert manager.engine is None
    await manager.init()
    assert manager.engine is not None
    assert manager.session_maker is not None
    await manager.dispose()
    assert manager.engine is None
    assert manager.session_maker is None


@pytest.mark.anyio
async def test_get_session(db):
    async with db.get_session() as session:
        result = await session.execute(text("SELECT 1"))
        value = result.scalar()
        assert value == 1


@pytest.mark.anyio
async def test_transaction_commit(db):
    await db.create_all()
    async with db.transaction() as session:
        session.add(SampleItem(name="committed"))

    async with db.get_session() as session:
        result = await session.execute(select(SampleItem).where(SampleItem.name == "committed"))
        item = result.scalar_one_or_none()
        assert item is not None
        assert item.name == "committed"


@pytest.mark.anyio
async def test_transaction_rollback(db):
    await db.create_all()
    try:
        async with db.transaction() as session:
            session.add(SampleItem(name="rollback"))
            raise RuntimeError("force rollback")
    except RuntimeError:
        pass

    async with db.get_session() as session:
        result = await session.execute(select(SampleItem).where(SampleItem.name == "rollback"))
        item = result.scalar_one_or_none()
        assert item is None


@pytest.mark.anyio
async def test_execute_fetch_one_fetch_all(db):
    await db.create_all()
    async with db.transaction() as session:
        session.add(SampleItem(name="alpha"))
        session.add(SampleItem(name="beta"))

    stmt = select(SampleItem.id, SampleItem.name).where(SampleItem.name == "alpha")
    row = await db.fetch_one(stmt)
    assert row is not None
    assert row["name"] == "alpha"

    stmt_all = select(SampleItem.id, SampleItem.name).order_by(SampleItem.id)
    rows = await db.fetch_all(stmt_all)
    assert len(rows) == 2
    assert rows[0]["name"] == "alpha"
    assert rows[1]["name"] == "beta"


@pytest.mark.anyio
async def test_create_all(db):
    await db.create_all()
    async with db.get_session() as session:
        result = await session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name='sample_items'")
        )
        assert result.scalar_one_or_none() == "sample_items"


@pytest.mark.anyio
async def test_not_initialized_errors():
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")

    with pytest.raises(RuntimeError, match="not initialized"):
        async with manager.get_session() as session:
            pass

    with pytest.raises(RuntimeError, match="not initialized"):
        await manager.create_all()


@pytest.mark.anyio
async def test_create_all_includes_telemetry_tables(db):
    await db.create_all()
    async with db.get_session() as session:
        for table_name in ("telemetry_messages", "telemetry_llm_usage"):
            result = await session.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name=:name"),
                {"name": table_name},
            )
            assert result.scalar_one_or_none() == table_name


@pytest.mark.anyio
async def test_sqlite_file_connection_settings(tmp_path):
    manager = DatabaseManager(
        f"sqlite+aiosqlite:///{(tmp_path / 'settings.db').as_posix()}",
        connect_args={"timeout": 0.1},
    )
    await manager.init()
    try:
        # Hold both connections so the pool must open a second physical connection.
        async with manager.engine.connect() as first, manager.engine.connect() as second:
            for connection in (first, second):
                assert (await connection.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"
                assert (await connection.execute(text("PRAGMA busy_timeout"))).scalar_one() == 10000
        await manager.engine.dispose()
        async with manager.engine.connect() as replacement:
            assert (await replacement.execute(text("PRAGMA journal_mode"))).scalar_one() == "wal"
            assert (await replacement.execute(text("PRAGMA busy_timeout"))).scalar_one() == 10000
    finally:
        await manager.dispose()


@pytest.mark.anyio
async def test_sqlite_writer_waits_while_readers_continue(tmp_path):
    manager = DatabaseManager(f"sqlite+aiosqlite:///{(tmp_path / 'concurrent.db').as_posix()}")
    await manager.init()
    pending_write = None
    write_started = asyncio.Event()

    async def insert_second(connection):
        write_started.set()
        await connection.execute(text("INSERT INTO write_probe (id) VALUES (2)"))
        await connection.commit()

    try:
        async with manager.engine.begin() as connection:
            await connection.execute(text("CREATE TABLE write_probe (id INTEGER PRIMARY KEY)"))
        async with (
            manager.engine.connect() as first,
            manager.engine.connect() as second,
            manager.engine.connect() as reader,
        ):
            try:
                await first.execute(text("INSERT INTO write_probe (id) VALUES (1)"))
                pending_write = asyncio.create_task(insert_second(second))
                await write_started.wait()
                await asyncio.sleep(0.1)
                assert not pending_write.done()
                # WAL readers see committed state while another connection holds a write lock.
                assert await asyncio.wait_for(
                    reader.scalar(text("SELECT COUNT(*) FROM write_probe")), timeout=2,
                ) == 0
                await reader.rollback()
                await first.commit()
                await asyncio.wait_for(pending_write, timeout=3)
                assert await reader.scalar(text("SELECT COUNT(*) FROM write_probe")) == 2
            finally:
                await first.rollback()
                if pending_write is not None:
                    await asyncio.gather(pending_write, return_exceptions=True)
    finally:
        await manager.dispose()
