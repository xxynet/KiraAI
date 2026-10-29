"""Compose business database interfaces over a shared database manager."""

import asyncio

from .db_mgr import DatabaseManager
from .mixins.image_cache import ImageCacheMixin
from .mixins.messages import MessageHistoryMixin
from .mixins.personas import PersonaMixin
from .mixins.plugin_sources import PluginSourceMixin
from .mixins.sessions import ChatSessionMixin
from .mixins.stickers import StickerMixin
from .mixins.telemetry import TelemetryMixin


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
        """Create all tables if they do not exist."""
        await self.db.create_all()
