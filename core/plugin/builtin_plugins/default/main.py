import json
import asyncio
from pathlib import Path
import xml.etree.ElementTree as ET
from typing import Union, Optional
from datetime import datetime

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraIMMessage
from core.provider import LLMRequest, LLMResponse
from core.prompt_manager import Prompt

from core.utils.tool_utils import BaseTool


XML_FIX_PROMPT = """\
你是一个xml 格式检查器，请将下面解析失败的xml修改为正确的格式，但不要修改标签内的任何数据，需要符合如下xml tag结构（非标准xml，没有<root>标签）：
<msg>
    ...
</msg>
其中可以有多个<msg>，代表发送多条消息。每个msg标签中可以有多个子标签代表不同的消息元素，如<text>文本消息</text>。如果消息中存在未转义的特殊字符请转义。直接输出修改后的内容，不要解释，不要输出任何多余内容。
当前报错：{exc}"""


class DefaultPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
    
    async def initialize(self):
        pass
    
    async def terminate(self):
        pass

    @staticmethod
    def _get_current_time_str() -> str:
        now = datetime.now()
        return now.strftime("%b %d %Y %H:%M %a")

    def _format_user_message(self, msg: Union[KiraIMMessage]) -> str:
        """格式化用户消息"""
        date_str = self._get_current_time_str()
        # TODO format it in message processor
        if isinstance(msg, KiraIMMessage):
            if msg.is_group_message():
                if msg.is_notice:
                    return f"[{date_str}] Notice [group_id: {msg.group.group_id}, user_id: {msg.sender.user_id}] | {msg.message_str}"
                return f"[{date_str}] [message_id: {str(msg.message_id)}] [group_name: {msg.group.group_name} group_id: {msg.group.group_id} user_nickname: {msg.sender.nickname}, user_id: {msg.sender.user_id}] | {msg.message_str}"
            else:
                if msg.is_notice:
                    return f"[{date_str}] Notice [user_id: {msg.sender.user_id}] | {msg.message_str}"
                return f"[{date_str}] [message_id: {str(msg.message_id)}] [user_nickname: {msg.sender.nickname}, user_id: {msg.sender.user_id}] | {msg.message_str}"
        else:
            return ""

    @on.llm_request(priority=Priority.HIGH)
    async def on_llm_req(self, event: KiraMessageBatchEvent, req: LLMRequest):
        message_index = 0
        for i, p in enumerate(req.user_prompt):
            if p.name == "message" and p.source == "system":
                if message_index >= len(event.messages):
                    break
                formatted_message = self._format_user_message(event.messages[message_index])
                p.content = formatted_message
                message_index += 1

    @on.llm_response()
    async def on_llm_resp(self, _, resp: LLMResponse):
        xml_data = resp.text_response
        if not xml_data:
            return

        try:
            root = ET.fromstring(f"<root>{xml_data}</root>")
            for msg in root.findall("msg"):
                for child in msg:
                    tag = child.tag
                    value = child.text.strip() if child.text else ""
        except ET.ParseError as e:
            logger.error(f"Error parsing message: {str(e)}")
            logger.debug(f"previously wrong format: {xml_data}")

            try:
                llm_resp = await self.ctx.llm_api.chat([
                    {"role": "system",
                     "content": XML_FIX_PROMPT.format(exc=str(e))},
                    {"role": "user", "content": xml_data}
                ])
                fixed_xml = llm_resp.text_response
                logger.debug(f"fixed xml data: {fixed_xml}")
                resp.text_response = fixed_xml
            except Exception as e:
                logger.error(f"Failed to fix xml parse error: {e}")
