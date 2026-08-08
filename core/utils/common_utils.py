from __future__ import annotations

import base64
import httpx

from typing import Union, TYPE_CHECKING

from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.chat.message_elements import Image, Sticker, Record
    from core.provider import LLMModelClient, TTSModelClient, STTModelClient, ImageModelClient

logger = get_logger("llm", "purple")


DEFAULT_VLM_PROMPTS = {
    "zh": "描述这张图片的内容；如果图片中有文字，请一并输出。",
    "en": "Describe the content of this image. If it contains text, include that text in the description.",
}


def get_default_vlm_prompt(lang: str | None) -> str:
    """Return the localized fallback prompt used for VLM image descriptions."""
    normalized_lang = str(lang or "en").lower().replace("_", "-")
    language_code = normalized_lang.split("-", maxsplit=1)[0]
    return DEFAULT_VLM_PROMPTS.get(language_code, DEFAULT_VLM_PROMPTS["en"])


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


async def desc_img(
    client: LLMModelClient,
    image: Union[Image, Sticker],
    prompt: str | None = None,
    lang: str | None = None,
) -> str:
    """
    describe an image
    :param client: LLMModelClient
    :param image: url or base64
    :param prompt: prompt of VLM, uses a localized default prompt if None
    :param lang: configured language code used to select the default prompt
    :return: image description
    """
    if prompt is None:
        prompt = get_default_vlm_prompt(lang)
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


async def text_to_speech(client: TTSModelClient, text: str) -> Record:
        tts_client = client
        provider_name = tts_client.model.provider_name
        model_id = tts_client.model.model_id
        logger.info(f"Generating speech using {model_id} ({provider_name})")
        record = await tts_client.text_to_speech(text)
        if record:
            logger.info(f"Generated speech from text {text}")
        return record


async def speech_to_text(client: STTModelClient, record: Record):
    stt_client = client
    provider_name = stt_client.model.provider_name
    model_id = stt_client.model.model_id
    logger.info(f"Recognizing text using {model_id} ({provider_name})")
    text = await stt_client.speech_to_text(record)
    logger.info(f"Recognized text: {text}")
    return text


async def generate_image(client: ImageModelClient, prompt: str) -> Image:
    image_client = client
    provider_name = image_client.model.provider_name
    model_id = image_client.model.model_id
    logger.info(f"Generating image using {model_id} ({provider_name})")
    try:
        img_res = await image_client.text_to_image(prompt)
        if img_res:
            logger.info(f"Image generated with prompt: {prompt}")
            logger.debug(f"type={img_res.image_type}, len={len(img_res.image or '')}, prefix={(img_res.image or '')[:200]!r}")
        else:
            logger.error("Failed to generate image with text: result is None")
        return img_res
    except Exception as e:
        logger.error(f"Failed to generate image with text: {e}")


async def image_to_image(client: ImageModelClient, prompt: str, image: Union[Image, list[Image]]) -> Image:
    image_client = client
    provider_name = image_client.model.provider_name
    model_id = image_client.model.model_id
    logger.info(f"Generating image using {model_id} ({provider_name}) with a reference image")
    try:
        img_res = await image_client.image_to_image(prompt=prompt, image=image)
        if img_res:
            logger.info(f"Image generated (img2img): prompt: {prompt}")
            logger.debug(f"type={img_res.image_type}, len={len(img_res.image or '')}, prefix={(img_res.image or '')[:200]!r}")
        else:
            logger.error("Failed to generate image with a reference image: result is None")
        return img_res
    except Exception as e:
        logger.error(f"Failed to generate image with a reference image: {e}")
