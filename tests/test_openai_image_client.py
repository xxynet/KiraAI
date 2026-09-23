import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core.chat.message_elements import Image
from core.provider.src.openai.model_clients import OpenAIImageClient


PNG_BYTES = b"\x89PNG\r\n\x1a\n"
PNG_BASE64 = base64.b64encode(PNG_BYTES).decode()


def _client():
    return object.__new__(OpenAIImageClient)


def _configured_client(images_api):
    client = _client()
    client.model = SimpleNamespace(
        model_id="gpt-image-1",
        model_config={"endpoint": "v1/image", "size": "1024x1024"},
    )
    client._build_client = lambda: SimpleNamespace(images=images_api)
    return client


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
async def test_v1_image_text_to_image_accepts_base64_response():
    generate = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(url=None, b64_json=PNG_BASE64)]
        )
    )
    client = _configured_client(SimpleNamespace(generate=generate))

    result = await client.text_to_image("draw a blue square")

    assert result.image == PNG_BASE64
    assert result.image_type == "base64"
    call = generate.await_args.kwargs
    assert call == {
        "model": "gpt-image-1",
        "prompt": "draw a blue square",
        "size": "1024x1024",
    }


@pytest.mark.asyncio
async def test_v1_image_uses_edits_and_accepts_base64_response():
    edit = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(url=None, b64_json=PNG_BASE64)]
        )
    )
    client = _configured_client(SimpleNamespace(edit=edit))

    result = await client.image_to_image(
        "make it blue",
        Image(image=f"data:image/png;base64,{PNG_BASE64}"),
    )

    assert result.image == PNG_BASE64
    assert result.image_type == "base64"
    edit.assert_awaited_once()
    call = edit.await_args.kwargs
    assert call["model"] == "gpt-image-1"
    assert call["prompt"] == "make it blue"
    assert call["size"] == "1024x1024"
    assert "response_format" not in call
    assert "extra_body" not in call
    assert call["image"] == ("image_0.png", PNG_BYTES, "image/png")


@pytest.mark.asyncio
async def test_v1_image_edit_accepts_url_response_and_multiple_images():
    edit = AsyncMock(
        return_value=SimpleNamespace(
            data=[
                SimpleNamespace(
                    url="https://example.com/edited.webp",
                    b64_json=None,
                )
            ]
        )
    )
    client = _configured_client(SimpleNamespace(edit=edit))
    jpeg_base64 = base64.b64encode(b"jpeg").decode()
    webp_base64 = base64.b64encode(b"webp").decode()

    result = await client.image_to_image(
        "combine them",
        [
            Image(image=f"data:image/jpeg;base64,{jpeg_base64}"),
            Image(image=f"data:image/webp;base64,{webp_base64}"),
        ],
    )

    assert result.image == "https://example.com/edited.webp"
    image_files = edit.await_args.kwargs["image"]
    assert image_files == [
        ("image_0.jpg", b"jpeg", "image/jpeg"),
        ("image_1.webp", b"webp", "image/webp"),
    ]


@pytest.mark.parametrize(
    "data_url, message",
    [
        ("data:image/png,cG5n", "must contain Base64"),
        ("data:image/png;base64,%%%", "invalid Base64"),
        ("data:image/png;base64,", "empty image data"),
        ("data:image/gif;base64,R0lG", "Unsupported image MIME type"),
    ],
)
def test_image_file_from_data_url_rejects_invalid_input(data_url, message):
    with pytest.raises(ValueError, match=message):
        _client()._image_file_from_data_url(data_url, 0)


@pytest.mark.parametrize("data", [[], [SimpleNamespace(url=None, b64_json=None)]])
def test_image_response_rejects_missing_image_data(data):
    with pytest.raises(ValueError, match="returned"):
        _client()._image_from_response(SimpleNamespace(data=data), "Image edit")


@pytest.mark.asyncio
async def test_image_edit_requires_input_image():
    edit = AsyncMock()
    client = _configured_client(SimpleNamespace(edit=edit))

    with pytest.raises(ValueError, match="at least one input image"):
        await client.image_to_image("edit it", [])

    edit.assert_not_awaited()
