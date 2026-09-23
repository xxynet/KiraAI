import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.chat.message_elements import Image
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


@pytest.mark.asyncio
async def test_v1_image_uses_edits_for_image_to_image():
    edit = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(url="https://example.com/edited.png")]
        )
    )
    sdk_client = SimpleNamespace(images=SimpleNamespace(edit=edit))
    client = _client()
    client.model = SimpleNamespace(
        model_id="gpt-image-1",
        model_config={"endpoint": "v1/image", "size": "1024x1024"},
    )
    client._build_client = lambda: sdk_client

    result = await client.image_to_image(
        "make it blue",
        Image(image="data:image/png;base64,cG5n"),
    )

    assert result.image == "https://example.com/edited.png"
    edit.assert_awaited_once()
    call = edit.await_args.kwargs
    assert call["model"] == "gpt-image-1"
    assert call["prompt"] == "make it blue"
    assert call["size"] == "1024x1024"
    assert call["response_format"] == "url"
    assert call["extra_body"] == {"watermark": False}
    assert call["image"][0] == "image_0.png"
    assert call["image"][1] == base64.b64decode("cG5n")
    assert call["image"][2] == "image/png"
