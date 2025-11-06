import asyncio

from utils.tool_utils import BaseTool
from core.message_manager import message_processor


class SendMessageTool(BaseTool):
    name = "send_message"
    description = "向指定会话发送消息（私聊消息和群聊消息）。target 形如 qq:dm:3429924750 或 qq:gm:123456，xml 为消息的XML片段。"
    parameters = {
        "type": "object",
        "properties": {
            "target": {"type": "string", "description": "会话标识，如 qq:dm:3429924750"},
            "xml": {"type": "string", "description": "消息的XML格式（与系统提示词中的格式要求一致，每条消息都需要msg标签包裹）"}
        },
        "required": ["target", "xml"]
    }

    def execute(self, target: str, xml: str) -> str:
        try:
            result = asyncio.create_task(message_processor.send_xml_messages(target, xml))
            return str(result)
        except Exception as e:
            return f"发送失败：{e}"
