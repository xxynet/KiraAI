from openai import AsyncOpenAI, APIStatusError, APITimeoutError, APIConnectionError
import asyncio
import json
from typing import Optional

from core.logging_manager import get_logger
from ..provider import LLMProvider, ImageProvider
from ..llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType
from ..image_result import ImageResult


logger = get_logger("provider", "purple")
tool_logger = get_logger("tool_use", "orange")


class OpenAIProvider(LLMProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    def get_keys(self) -> list[str]:
        return self.provider_config.get("api_key", "")

    def get_models(self) -> str:
        return self.provider_config.get("model", "")

    async def chat(self, request: LLMRequest) -> LLMResponse:
        client = AsyncOpenAI(
            api_key=self.get_keys(),
            base_url=self.provider_config.get("base_url", "")
        )
        try:
            response = await client.chat.completions.create(
                model=self.get_models(),
                messages=request.messages,
                tools=request.tools if request.tools else None,
                tool_choice=request.tool_choice if request.tool_choice != "none" else None
            )
            llm_resp = LLMResponse("")
            if response.choices:
                message = response.choices[0].message

                if message.tool_calls:

                    # tool_messages = [json.loads(message.model_dump_json())]
                    tool_messages = []

                    # 先添加 assistant 调用 tool 的消息
                    assistant_msg = {
                        "role": "assistant",
                        "content": message.content if message.content else None,
                        "tool_calls": []
                    }
                    
                    for tool_call in message.tool_calls:
                        name = tool_call.function.name
                        args = json.loads(tool_call.function.arguments)
                        tool_logger.info(f"{name} args: {args}")

                        # 保存 tool_call 信息到 assistant 消息中
                        assistant_msg["tool_calls"].append({
                            "id": tool_call.id,
                            "type": "function",
                            "function": {
                                "name": name,
                                "arguments": tool_call.function.arguments
                            }
                        })

                        # 调用对应的 Python 函数
                        if request.tool_funcs and name in request.tool_funcs:
                            result = await request.tool_funcs[name](**args)
                            tool_logger.info(f"tool_result: {result}")
                        else:
                            result = {"error": f"工具 {name} 未实现"}
                            tool_logger.error(f"工具 {name} 未实现")

                        # 保存工具执行结果
                        tool_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "name": name,
                            "content": str(result)
                        })

                    # tool_results 列表：先 assistant，后 tool
                    llm_resp.tool_results = [assistant_msg] + tool_messages

                content = message.content if message.content else ""
                reasoning_content = getattr(message, "reasoning_content", "")
                llm_resp.text_response = content
                llm_resp.reasoning_content = reasoning_content
                llm_resp.input_tokens = response.usage.prompt_tokens
                llm_resp.output_tokens = response.usage.completion_tokens
            return llm_resp
        except APIStatusError as e:
            # the model does not support function calling etc.
            # 403 Authorization failed (api key error)
            logger.error(f"APIStatusError: {e}")
        except APITimeoutError as e:
            logger.error(f"APITimeoutError: {e}")
        except APIConnectionError as e:
            # APIConnectionError: Connection error.(base_url error)
            logger.error(f"APIConnectionError: {e}")


class OpenAIImageProvider(ImageProvider):
    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def text_to_image(self, prompt) -> ImageResult:
        client = AsyncOpenAI(
            base_url=self.provider_config.get("base_url", ""),
            api_key=self.provider_config.get("api_key", ""),
        )

        images_response = await client.images.generate(
            model=self.provider_config.get("model", ""),
            prompt=prompt,
            size=self.provider_config.get("size", None),
            response_format="url",
            extra_body={
                "watermark": False,
            },
        )

        return ImageResult(images_response.data[0].url)

    async def image_to_image(self, prompt: str, url: Optional[str] = None, base64: Optional[str] = None) -> ImageResult:
        pass
