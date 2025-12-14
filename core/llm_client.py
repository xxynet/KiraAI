from openai import OpenAI, AsyncOpenAI
from asyncio import Semaphore
import requests
import functools
import copy
import json
import time
import base64

from core.logging_manager import get_logger
from core.config_loader import global_config
from .provider import LLMRequest, LLMResponse
from .provider import ProviderManager

tool_logger = get_logger("tool_use", "orange")
llm_logger = get_logger("llm", "purple")

models_config = global_config.get("models", {})
main_llm = models_config.get("main_llm", {}).get("provider", "")
tool_llm = models_config.get("tool_llm", {}).get("provider", "")
vlm = models_config.get("vlm", {}).get("provider", "")
util_model = models_config.get("util_model", {}).get("provider", "")
image_provider = models_config.get("image", {}).get("provider", "")
tts_provider = models_config.get("tts", {}).get("provider", "")
stt_provider = models_config.get("stt", {}).get("provider", "")


provider_manager = ProviderManager(global_config.get("providers"))


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
    def __init__(self):

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

    async def chat(self, messages, provider=main_llm) -> LLMResponse:
        """与LLM交互

        Args:
            messages: 消息列表
            provider: 使用的LLM provider

        Returns:
            LLMResponse
        """
        async with self.llm_semaphore:
            request = LLMRequest(messages)
            llm_provider = provider_manager.get_llm_provider(provider)
            response = await llm_provider.chat(request)
            return response

    @timer
    async def chat_with_tools(self, user_message, tool_system_prompt) -> LLMResponse:

        async with self.llm_semaphore:
            raw_msg = copy.deepcopy(user_message)
            raw_msg[0] = {"role": "system", "content": tool_system_prompt}
            # 第一次调用，让模型决定是否调用工具
            request = LLMRequest(raw_msg, tools=self.tools_definitions, tool_funcs=self.tools_functions)
            tool_provider = provider_manager.get_llm_provider(tool_llm)
            llm_logger.info(f"checking whether to call tools using {tool_llm}")
            resp1 = await tool_provider.chat(request)

            if resp1.tool_results:
                user_message.extend(resp1.tool_results)

            request2 = LLMRequest(user_message)
            llm_provider = provider_manager.get_llm_provider(main_llm)
            llm_logger.info(f"generating response using {main_llm}")
            resp2 = await llm_provider.chat(request2)
            return resp2

    async def text_to_speech(self, text: str):
        tts = provider_manager.get_tts_provider(tts_provider)
        bs64 = await tts.text_to_speech(text)
        return bs64

    async def speech_to_text(self, bs64):
        stt = provider_manager.get_stt_provider(stt_provider)
        text = await stt.speech_to_text(bs64)
        return text

    async def desc_img(self, image, model=vlm, prompt="描述这张图片的内容，如果有文字请将其输出", is_base64=False):
        """
        describe an image
        :param image: url or base64
        :param model: defaults to DEFAULT_VLM
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
                "content":[
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
            vlm_provider = provider_manager.get_llm_provider(model)
            resp = await vlm_provider.chat(request)
            return resp.text_response

        except Exception as e:
            llm_logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    async def generate_img(self, prompt):
        img_provider = provider_manager.get_image_provider(image_provider)
        url = await img_provider.generate_image(prompt)
        return url


if __name__ == "__main__":
    llm = LLMClient()
