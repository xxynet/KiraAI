from dataclasses import dataclass


@dataclass
class ImageResult:
    """image url, should be a public link"""
    url: str = None

    """base64 of the image"""
    base64: str = None

    """image, could be url, base64 or data url"""
    image: str = ""

    def to_base64(self):
        pass

    def to_data_url(self):
        pass
