from __future__ import annotations

import base64
import httpx
import time

from typing import Union, TYPE_CHECKING

from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.chat.message_elements import Image, Sticker
    from core.provider import LLMModelClient

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
        image_data = await _download_image_bytes(image_path)
        base64_data = base64.b64encode(image_data)
        return base64_data.decode('utf-8')
    with open(image_path, 'rb') as image_file:
        base64_data = base64.b64encode(image_file.read())
    return base64_data.decode('utf-8')


# 代理连接失败后的直连偏好：避免死代理环境下每次下载都白等一个连接超时，
# 超过重试间隔后会重新尝试代理，代理恢复即可自动切回
_proxy_failed_at: float | None = None
_PROXY_RETRY_INTERVAL = 600.0


async def _fetch_image_bytes(image_url: str, timeout: httpx.Timeout, trust_env: bool) -> bytes:
    """按指定的代理策略下载图片，trust_env=False 表示忽略系统代理环境变量"""
    async with httpx.AsyncClient(trust_env=trust_env, timeout=timeout) as client:
        resp = await client.get(image_url)
        resp.raise_for_status()
        return resp.content


async def _download_image_bytes(image_url: str) -> bytes:
    """
    下载图片字节内容。默认走系统代理（与之前行为一致，不影响依赖代理访问外网图片的用户），
    代理连接失败时回退直连并记住该状态：之后一段时间内优先直连，避免每次都白等代理超时；
    超过 _PROXY_RETRY_INTERVAL 后重新尝试代理，代理恢复则自动切回。
    :param image_url: 图片网络URL
    :return: 图片字节内容
    """
    global _proxy_failed_at
    # connect 只约束建连（TCP+TLS）：正常路径几百毫秒内完成，3s 已是数倍余量；
    # 过长的 connect 超时只会让黑洞型代理的探测白等。下载阶段的 20s 保持不变。
    timeout = httpx.Timeout(20.0, connect=3.0)
    if _proxy_failed_at is not None and time.monotonic() - _proxy_failed_at < _PROXY_RETRY_INTERVAL:
        try:
            return await _fetch_image_bytes(image_url, timeout, trust_env=False)
        except (httpx.ConnectTimeout, httpx.ConnectError):
            pass  # 直连也不通，继续走代理尝试，由下方流程抛出最终的异常
    try:
        return await _fetch_image_bytes(image_url, timeout, trust_env=True)
    except (httpx.ConnectTimeout, httpx.ConnectError, httpx.ProxyError):
        # 系统代理不可达，记录失败时间并回退直连
        _proxy_failed_at = time.monotonic()
        return await _fetch_image_bytes(image_url, timeout, trust_env=False)


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
