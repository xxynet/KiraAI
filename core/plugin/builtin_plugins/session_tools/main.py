import asyncio

from core.plugin import BasePlugin, logger, on, Priority, register_tool
from core.chat.message_utils import KiraMessageBatchEvent
from core.provider import LLMRequest

from core.chat import Group, User, MessageChain
from core.chat.message_elements import Text

SESSION_TOOL_FEW_SHOT = """
### session_send 工具说明
当你需要在其他会话（私聊、群聊等）发送消息时，
即 当前会话 ≠ 发消息目标会话时，需要调用 `session_send` 工具进行**跨会话发送**。

#### 示例
* 场景：在群 1 中
* user：到群 12345678（群 2）发一条消息
* 行为：
  * 调用 `session_send` 工具
  * 完成跨会话消息发送
"""

CROSS_SESSION_PROMPT = """\
你接收到来自会话{session_id}转发到本会话的跨会话消息。

下面是跨会话消息的内容说明：
{description}

请你根据描述，直接生成要发送给最终用户的自然语言消息。
⚠注意：
1. 你当前已经在目标会话中，不需要再次调用跨会话工具。
2. 不要再次尝试发送跨会话消息。
3. 只需要输出最终要发给用户的xml格式消息"""


DESC_PROMPT = """\
对当前会话发生了什么的总结以及为什么需要发送跨会话消息
NOTE that the target session doesn't know anything about the current session
You need to precisely describe  what happened and the reason why you need to send cross session messages
DO NOT use pronouns to refer to anything in the current session, e.g. `这段对话`"""


class SessionPlugin(BasePlugin):
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
                "description": {"type": "string", "description": DESC_PROMPT}
            },
            "required": ["target", "description"]
        }
    )
    async def session_send(self, event: KiraMessageBatchEvent, target: str, description: str):
        parts = target.split(":")
        if not len(parts) == 3:
            raise ValueError(f"Failed to parse sid")
        if event.sid == target:
            return "Do not send messages to current session using this tool, output directly to send messages"
        try:
            cross_session_prompt = CROSS_SESSION_PROMPT.format(session_id=event.sid, description=description)

            await self.ctx.publish_notice(target, MessageChain([Text(cross_session_prompt)]))
            return f"message sent"
        except Exception as e:
            return f"failed to send: {e}"

    @on.llm_request()
    async def inject_few_shot(self, _event, req: LLMRequest, *_):
        for p in req.system_prompt:
            if p.name == "tools":
                p.content += SESSION_TOOL_FEW_SHOT
