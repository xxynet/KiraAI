from PIL import Image as PILImage
import pytest

from core.chat.message_elements import Image
from core.utils import image_compression


@pytest.mark.asyncio
async def test_compression_scales_large_image_and_preserves_alpha(tmp_path, monkeypatch):
    monkeypatch.setattr(image_compression, "get_data_path", lambda: tmp_path)
    source_path = tmp_path / "source.png"
    PILImage.new("RGBA", (2000, 1000), (255, 0, 0, 128)).save(source_path)
    image = Image(str(source_path))

    changed = await image_compression.compress_image_element(
        image,
        {"enabled": True, "max_size": 500, "quality": 80, "min_file_size_mb": 1},
    )

    assert changed is True
    assert image.file_type == "path"
    assert image.mime == "image/png"
    with PILImage.open(image.file) as compressed:
        assert compressed.mode == "RGBA"
        assert max(compressed.size) == 500


@pytest.mark.asyncio
async def test_compression_can_be_disabled(tmp_path):
    source_path = tmp_path / "source.jpg"
    PILImage.new("RGB", (2000, 1000), "red").save(source_path)
    image = Image(str(source_path))

    changed = await image_compression.compress_image_element(
        image,
        {"enabled": False, "max_size": 500, "quality": 80, "min_file_size_mb": 0},
    )

    assert changed is False
    assert image.file == str(source_path)


@pytest.mark.asyncio
async def test_compression_applies_exif_orientation(tmp_path, monkeypatch):
    monkeypatch.setattr(image_compression, "get_data_path", lambda: tmp_path)
    source_path = tmp_path / "rotated.jpg"
    exif = PILImage.Exif()
    exif[274] = 6
    PILImage.new("RGB", (100, 200), "red").save(source_path, exif=exif)
    image = Image(str(source_path))

    changed = await image_compression.compress_image_element(
        image,
        {"enabled": True, "max_size": 500, "quality": 80, "min_file_size_mb": 0},
    )

    assert changed is True
    with PILImage.open(image.file) as compressed:
        assert compressed.size == (200, 100)


@pytest.mark.asyncio
async def test_compression_skips_images_over_pixel_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(image_compression, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(PILImage, "MAX_IMAGE_PIXELS", 1)
    source_path = tmp_path / "large-dimensions.jpg"
    PILImage.new("RGB", (2, 2), "red").save(source_path)
    image = Image(str(source_path))

    changed = await image_compression.compress_image_element(
        image,
        {"enabled": True, "max_size": 1, "quality": 80, "min_file_size_mb": 0},
    )

    assert changed is False
    assert image.file == str(source_path)
