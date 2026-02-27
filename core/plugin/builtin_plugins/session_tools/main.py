import json
import asyncio
import time
from typing import Union, Optional

from core.plugin import BasePlugin, logger, on, Priority, register_tool
from core.chat.message_utils import KiraMessageBatchEvent

from core.chat import Group, User, MessageChain
from core.chat.message_elements import Text


class DefaultPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.session_events: dict[str, asyncio.Event] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        bot_cfg = ctx.config["bot_config"].get("bot", {})
        self.debounce_interval = float(bot_cfg.get("max_message_interval", 1.5))
        self.max_buffer_messages = int(bot_cfg.get("max_buffer_messages", 3))
    
    async def initialize(self):
        pass
    
    async def terminate(self):
        """
        Cleanup when plugin is terminated
        """
        pass

    @register_tool(
        name="session_send",
        description="向指定会话发送跨会话消息（私聊消息和群聊消息），仅当目标会话和当前会话不同时使用。 target 形如 qq:dm:123456 或 qq:gm:123456",
        params={
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "会话标识，如 qq:dm:123456"},
                "description": {"type": "string", "description": "对当前会话发生了什么的总结以及为什么需要发送跨会话消息，发送的消息大致方向"}
            },
            "required": ["target", "description"]
        }
    )
    async def session_send(self, event: KiraMessageBatchEvent, target: str, description: str):
        parts = target.split(":")
        if not len(parts) == 3:
            raise ValueError(f"Failed to parse sid")
        ada_name, st, sid = parts
        if event.sid == target:
            return "Do not send messages to current session using this tool, output directly to send messages"
        try:
            ada = self.ctx.adapter_mgr.get_adapter(ada_name)

            cross_session_prompt = f"""\
        你接收到来自其他会话转发到本会话的跨会话消息。

        下面是跨会话消息的内容说明：
        {description}

        请你根据描述，直接生成要发送给最终用户的自然语言消息。
        ⚠注意：
        1. 你当前已经在目标会话中，不需要再次调用跨会话工具。
        2. 不要再次尝试发送跨会话消息。
        3. 只需要输出最终要发给用户的xml格式消息"""

            await self.ctx.publish_notice(target, MessageChain([Text(cross_session_prompt)]))
            return f"message sent"
        except Exception as e:
            return f"failed to send: {e}"
