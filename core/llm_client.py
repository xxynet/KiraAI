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
from .provider import LLMResponse

tool_logger = get_logger("tool_use", "orange")
llm_logger = get_logger("llm", "purple")

# === model config ===
MAIN_PROVIDER = global_config["models"].get("main_llm").get("provider")
MAIN_API_BASE_URL = global_config["providers"].get(MAIN_PROVIDER).get("base_url")
MAIN_API_KEY = global_config["providers"].get(MAIN_PROVIDER).get("api_key")
DEFAULT_LLM = global_config["models"].get("main_llm").get("model")

TOOL_PROVIDER = global_config["models"].get("tool_llm").get("provider")
TOOL_API_BASE_URL = global_config["providers"].get(TOOL_PROVIDER).get("base_url")
TOOL_API_KEY = global_config["providers"].get(TOOL_PROVIDER).get("api_key")
DEFAULT_TOOL_LLM = global_config["models"].get("tool_llm").get("model")

VLM_PROVIDER = global_config["models"].get("vlm").get("provider")
VLM_API_BASE_URL = global_config["providers"].get(VLM_PROVIDER).get("base_url")
VLM_API_KEY = global_config["providers"].get(VLM_PROVIDER).get("api_key")
DEFAULT_VLM = global_config["models"].get("vlm").get("model")

UTIL_PROVIDER = global_config["models"].get("util_model").get("provider")
UTIL_API_BASE_URL = global_config["providers"].get(UTIL_PROVIDER).get("base_url")
UTIL_API_KEY = global_config["providers"].get(UTIL_PROVIDER).get("api_key")
DEFAULT_UTIL_MODEL = global_config["models"].get("util_model").get("model")

DEFAULT_TTI = global_config["models"].get("tti").get("model")
TTI_API_KEY = global_config["models"].get("tti").get("api_key")


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
        """初始化LLM客户端"""
        self.client = AsyncOpenAI(
            api_key=MAIN_API_KEY,
            base_url=MAIN_API_BASE_URL
        )
        self.tool_client = AsyncOpenAI(
            api_key=TOOL_API_KEY,
            base_url=TOOL_API_BASE_URL
        )
        self.vlm_client = AsyncOpenAI(
            api_key=VLM_API_KEY,
            base_url=VLM_API_BASE_URL
        )
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

    async def chat(self, messages, model=DEFAULT_LLM) -> LLMResponse:
        """与LLM交互

        Args:
            messages: 消息列表
            model: 使用的LLM模型

        Returns:
            tuple: (content, reasoning_content)
        """
        async with self.llm_semaphore:
            llm_resp = LLMResponse("", "")
            try:
                # print(f"LLM请求: {messages}")
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=messages,
                )
                if response.choices:
                    message = response.choices[0].message
                    content = message.content if message.content else ""
                    reasoning_content = getattr(message, "reasoning_content", "")
                    llm_resp.text_response = content
                    llm_resp.reasoning_content = reasoning_content
                    return llm_resp

                return llm_resp

            except Exception as e:
                print(f"LLM调用出错: {str(e)}")
                return llm_resp

    @timer
    async def chat_with_tools(self, user_message, tool_system_prompt) -> LLMResponse:
        # 第一次调用，让模型决定是否调用工具

        async with self.llm_semaphore:
            llm_resp = LLMResponse("", "")
            raw_msg = copy.deepcopy(user_message)
            raw_msg[0] = {"role": "system", "content": tool_system_prompt}

            llm_logger.info(f"checking whether to call tools using {DEFAULT_TOOL_LLM} from {TOOL_PROVIDER}")
            resp1 = await self.tool_client.chat.completions.create(
                model=DEFAULT_TOOL_LLM,
                messages=raw_msg,
                tools=self.tools_definitions
            )

            message = resp1.choices[0].message

            # 如果模型调用了工具
            if message.tool_calls:

                # tool_messages = [json.loads(message.model_dump_json())]
                tool_messages = []

                for tool_call in message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_logger.info(f"{name} args: {args}")

                    # 调用对应的 Python 函数
                    if name in self.tools_functions:
                        result = await self.tools_functions[name](**args)
                        tool_logger.info(f"tool_result: {result}")
                    else:
                        result = {"error": f"工具 {name} 未实现"}
                        tool_logger.error(f"工具 {name} 未实现")

                    # 保存工具执行结果
                    tool_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": str(result)
                    })

                user_message.extend(tool_messages)

                try:
                    llm_logger.info(f"generating response using {DEFAULT_LLM} from {MAIN_PROVIDER}")
                    resp2 = await self.client.chat.completions.create(
                        model=DEFAULT_LLM,
                        messages=user_message
                    )

                    llm_resp.text_response = resp2.choices[0].message.content
                    llm_resp.tool_results = tool_messages

                    return llm_resp
                except Exception as e:
                    print("messages:")
                    print(json.dumps(user_message, ensure_ascii=False, indent=2))
                    print(e)
                    return llm_resp
            else:
                # model did not use tools
                try:
                    llm_logger.info(f"generating response using {DEFAULT_LLM} from {MAIN_PROVIDER}")
                    resp2 = await self.client.chat.completions.create(
                        model=DEFAULT_LLM,
                        messages=user_message
                    )
                    message2 = resp2.choices[0].message
                    llm_resp.text_response = message2.content
                    return llm_resp
                except Exception as e:
                    llm_logger.error(f"error while generating response when tools are not called: {str(e)}")
                    return llm_resp

    async def desc_img(self, image, model=DEFAULT_VLM, prompt="描述这张图片的内容，如果有文字请将其输出", is_base64=False):
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

            response = await self.vlm_client.chat.completions.create(
                model=model,
                messages=messages,
            )
            if response.choices:
                message = response.choices[0].message
                content = message.content if message.content else ""
                return content

            return ""

        except Exception as e:
            llm_logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    def generate_img(self, prompt):
        url = "https://api.siliconflow.cn/v1/images/generations"
        payload = {
            "model": DEFAULT_TTI,
            "prompt": prompt,
            "image_size": "1024x1024",
            "batch_size": 1,
            "num_inference_steps": 20,
            "guidance_scale": 7.5
        }
        headers = {
            "Authorization": f"Bearer {TTI_API_KEY}",
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        return response.json().get("images")[0].get("url")


if __name__ == "__main__":
    llm = LLMClient()
