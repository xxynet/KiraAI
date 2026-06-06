from __future__ import annotations

from asyncio import Semaphore, wait_for, TimeoutError as AsyncTimeoutError
from typing import Optional, Union, TYPE_CHECKING
import copy
import json
import time

from core.logging_manager import get_logger
from core.chat.message_elements import Record, Image, Sticker
from .config import KiraConfig
from .provider import LLMRequest, LLMResponse
from .agent.tool import ToolResult, ToolSet
from core.utils.tool_utils import BaseTool
from .provider import ProviderManager

logger = get_logger("llm", "purple")
tool_logger = get_logger("tool_use", "orange")

if TYPE_CHECKING:
    from core.chat import KiraMessageBatchEvent


class _LegacyFuncTool(BaseTool):
    """Wraps a legacy (name, description, parameters, func) quadruple as a BaseTool."""

    def __init__(self, name: str, description: str, parameters: dict, func):
        self.name = name
        self.description = description
        self.parameters = parameters
        self._func = func

    async def execute(self, *args, **kwargs):
        return await self._func(*args, **kwargs)

    def get_schema(self):
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


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

    def build_tool_set(self) -> ToolSet:
        """Wrap all registered legacy tools into a unified ToolSet."""
        tool_set = ToolSet()
        for td in self.tools_definitions:
            func_def = td.get("function", {})
            name = func_def.get("name")
            if not name:
                continue
            func = self.tools_functions.get(name)
            if not func:
                continue
            tool_set.add(_LegacyFuncTool(
                name=name,
                description=func_def.get("description", ""),
                parameters=func_def.get("parameters", {}),
                func=func,
            ))
        return tool_set

    async def execute_tool(self, event: KiraMessageBatchEvent, resp: LLMResponse, tool_set: Optional[ToolSet] = None):
        max_tool_calls_per_turn = self.kira_config.get_config("bot_config.agent.max_tool_calls_per_turn")
        try:
            max_tool_calls_per_turn = int(max_tool_calls_per_turn)
        except (TypeError, ValueError):
            max_tool_calls_per_turn = 5

        tool_call_timeout = self.kira_config.get_config("bot_config.agent.tool_call_timeout")
        try:
            tool_call_timeout = float(tool_call_timeout)
            if tool_call_timeout <= 0:
                tool_call_timeout = None
        except (TypeError, ValueError):
            tool_call_timeout = 60

        for idx, tool_call in enumerate(resp.tool_calls):
            tool_call_id = tool_call.get("id")
            name = tool_call.get("function", {}).get("name")

            # Exceeds per-turn tool call limit
            if idx >= max_tool_calls_per_turn:
                warn_msg = f"Tool call limit exceeded: maximum {max_tool_calls_per_turn} tool calls per turn, skipping tool '{name}'."
                tool_logger.warning(warn_msg)
                resp.tool_results.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": warn_msg
                })
                continue

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
                    coro = self.tools_functions[name](event, **args)
                    result = await (wait_for(coro, tool_call_timeout) if tool_call_timeout else coro)
                except AsyncTimeoutError:
                    result = {"error": f"Tool '{name}' timed out after {tool_call_timeout}s"}
                    tool_logger.error(f"Tool '{name}' timed out after {tool_call_timeout}s")
                except Exception as e:
                    result = {"error": f"Failed to call tool '{name}': {e}"}
                    tool_logger.error(f"Failed to call tool '{name}': {e}")
            elif tool_set and name in tool_set:
                try:
                    tool_inst = tool_set.get(name)
                    coro = tool_inst.execute(event, **args)
                    result = await (wait_for(coro, tool_call_timeout) if tool_call_timeout else coro)
                except AsyncTimeoutError:
                    result = {"error": f"Tool '{name}' timed out after {tool_call_timeout}s"}
                    tool_logger.error(f"Tool '{name}' timed out after {tool_call_timeout}s")
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

    async def generate_img(self, prompt) -> Image:
        image_model = self.provider_mgr.get_default_image()
        provider_name = image_model.model.provider_name
        model_id = image_model.model.model_id
        logger.info(f"Generating image using {model_id} ({provider_name})")
        try:
            img_res = await image_model.text_to_image(prompt)
            if img_res:
                logger.info(f"Image generated with prompt: {prompt}")
                logger.debug(f"type={img_res.image_type}, len={len(img_res.image or '')}, prefix={(img_res.image or '')[:200]!r}")
            else:
                logger.error("Failed to generate image with text: result is None")
            return img_res
        except Exception as e:
            logger.error(f"Failed to generate image with text: {e}")

    async def image_to_image(self, prompt, image: Union[Image, list[Image]]) -> Image:
        image_model = self.provider_mgr.get_default_image()
        provider_name = image_model.model.provider_name
        model_id = image_model.model.model_id
        logger.info(f"Generating image using {model_id} ({provider_name}) with a reference image")
        try:
            img_res = await image_model.image_to_image(prompt=prompt, image=image)
            if img_res:
                logger.info(f"Image generated (img2img): prompt: {prompt}")
                logger.debug(f"type={img_res.image_type}, len={len(img_res.image or '')}, prefix={(img_res.image or '')[:200]!r}")
            else:
                logger.error("Failed to generate image with a reference image: result is None")
            return img_res
        except Exception as e:
            logger.error(f"Failed to generate image with a reference image: {e}")
