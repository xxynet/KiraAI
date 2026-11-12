from core.agent.subagent_manager import SUBAGENT_COMPLETED_EVENT
from core.agent.tool import ToolSet
from core.chat.message_elements import Text
from core.chat.message_utils import KiraCustomEvent, MessageChain
from core.plugin import BasePlugin, Priority, on
from core.provider import LLMRequest

from .tools import (
    FollowupTaskTool,
    InterruptAgentTool,
    ListAgentsTool,
    SendMessageTool,
    SpawnAgentTool,
)


class SubAgentsPlugin(BasePlugin):
    """Expose native background agent controls through the caller's request."""

    async def initialize(self):
        """Tools are bound to each request rather than the main tool registry."""

    async def terminate(self):
        """The application lifecycle owns the background agents."""

    @on.custom_event(event_name=SUBAGENT_COMPLETED_EVENT)
    async def notify_parent(self, event: KiraCustomEvent):
        """Deliver a completed turn through the parent's existing notice pipeline."""
        if event.source_plugin != "subagents":
            return
        info = event.payload
        child = await self.ctx.session_mgr.get_session(info["sid"], include_content=False)
        if child is None or child.parent_id is None or child.parent_id != info["parent_id"]:
            return
        message = (
            f"Subagent turn finished (agent_id: {info['id']}, name: {info['title']}, "
            f"turn: {info['turn']}, status: {info['status']}):\n{info['result']}"
        )
        if info["error"]:
            message += f"\nError: {info['error']}"
        await self.ctx.publish_notice(
            child.parent_id,
            MessageChain([Text(message)]),
            is_mentioned=True,
        )

    @on.llm_request(priority=Priority.SYS_LOW)
    async def inject_tools(self, event, request: LLMRequest, *_):
        if request.tool_set is None:
            request.tool_set = ToolSet()
        can_spawn = self.ctx.subagent_mgr.presets.has_available_presets(event.session.sid)
        for tool_type in (
            SpawnAgentTool,
            ListAgentsTool,
            SendMessageTool,
            FollowupTaskTool,
            InterruptAgentTool,
        ):
            if tool_type is SpawnAgentTool and not can_spawn:
                continue
            request.tool_set.add(tool_type(
                ctx=self.ctx,
                source=event.session,
                request=request,
            ))
