from openai import AsyncOpenAI
import json

from core.logging_manager import get_logger
from ..provider import LLMProvider
from ..llm_model import LLMModel, LLMRequest, LLMResponse, LLMClientType


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
        response = await client.chat.completions.create(
            model=self.get_models(),
            messages=request.messages,
            tools=request.tools
        )
        llm_resp = LLMResponse("")
        if response.choices:
            message = response.choices[0].message

            if message.tool_calls:

                # tool_messages = [json.loads(message.model_dump_json())]
                tool_messages = []

                for tool_call in message.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments)
                    tool_logger.info(f"{name} args: {args}")

                    # 调用对应的 Python 函数
                    if name in request.tool_funcs:
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

                llm_resp.tool_results = tool_messages

            content = message.content if message.content else ""
            reasoning_content = getattr(message, "reasoning_content", "")
            llm_resp.text_response = content
            llm_resp.reasoning_content = reasoning_content
            llm_resp.input_tokens = response.usage.prompt_tokens
            llm_resp.output_tokens = response.usage.completion_tokens
        return llm_resp
