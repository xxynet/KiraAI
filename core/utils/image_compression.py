"""Image compression shared by native multimodal and VLM description flows."""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

from PIL import Image as PILImage

from core.chat.message_elements import Image, Sticker
from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path


logger = get_logger("image_compression", "purple")

DEFAULT_MAX_SIZE = 1280
DEFAULT_QUALITY = 95
DEFAULT_MIN_FILE_SIZE_MB = 1


def _get_int_option(config: dict, key: str, default: int, minimum: int) -> int:
    value = config.get(key, default)
    if not isinstance(value, int):
        return default
    return max(value, minimum)


def _compression_options(config: dict | None) -> tuple[bool, int, int, int]:
    options = config if isinstance(config, dict) else {}
    enabled = options.get("enabled", True)
    if not isinstance(enabled, bool):
        enabled = True
    max_size = _get_int_option(options, "max_size", DEFAULT_MAX_SIZE, 1)
    quality = min(_get_int_option(options, "quality", DEFAULT_QUALITY, 1), 100)
    min_file_size_mb = _get_int_option(
        options, "min_file_size_mb", DEFAULT_MIN_FILE_SIZE_MB, 0
    )
    return enabled, max_size, quality, min_file_size_mb * 1024 * 1024


def _compress_image_sync(
    source_path: Path,
    max_size: int,
    quality: int,
    min_file_size_bytes: int,
) -> tuple[Path, str] | None:
    """Create a compressed temporary image when the source exceeds a limit."""
    try:
        source_size = source_path.stat().st_size
        with PILImage.open(source_path) as opened_image:
            if (
                getattr(opened_image, "is_animated", False)
                or getattr(opened_image, "n_frames", 1) > 1
            ):
                return None
            if source_size < min_file_size_bytes and max(opened_image.size) <= max_size:
                return None

            has_alpha = opened_image.mode in {"RGBA", "LA"} or (
                opened_image.mode == "P" and "transparency" in opened_image.info
            )
            output_format = "PNG" if has_alpha else "JPEG"
            output_suffix = ".png" if has_alpha else ".jpg"
            output_mime = "image/png" if has_alpha else "image/jpeg"
            image = opened_image.convert("RGBA" if has_alpha else "RGB")
            try:
                image.thumbnail((max_size, max_size), PILImage.Resampling.LANCZOS)
                output_dir = get_data_path() / "temp"
                output_dir.mkdir(parents=True, exist_ok=True)
                output_path = output_dir / f"compressed_{uuid.uuid4().hex}{output_suffix}"
                save_kwargs: dict[str, int | bool] = {"optimize": True}
                if output_format == "JPEG":
                    save_kwargs["quality"] = quality
                image.save(output_path, output_format, **save_kwargs)
                return output_path, output_mime
            finally:
                image.close()
    except Exception as exc:
        logger.warning(f"Failed to compress image {source_path.name}: {exc}")
        return None


async def compress_image_element(
    media: Image | Sticker,
    config: dict | None,
) -> bool:
    """Replace an image element with a bounded temporary image when needed."""
    enabled, max_size, quality, min_file_size_bytes = _compression_options(config)
    if not enabled:
        return False

    try:
        source_path = Path(await media.to_path())
    except Exception as exc:
        logger.warning(f"Failed to materialize image for compression: {exc}")
        return False
    compressed = await asyncio.to_thread(
        _compress_image_sync,
        source_path,
        max_size,
        quality,
        min_file_size_bytes,
    )
    if compressed is None:
        return False

    output_path, output_mime = compressed
    media.file = str(output_path)
    media._temp_path = str(output_path)
    media.file_type = "path"
    media.mime = output_mime
    media.md5 = None
    if isinstance(media, Image):
        media.image = media.file
        media.image_type = "path"
    return True
