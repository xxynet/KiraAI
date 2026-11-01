"""Valid in-memory image samples for media persistence and provider tests."""

import base64
from io import BytesIO

from PIL import Image


def image_bytes(image_format: str = "PNG", *, animated: bool = False) -> bytes:
    with BytesIO() as output, Image.new("RGB", (4, 4), "red") as first:
        if animated:
            with Image.new("RGB", (4, 4), "blue") as second:
                first.save(output, format=image_format, save_all=True, append_images=[second], duration=100)
        else:
            first.save(output, format=image_format)
        return output.getvalue()


PNG_BYTES = image_bytes()
PNG_DATA_URL = "data:image/png;base64," + base64.b64encode(PNG_BYTES).decode("ascii")
