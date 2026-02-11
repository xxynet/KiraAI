from asyncio import Semaphore
from typing import Optional
import copy
import json
import time

from core.logging_manager import get_logger
from core.utils.common_utils import image_to_base64
from .config import KiraConfig
from .provider import LLMRequest, LLMResponse, ModelType
from .provider import ProviderManager, ImageResult

logger = get_logger("llm", "purple")
tool_logger = get_logger("tool_use", "orange")


class LLMClient:
    def __init__(self, kira_config: KiraConfig, provider_mgr: ProviderManager):
        self.kira_config = kira_config

        self.provider_mgr = provider_mgr

        self.tools_definitions: list[dict] = []
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

    def unregister_tool(self, name: str):
        if name in self.tools_functions:
            del self.tools_functions[name]

        for i, tool_def in enumerate(self.tools_definitions):
            if tool_def.get("function", {}).get("name") == name:
                del self.tools_definitions[i]

    async def chat(self, messages) -> LLMResponse:
        """与LLM交互

        Args:
            messages: 消息列表

        Returns:
            LLMResponse
        """
        async with self.llm_semaphore:
            request = LLMRequest(messages)
            llm_model = self.provider_mgr.get_default_llm()
            response = await llm_model.chat(request)
            return response

    async def execute_tool(self, resp: LLMResponse):
        for tool_call in resp.tool_calls:
            tool_call_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")

            raw_args = tool_call.get("function", {}).get("arguments")
            try:
                if not raw_args.strip():
                    args = {}
                else:
                    args = json.loads(raw_args)
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse function calling arguments: {e}")
                logger.error(f"Raw args: {raw_args}")
                args = {}
            tool_logger.info(f"{name} args: {args}")

            # Call corresponding Python function(s)
            if self.tools_functions and name in self.tools_functions:
                try:
                    result = await self.tools_functions[name](**args)
                    tool_logger.info(f"tool_result: {result}")
                except Exception as e:
                    result = {"error": f"Failed to call tool '{name}': {e}"}
                    tool_logger.error(f"Failed to call tool '{name}': {e}")
            else:
                result = {"error": f"Tool {name} not implemented"}
                tool_logger.error(f"Tool {name} not implemented")

            # Save tool results
            resp.tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": str(result)
            })

    async def agent_run(self, user_message) -> LLMResponse:

        async with self.llm_semaphore:
            request = LLMRequest(user_message, tools=self.tools_definitions, tool_funcs=self.tools_functions)
            llm_model = self.provider_mgr.get_default_llm()
            provider_name = llm_model.model.provider_name
            model_id = llm_model.model.model_id
            logger.info(f"Running agent using {model_id} ({provider_name})")
            resp = await llm_model.chat(request)
            logger.debug(resp)
            if resp:
                logger.info(f"Time consumed: {resp.time_consumed}s, Input tokens: {resp.input_tokens}, output tokens: {resp.output_tokens}")
            return resp

    async def text_to_speech(self, text: str):
        tts_model = self.provider_mgr.get_default_tts()
        provider_name = tts_model.model.provider_name
        model_id = tts_model.model.model_id
        logger.info(f"Generating speech using {model_id} ({provider_name})")
        bs64 = await tts_model.text_to_speech(text)
        if bs64:
            logger.info(f"Generated speech from text {text}")
        return bs64

    async def speech_to_text(self, bs64):
        stt_model = self.provider_mgr.get_default_stt()
        provider_name = stt_model.model.provider_name
        model_id = stt_model.model.model_id
        logger.info(f"Recognizing text using {model_id} ({provider_name})")
        text = await stt_model.speech_to_text(stt_model, bs64)
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
                b64_data = await image_to_base64(image)

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
            vlm_model = self.provider_mgr.get_default_vlm()
            provider_name = vlm_model.model.provider_name
            model_id = vlm_model.model.model_id
            logger.info(f"Describing image using {model_id} ({provider_name})")
            resp = await vlm_model.chat(request)
            return resp.text_response
        except Exception as e:
            logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    async def generate_img(self, prompt) -> ImageResult:
        image_model = self.provider_mgr.get_default_image()
        provider_name = image_model.model.provider_name
        model_id = image_model.model.model_id
        logger.info(f"Generating image using {model_id} ({provider_name})")
        try:
            img_res = await image_model.text_to_image(prompt)
            if not img_res:
                logger.error(f"Failed to generate image with text")
            return img_res
        except Exception as e:
            logger.error(f"Failed to generate image with text: {e}")

    async def image_to_image(self, prompt, url: Optional[str] = None, bs64: Optional[str] = None):
        image_model = self.provider_mgr.get_default_image()
        provider_name = image_model.model.provider_name
        model_id = image_model.model.model_id
        logger.info(f"Generating image using {model_id} ({provider_name}) with a reference image")
        try:
            img_res = await image_model.image_to_image(prompt, url=url, base64=bs64)
            if not img_res:
                logger.error(f"Failed to generate image with a reference image")
            return img_res
        except Exception as e:
            logger.error(f"Failed to generate image with a reference image: {e}")
