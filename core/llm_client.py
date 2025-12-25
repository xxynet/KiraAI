from asyncio import Semaphore
from typing import Optional
import requests
import functools
import copy
import json
import time
import base64

from core.logging_manager import get_logger
from .provider import LLMRequest, LLMResponse
from .provider import ProviderManager, ImageResult

tool_logger = get_logger("tool_use", "orange")
llm_logger = get_logger("llm", "purple")


def timer(func):
    """计算函数执行时间的装饰器"""

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()  # 开始时间
        result = await func(*args, **kwargs)  # 执行函数
        end_time = time.perf_counter()  # 结束时间

        # 计算并打印执行时间
        execution_time = end_time - start_time
        print(f"函数 {func.__name__} 执行耗时: {execution_time:.4f} 秒")

        return result

    return wrapper


class LLMClient:
    def __init__(self, kira_config):
        self.kira_config = kira_config

        models_config = self.kira_config.get("models", {})

        self.main_llm = models_config.get("main_llm", {}).get("provider", "")
        self.tool_llm = models_config.get("tool_llm", {}).get("provider", "")
        self.vlm = models_config.get("vlm", {}).get("provider", "")
        self.util_model = models_config.get("util_model", {}).get("provider", "")
        self.image_provider = models_config.get("image", {}).get("provider", "")
        self.tts_provider = models_config.get("tts", {}).get("provider", "")
        self.stt_provider = models_config.get("stt", {}).get("provider", "")

        self.provider_manager = ProviderManager(self.kira_config.get("providers"))

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
            llm_provider = self.provider_manager.get_llm_provider(self.main_llm)
            response = await llm_provider.chat(request)
            return response

    @timer
    async def chat_with_tools(self, user_message, tool_system_prompt) -> LLMResponse:

        async with self.llm_semaphore:
            raw_msg = copy.deepcopy(user_message)
            raw_msg[0] = {"role": "system", "content": tool_system_prompt}
            # 第一次调用，让模型决定是否调用工具
            request = LLMRequest(raw_msg, tools=self.tools_definitions, tool_funcs=self.tools_functions)
            tool_provider = self.provider_manager.get_llm_provider(self.tool_llm)
            llm_logger.info(f"checking whether to call tools using {self.tool_llm}")
            resp1 = await tool_provider.chat(request)

            if resp1 and resp1.tool_results:
                user_message.extend(resp1.tool_results)

            request2 = LLMRequest(user_message)
            # request2 = LLMRequest(user_message, tools=self.tools_definitions, tool_choice="none")
            llm_provider = self.provider_manager.get_llm_provider(self.main_llm)
            llm_logger.info(f"generating response using {self.main_llm}")
            resp2 = await llm_provider.chat(request2)

            # make sure to let message processor to get the tool_results
            resp2.tool_results = resp1.tool_results
            return resp2

    async def text_to_speech(self, text: str):
        tts = self.provider_manager.get_tts_provider(self.tts_provider)
        bs64 = await tts.text_to_speech(text)
        return bs64

    async def speech_to_text(self, bs64):
        stt = self.provider_manager.get_stt_provider(self.stt_provider)
        text = await stt.speech_to_text(bs64)
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
            vlm_provider = self.provider_manager.get_llm_provider(self.vlm)
            resp = await vlm_provider.chat(request)
            return resp.text_response

        except Exception as e:
            llm_logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    async def generate_img(self, prompt) -> ImageResult:
        img_provider = self.provider_manager.get_image_provider(self.image_provider)
        img_res = await img_provider.text_to_image(prompt)
        if not img_res:
            llm_logger.error(f"error occurred when generating image")
        return img_res

    async def image_to_image(self, prompt, url: Optional[str] = None, bs64: Optional[str] = None):
        img_provider = self.provider_manager.get_image_provider(self.image_provider)
        img_res = await img_provider.image_to_image(prompt, url=url, base64=bs64)
        if not img_res:
            llm_logger.error(f"error occurred when generating image")
        return img_res
