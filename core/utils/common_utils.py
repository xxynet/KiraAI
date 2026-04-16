from __future__ import annotations

import base64
import httpx

from typing import Union, TYPE_CHECKING

from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.chat.message_elements import Image, Sticker
    from core.provider import LLMModelClient

logger = get_logger("llm", "purple")


async def image_to_base64(image_path: str):
    """
    convert an image to base64
    :param image_path: 图片文件路径或网络URL
    :return: Base64编码的字符串
    """
    if image_path.startswith(("http://", "https://")):
        async with httpx.AsyncClient() as client:
            resp = await client.get(image_path)
            resp.raise_for_status()
            image_data = resp.content
        base64_data = base64.b64encode(image_data)
        return base64_data.decode('utf-8')
    with open(image_path, 'rb') as image_file:
        base64_data = base64.b64encode(image_file.read())
    return base64_data.decode('utf-8')


async def desc_img(client: LLMModelClient, image: Union[Image, Sticker], prompt="描述这张图片的内容，如果有文字请将其输出") -> str:
    """
    describe an image
    :param client: LLMModelClient
    :param image: url or base64
    :param prompt: prompt of VLM
    :return: image description
    """
    from core.provider import LLMRequest
    try:

        image_url = await image.to_data_url()

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": image_url,
                        "detail": "high"
                    }
                },
                {
                    "type": "text",
                    "text": prompt
                }
            ]
        }]

        request = LLMRequest(messages=messages)
        vlm_model = client
        provider_name = vlm_model.model.provider_name
        model_id = vlm_model.model.model_id
        logger.info(f"Describing image using {model_id} ({provider_name})")
        resp = await vlm_model.chat(request)
        return resp.text_response
    except Exception as e:
        logger.error(f"error occurred when describing image: {str(e)}")
        return ""
