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
