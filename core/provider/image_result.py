from dataclasses import dataclass


@dataclass
class ImageResult:
    """image url, should be a public link"""
    url: str = None

    """base64 of the image"""
    base64: str = None

