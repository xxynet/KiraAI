import asyncio
import time

from core.services.runtime import get_event_bus, get_adapter_by_name
from utils.message_utils import KiraMessageEvent, MessageType
from utils.tool_utils import BaseTool


class SendMessageTool(BaseTool):
    name = "send_message"
    description = "向指定会话发送消息（私聊消息和群聊消息）。target 形如 qq:dm:123456 或 qq:gm:123456"
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "会话标识，如 qq:dm:123456"},
            "description": {"type": "string", "description": "对当前会话发生了什么的总结以及为什么需要发送跨会话消息，发送的消息大致方向"}
        },
        "required": ["target", "description"]
    }

    async def execute(self, target: str, description: str) -> str:
        try:
            ada = get_adapter_by_name(target.split(":")[0])

            cross_session_prompt = f"""你接收到来自其他会话转发到本会话的跨会话消息。

下面是跨会话消息的内容说明：
{description}

请你根据描述，直接生成要发送给最终用户的自然语言消息。
⚠注意：
1. 你当前已经在目标会话中，不需要再次调用跨会话工具。
2. 不要再次尝试发送跨会话消息。
3. 只需要输出最终要发给用户的xml格式消息"""

            message_obj = KiraMessageEvent(
                platform=ada.name,
                adapter_name=target.split(":")[0],
                message_types=ada.message_types,
                user_id=target.split(":")[2] if target.split(":")[1] == "dm" else "unknown",
                user_nickname="system",
                message_id="system_message",
                self_id=ada.config.get("self_id"),
                content=[MessageType.Notice(cross_session_prompt)],
                timestamp=int(time.time()),
                group_id=target.split(":")[2] if target.split(":")[1] == "gm" else None,
                group_name="unknown"
            )
            event_bus = get_event_bus()
            await event_bus.put(message_obj)
            return f"message sent: {description}"
        except Exception as e:
            return f"failed to send: {e}"
