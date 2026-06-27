import json
import os

from sqlalchemy import select, text

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path

from .service import DatabaseService
from .models import ImageDescCache

logger = get_logger("db_migration", "cyan")


async def migrate_stickers(db_service: DatabaseService) -> None:
    """Migrate sticker data from JSON file to database if table is empty."""
    stickers = await db_service.list_stickers()
    if stickers:
        logger.info("Sticker table is not empty, skipping migration")
        return

    sticker_path = get_data_path() / "config" / "sticker.json"
    if not sticker_path.exists() or sticker_path.stat().st_size == 0:
        logger.info("Sticker JSON file not found or empty, skipping migration")
        return

    try:
        with open(sticker_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read sticker JSON: {e}")
        return

    count = 0
    for sticker_id, entry in data.items():
        desc = entry.get("desc", "")
        path = entry.get("path", "")
        if desc and path:
            await db_service.add_sticker(sticker_id, desc, path)
            count += 1

    logger.info(f"Migrated {count} stickers to database")


async def migrate_image_desc_cache(db_service: DatabaseService) -> None:
    """Migrate image description cache from JSON file to database if table is empty."""
    rows = await db_service.db.fetch_all(select(ImageDescCache).limit(1))
    if rows:
        logger.info("ImageDescCache table is not empty, skipping migration")
        return

    cache_path = get_data_path() / "image_desc_cache.json"
    if not cache_path.exists() or cache_path.stat().st_size == 0:
        logger.info("Image desc cache JSON file not found or empty, skipping migration")
        return

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read image desc cache JSON: {e}")
        return

    count = 0
    for md5, entry in data.items():
        description = entry.get("description", "")
        count_val = entry.get("count", 1)
        last_seen = entry.get("last_seen", 0)
        if description:
            await db_service.add_image_desc_cache(md5, description, count_val, last_seen)
            count += 1

    logger.info(f"Migrated {count} image desc cache entries to database")


async def migrate_persona(db_service: DatabaseService) -> None:
    """Migrate persona data from text file to database if table is empty."""
    personas = await db_service.list_personas()
    if personas:
        logger.info("Persona table is not empty, skipping migration")
        return

    persona_path = get_data_path() / "persona.txt"
    if not persona_path.exists() or persona_path.stat().st_size == 0:
        logger.info("Persona text file not found or empty, skipping migration")
        return

    try:
        content = persona_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read persona text: {e}")
        return

    await db_service.add_persona("default", "default", content, format="text", is_active=True)
    logger.info("Migrated default persona to database")


async def migrate_persona_is_active(db_service: DatabaseService) -> None:
    """Add is_active column to personas table if it doesn't exist."""
    logger.info("Checking if is_active column needs to be added to personas table")
    try:
        # Use raw connection for DDL operations
        async with db_service.db.engine.begin() as conn:
            # Check if is_active column exists
            result = await conn.execute(
                text("PRAGMA table_info(personas)")
            )
            columns = [row.name for row in result.fetchall()]
            logger.info(f"Current persona columns: {columns}")

            if 'is_active' not in columns:
                logger.info("Adding is_active column to personas table")
                await conn.execute(
                    text("ALTER TABLE personas ADD COLUMN is_active BOOLEAN DEFAULT 0")
                )

                # Check if any persona is already active (won't be the case for new column)
                # Since this is a new column, all values default to 0
                # Set the first persona as active only if none are active
                result = await conn.execute(
                    text("SELECT COUNT(*) FROM personas WHERE is_active = 1")
                )
                if result.scalar() == 0:
                    # No active persona, set the first one as active
                    logger.info("No active persona found, setting first persona as active")
                    await conn.execute(
                        text("UPDATE personas SET is_active = 1 WHERE id = (SELECT id FROM personas ORDER BY created_at LIMIT 1)")
                    )
                else:
                    logger.info("Active persona already exists, skipping activation")

                logger.info("Successfully added is_active column to personas table")
            else:
                logger.info("is_active column already exists, skipping")
    except Exception as e:
        logger.error(f"Failed to add is_active column: {e}")
        raise


async def run_migrations(db_service: DatabaseService) -> None:
    """Run all data migrations."""
    await migrate_stickers(db_service)
    await migrate_image_desc_cache(db_service)
    await migrate_persona(db_service)
    await migrate_persona_is_active(db_service)
