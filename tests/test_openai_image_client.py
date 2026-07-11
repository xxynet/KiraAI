from types import SimpleNamespace

from core.provider.src.openai.model_clients import OpenAIImageClient


def _client():
    return object.__new__(OpenAIImageClient)


def test_extracts_markdown_data_url_from_chat_content():
    data_url = "data:image/png;base64,iVBORw0KGgoAAAA"
    message = SimpleNamespace(content=f"![image]({data_url})")

    image = _client()._extract_image_from_message(message)

    assert image is not None
    assert image.image == data_url
    assert image.image_type == "data_url"


def test_extracts_wrapped_markdown_data_url_from_chat_content():
    message = SimpleNamespace(
        content="![image](data:image/png;base64,iVBORw0KGgo\nAAAA)"
    )

    image = _client()._extract_image_from_message(message)

    assert image is not None
    assert image.image == "data:image/png;base64,iVBORw0KGgoAAAA"
    assert image.image_type == "data_url"


def test_extracts_markdown_https_url_from_chat_content():
    message = SimpleNamespace(content="![image](https://example.com/image.png)")

    image = _client()._extract_image_from_message(message)

    assert image is not None
    assert image.image == "https://example.com/image.png"
    assert image.image_type == "url"
