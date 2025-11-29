import asyncio
import time

from core.services.runtime import get_event_bus, get_adapter_by_name
from utils.message_utils import KiraMessageEvent, MessageType
from utils.tool_utils import BaseTool
from core.message_manager import message_processor


class SendMessageTool(BaseTool):
    name = "send_message"
    description = "向指定会话发送消息（私聊消息和群聊消息）。target 形如 qq:dm:123456 或 qq:gm:123456"
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "会话标识，如 qq:dm:123456"},
            "description": {"type": "string", "description": "对当前会话的总结以及为什么需要发送跨会话消息"}
        },
        "required": ["target", "description"]
    }

    async def execute(self, target: str, description: str) -> str:
        try:
            ada = get_adapter_by_name(target.split(":")[0])

            message_obj = KiraMessageEvent(
                platform=ada.name,
                adapter_name=target.split(":")[0],
                message_types=ada.message_types,
                user_id=target.split(":")[2] if target.split(":")[1] == "dm" else "unknown",
                user_nickname="system",
                message_id="system_message",
                self_id=ada.config.get("self_id"),
                content=[MessageType.Notice(f"从会话{target}触发了跨会话消息：{description}")],
                timestamp=int(time.time()),
                group_id=target.split(":")[2] if target.split(":")[1] == "gm" else None,
                group_name="unknown"
            )
            event_bus = get_event_bus()
            await event_bus.put(message_obj)
            return f"message sent"
        except Exception as e:
            return f"failed to send:：{e}"
