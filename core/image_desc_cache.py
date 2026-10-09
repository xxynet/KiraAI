import asyncio
import time
from typing import Optional

from core.db.service import DatabaseService
from core.logging_manager import get_logger

logger = get_logger("message", "cyan")


class ImageDescCache:
    """Cache image/sticker VLM descriptions using MD5 hash backed by database."""

    def __init__(self, db_service: DatabaseService):
        self.db = db_service

    async def get(self, md5: str) -> Optional[str]:
        entry = await self.db.get_image_desc_cache(md5)
        if entry:
            await self.db.update_image_desc_cache(
                md5,
                count=entry["count"] + 1,
                last_seen=int(time.time()),
            )
            return entry["description"]
        return None

    async def set(self, md5: str, description: str):
        # Never cache an empty/failed description: an empty string would otherwise be
        # stored permanently as the caption for this md5 and served to every later hit.
        if not description:
            return
        existing = await self.db.get_image_desc_cache(md5)
        if existing:
            # Preserve the accumulated hit count that cleanup relies on; resetting it to 1
            # on every update would prevent frequently-seen entries from being retained.
            await self.db.update_image_desc_cache(
                md5,
                description=description,
                count=existing["count"],
                last_seen=int(time.time()),
            )
        else:
            await self.db.add_image_desc_cache(
                md5,
                description,
                count=1,
                last_seen=int(time.time()),
            )

    async def cleanup_task(self):
        """Background task: clean up expired image desc cache every 24 hours."""
        while True:
            try:
                deleted = await self.db.cleanup_expired_image_desc_cache()
                if deleted:
                    logger.info(f"Cleaned up {deleted} expired image desc cache entries")
                await asyncio.sleep(24 * 60 * 60)
            except asyncio.CancelledError:
                logger.info("Image desc cache cleanup task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in image desc cache cleanup: {e}")
