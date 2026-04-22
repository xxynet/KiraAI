from typing import Any, Optional
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.engine import Result

Base = declarative_base()


class DatabaseManager:
    """Asynchronous database access manager powered by SQLAlchemy.

    This class is database-agnostic. Switching the backend only requires
    changing the ``database_url`` and installing the appropriate driver.
    """

    def __init__(
        self,
        database_url: str,
        *,
        echo: bool = False,
        pool_size: Optional[int] = None,
        max_overflow: Optional[int] = None,
        connect_args: Optional[dict[str, Any]] = None,
        **engine_kwargs,
    ):
        self.database_url = database_url
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.connect_args = connect_args or {}
        self.engine_kwargs = engine_kwargs

        self.engine = None
        self.session_maker = None

    async def init(self) -> None:
        """Initialize the async engine and session factory."""
        kwargs: dict[str, Any] = {
            "echo": self.echo,
            **self.engine_kwargs,
        }
        if self.pool_size is not None:
            kwargs["pool_size"] = self.pool_size
        if self.max_overflow is not None:
            kwargs["max_overflow"] = self.max_overflow
        if self.connect_args:
            kwargs["connect_args"] = self.connect_args

        self.engine = create_async_engine(self.database_url, **kwargs)
        self.session_maker = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
            autocommit=False,
        )

    async def dispose(self) -> None:
        """Dispose the engine and release all connections."""
        if self.engine is not None:
            await self.engine.dispose()
            self.engine = None
            self.session_maker = None

    @asynccontextmanager
    async def get_session(self):
        """Yield a new async session."""
        if self.session_maker is None:
            raise RuntimeError("DatabaseManager is not initialized. Call init() first.")
        async with self.session_maker() as session:
            try:
                yield session
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self):
        """Yield a session wrapped in a transaction (auto-commit / rollback)."""
        async with self.get_session() as session:
            async with session.begin():
                yield session

    async def execute(
        self,
        statement,
        params: Optional[dict[str, Any]] = None,
    ) -> Result[Any]:
        """Execute a statement and return the result object."""
        async with self.get_session() as session:
            result = await session.execute(statement, params or {})
            return result

    async def fetch_one(
        self,
        statement,
        params: Optional[dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Execute a statement and return a single mapping or None."""
        async with self.get_session() as session:
            result = await session.execute(statement, params or {})
            row = result.mappings().one_or_none()
            return row

    async def fetch_all(
        self,
        statement,
        params: Optional[dict[str, Any]] = None,
    ) -> list[Any]:
        """Execute a statement and return all mappings."""
        async with self.get_session() as session:
            result = await session.execute(statement, params or {})
            rows = result.mappings().all()
            return list(rows)

    async def create_all(self) -> None:
        """Create all tables defined by ``Base.metadata`` if they do not exist."""
        if self.engine is None:
            raise RuntimeError("DatabaseManager is not initialized. Call init() first.")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
