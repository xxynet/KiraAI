"""Compose business database interfaces over a shared database manager."""

import asyncio

from sqlalchemy import inspect, text

from .db_mgr import DatabaseManager
from .mixins.image_cache import ImageCacheMixin
from .mixins.messages import MessageHistoryMixin
from .mixins.personas import PersonaMixin
from .mixins.plugin_sources import PluginSourceMixin
from .mixins.sessions import ChatSessionMixin
from .mixins.stickers import StickerMixin
from .mixins.telemetry import TelemetryMixin
from .models import ChatSessionRecord


class DatabaseService(
    ChatSessionMixin,
    MessageHistoryMixin,
    StickerMixin,
    ImageCacheMixin,
    PersonaMixin,
    PluginSourceMixin,
    TelemetryMixin,
):
    """High-level database service for KiraAI business operations."""

    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self._message_search_semaphore = asyncio.Semaphore(2)

    async def init_tables(self) -> None:
        """Create tables and add columns required by the current schema."""
        await self.db.create_all()
        async with self.db.engine.begin() as connection:
            columns = await connection.run_sync(
                lambda conn: {column["name"] for column in inspect(conn).get_columns("chat_sessions")}
            )
            if "kind" not in columns:
                await connection.execute(text("ALTER TABLE chat_sessions ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'im'"))
            if "parent_id" not in columns:
                await connection.execute(text("ALTER TABLE chat_sessions ADD COLUMN parent_id VARCHAR(37)"))
            for index in ChatSessionRecord.__table__.indexes:
                await connection.run_sync(lambda conn, index=index: index.create(conn, checkfirst=True))
            usage_columns = await connection.run_sync(
                lambda conn: {column["name"] for column in inspect(conn).get_columns("telemetry_llm_usage")}
            )
            if "source" not in usage_columns:
                await connection.execute(text(
                    "ALTER TABLE telemetry_llm_usage ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'main'"
                ))
