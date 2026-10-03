"""Storage for persona selfie reference images."""

import os
import re
import tempfile
import warnings
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from core.utils.path_utils import get_data_path, is_within_directory

REFERENCE_IMAGE_DIRECTORY = "selfie_refs"
MAX_REFERENCE_IMAGE_BYTES = 10 * 1024 * 1024
_IMAGE_FORMATS = {
    ".png": "PNG", ".jpg": "JPEG", ".jpeg": "JPEG",
    ".webp": "WEBP", ".gif": "GIF",
}


def _image_directory(persona_id: str) -> Path:
    if (not persona_id or re.search(r'[\\/:*?"<>|\x00-\x1f]', persona_id)
            or persona_id.endswith((".", " "))
            or persona_id in {".", ".."}
            or re.fullmatch(r"CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9]", persona_id.split(".", 1)[0], re.I)):
        raise ValueError("Invalid persona ID for reference image storage")
    data_dir = get_data_path().resolve()
    directory = data_dir / REFERENCE_IMAGE_DIRECTORY
    if not is_within_directory(data_dir, directory):
        raise ValueError("Invalid reference image directory")
    return directory


def get_reference_image_path(persona_id: str, stored_path: str | None, *, require_exists: bool = True) -> Path | None:
    """Resolve a database-recorded path without scanning the image directory."""
    if not stored_path:
        return None
    relative_path = Path(stored_path)
    if (relative_path.parent != Path(REFERENCE_IMAGE_DIRECTORY)
            or relative_path.stem != persona_id
            or relative_path.suffix.lower() not in _IMAGE_FORMATS):
        raise ValueError("Invalid reference image path")
    directory = _image_directory(persona_id)
    path = directory / relative_path.name
    if path.is_symlink() or not is_within_directory(directory, path):
        raise ValueError("Invalid reference image path")
    if require_exists and not path.is_file():
        return None
    return path


def save_reference_image(persona_id: str, file_bytes: bytes, filename: str) -> Path:
    directory = _image_directory(persona_id)
    extension = Path(filename).suffix
    expected_format = _IMAGE_FORMATS.get(extension.lower())
    if expected_format is None:
        raise ValueError("Supported reference image formats: PNG, JPEG, WebP, GIF")
    if not file_bytes or len(file_bytes) > MAX_REFERENCE_IMAGE_BYTES:
        raise ValueError("Reference image must be nonempty and at most 10 MB")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(file_bytes)) as image:
                if image.format != expected_format:
                    raise ValueError("Image content does not match its extension")
                image.verify()
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as exc:
        raise ValueError("Invalid reference image") from exc

    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / f"{persona_id}{extension}"
    if destination.is_symlink() or not is_within_directory(directory, destination):
        raise ValueError("Invalid reference image path")
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(file_bytes)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


def delete_reference_image(persona_id: str, stored_path: str | None) -> None:
    path = get_reference_image_path(persona_id, stored_path, require_exists=False)
    if path is not None:
        path.unlink(missing_ok=True)
