from __future__ import annotations

from asyncio import Semaphore
from typing import Optional, TYPE_CHECKING
import copy
import json
import time

from core.logging_manager import get_logger
from core.utils.common_utils import image_to_base64
from core.chat.message_elements import Record, Image
from .config import KiraConfig
from .provider import LLMRequest, LLMResponse
from .agent.tool import ToolResult, ToolSet
from .provider import ProviderManager

logger = get_logger("llm", "purple")
tool_logger = get_logger("tool_use", "orange")

if TYPE_CHECKING:
    from core.chat import KiraMessageBatchEvent


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

    async def execute_tool(self, event: KiraMessageBatchEvent, resp: LLMResponse, tool_set: Optional[ToolSet] = None):
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
                    result = await self.tools_functions[name](event, **args)
                except Exception as e:
                    result = {"error": f"Failed to call tool '{name}': {e}"}
                    tool_logger.error(f"Failed to call tool '{name}': {e}")
            elif tool_set and name in tool_set:
                try:
                    tool_inst = tool_set.get(name)
                    result = await tool_inst.execute()
                except Exception as e:
                    result = {"error": f"Failed to call tool '{name}': {e}"}
                    tool_logger.error(f"Failed to call tool '{name}': {e}")
            else:
                result = {"error": f"Tool {name} not implemented"}
                tool_logger.error(f"Tool {name} not implemented")

            if isinstance(result, ToolResult):
                tool_result_obj = result
            else:
                tool_result_obj = ToolResult(str(result))

            from core.plugin.plugin_handlers import event_handler_reg, EventType

            # EventType.ON_TOOL_RESULT
            llm_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_TOOL_RESULT)
            for handler in llm_handlers:
                await handler.exec_handler(event, tool_result_obj)
                if event.is_stopped:
                    logger.info("Event stopped while ON_TOOL_RESULT stage")
                    return

            # Save tool results
            content = await tool_result_obj.assemble_result()
            tool_logger.info(f"tool_result: {content}")
            resp.tool_results.append({
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": name,
                "content": content
            })

    async def text_to_speech(self, text: str) -> Record:
        tts_model = self.provider_mgr.get_default_tts()
        provider_name = tts_model.model.provider_name
        model_id = tts_model.model.model_id
        logger.info(f"Generating speech using {model_id} ({provider_name})")
        record = await tts_model.text_to_speech(text)
        if record:
            logger.info(f"Generated speech from text {text}")
        return record

    async def speech_to_text(self, record: Record):
        stt_model = self.provider_mgr.get_default_stt()
        provider_name = stt_model.model.provider_name
        model_id = stt_model.model.model_id
        logger.info(f"Recognizing text using {model_id} ({provider_name})")
        text = await stt_model.speech_to_text(record)
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

            request = LLMRequest(messages=messages)
            vlm_model = self.provider_mgr.get_default_vlm()
            provider_name = vlm_model.model.provider_name
            model_id = vlm_model.model.model_id
            logger.info(f"Describing image using {model_id} ({provider_name})")
            resp = await vlm_model.chat(request)
            return resp.text_response
        except Exception as e:
            logger.error(f"error occurred when describing image: {str(e)}")
            return ""

    async def generate_img(self, prompt) -> Image:
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

    async def image_to_image(self, prompt, image: Image) -> Image:
        image_model = self.provider_mgr.get_default_image()
        provider_name = image_model.model.provider_name
        model_id = image_model.model.model_id
        logger.info(f"Generating image using {model_id} ({provider_name}) with a reference image")
        try:
            img_res = await image_model.image_to_image(prompt=prompt, image=image)
            if not img_res:
                logger.error(f"Failed to generate image with a reference image")
            return img_res
        except Exception as e:
            logger.error(f"Failed to generate image with a reference image: {e}")
