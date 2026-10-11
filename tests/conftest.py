import pytest


@pytest.fixture(params=["asyncio"])
def anyio_backend(request):
    return request.param


@pytest.fixture
async def session_db(tmp_path):
    from core.db.db_mgr import DatabaseManager
    from core.db.service import DatabaseService

    database = DatabaseManager(f"sqlite+aiosqlite:///{(tmp_path / 'session_store.db').as_posix()}")
    await database.init()
    service = DatabaseService(database)
    await service.init_tables()
    try:
        yield service
    finally:
        await database.dispose()
