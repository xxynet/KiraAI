from asyncio import Semaphore
from typing import Optional
import requests
import copy
import json
import time
import base64

from core.logging_manager import get_logger
from .config import KiraConfig
from .provider import LLMRequest, LLMResponse
from .provider import ProviderManager, ImageResult

logger = get_logger("llm", "purple")


class LLMClient:
    def __init__(self, kira_config: KiraConfig, provider_mgr: ProviderManager):
        self.kira_config = kira_config

        # TODO remove it and get model when needed
        self.fast_llm_model = provider_mgr.get_default_model("default_fast_llm")

        self.provider_mgr = provider_mgr

        self.tools_definitions = []
        self.tools_functions = {}

        self.llm_semaphore = Semaphore(2)

    def register_tool(self, name, description, parameters, func):
        """Register a tool"""
        self.tools_definitions.append({
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters
            }
        })
        self.tools_functions[name] = func

    @staticmethod
    def image_to_base64(image_url):
        """
        将url图片转换为Base64编码
        :param image_url: 图片文件路径
        :return: Base64编码的字符串
        """
        resp = requests.get(image_url)
        image_data = resp.content
        base64_data = base64.b64encode(image_data)
        return base64_data.decode('utf-8')

    async def chat(self, messages) -> LLMResponse:
        """与LLM交互

        Args:
            messages: 消息列表

        Returns:
            LLMResponse
        """
        async with self.llm_semaphore:
            request = LLMRequest(messages)
            llm_model = self.provider_mgr.get_default_model("default_llm")
            llm_provider = self.provider_mgr.get_provider(llm_model.provider_id)
            response = await llm_provider.chat(llm_model, request)
            return response

    async def agent_run(self, user_message) -> LLMResponse:

        async with self.llm_semaphore:
            request = LLMRequest(user_message, tools=self.tools_definitions, tool_funcs=self.tools_functions)
            llm_model = self.provider_mgr.get_default_model("default_llm")
            llm_provider = self.provider_mgr.get_provider(llm_model.provider_id)
            provider_name = self.kira_config.get_config(f"providers.{llm_model.provider_id}.name")
            logger.info(f"Running agent using {llm_model.model_id} ({provider_name})")
            resp = await llm_provider.chat(llm_model, request)
            logger.debug(resp)
            if resp:
                logger.info(f"Time consumed: {resp.time_consumed}s, Input tokens: {resp.input_tokens}, output tokens: {resp.output_tokens}")
            return resp

    async def text_to_speech(self, text: str):
        tts_model = self.provider_mgr.get_default_model("default_tts")
        tts = self.provider_mgr.get_provider(tts_model.provider_id)
        provider_name = tts_model.provider_name
        logger.info(f"Generating speech using {tts_model.model_id} ({provider_name})")
        bs64 = await tts.text_to_speech(tts_model, text)
        if bs64:
            logger.info(f"Generated speech from text {text}")
        return bs64

    async def speech_to_text(self, bs64):
        stt_model = self.provider_mgr.get_default_model("default_stt")
        stt = self.provider_mgr.get_provider(stt_model.provider_id)
        provider_name = stt_model.provider_name
        logger.info(f"Recognizing text using {stt_model.model_id} ({provider_name})")
        text = await stt.speech_to_text(stt_model, bs64)
        logger.info(f"Recognized text: {text}")
        return text

    async def desc_img(self, image, prompt="描述这张图片的内容，如果有文字请将其输出", is_base64=False):
        """
        describe an image
        :param image: url or base64
        :param prompt: prompt of VLM
        :param is_base64: defaults to False
        :return: image description
        """
        try:
            if is_base64:
                b64_data = image
            else:
                b64_data = self.image_to_base64(image)

            messages = [{
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/TYPE;base64,{b64_data}",
                            "detail": "high"
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]

            request = LLMRequest(messages)
            vlm_model = self.provider_mgr.get_default_model("default_vlm")
            vlm_provider = self.provider_mgr.get_provider(vlm_model.provider_id)
            provider_name = vlm_model.provider_name
            logger.info(f"Describing image using {vlm_model.model_id} ({provider_name})")
            resp = await vlm_provider.chat(vlm_model, request)
            return resp.text_response
        except Exception as e:
            logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    async def generate_img(self, prompt) -> ImageResult:
        image_model = self.provider_mgr.get_default_model("default_image")
        img_provider = self.provider_mgr.get_provider(image_model.provider_id)
        provider_name = image_model.provider_name
        logger.info(f"Generating image using {image_model.model_id} ({provider_name})")
        img_res = await img_provider.text_to_image(image_model, prompt)
        if not img_res:
            logger.error(f"error occurred when generating image")
        return img_res

    async def image_to_image(self, prompt, url: Optional[str] = None, bs64: Optional[str] = None):
        image_model = self.provider_mgr.get_default_model("default_image")
        img_provider = self.provider_mgr.get_provider(image_model.provider_id)
        provider_name = image_model.provider_name
        logger.info(f"Generating image using {image_model.model_id} ({provider_name}) with a reference image")
        img_res = await img_provider.image_to_image(image_model, prompt, url=url, base64=bs64)
        if not img_res:
            logger.error(f"error occurred when generating image")
        return img_res
