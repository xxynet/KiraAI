from core.agent.subagent_manager import SUBAGENT_COMPLETED_EVENT, SUBAGENT_TOOL_NAMES
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

    async def initialize(self) -> None:
        """Tools are bound to each request rather than the main tool registry."""

    async def terminate(self) -> None:
        """The application lifecycle owns the background agents."""

    @on.custom_event(event_name=SUBAGENT_COMPLETED_EVENT)
    async def notify_parent(self, event: KiraCustomEvent) -> None:
        """Deliver a completed turn through the parent's existing notice pipeline."""
        if event.source_plugin != "subagents":
            return
        info = event.payload
        child = await self.ctx.session_mgr.get_session(
            info["sid"], include_content=False
        )
        if (
            child is None
            or child.parent_id is None
            or child.parent_id != info["parent_id"]
        ):
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
    async def inject_tools(self, event, request: LLMRequest, *_) -> None:
        parent_tools = request.tool_set if request.tool_set is not None else ToolSet()
        manager = self.ctx.subagent_mgr
        presets = manager.presets
        source = event.session
        sid = source.sid
        can_spawn = presets.has_available_presets(sid)
        if not can_spawn:
            caller_id = source.internal_id
            if caller_id is None:
                stored = await self.ctx.session_mgr.get_session(
                    sid, include_content=False
                )
                caller_id = stored.internal_id if stored is not None else None
            if caller_id is None or not await manager.has_manageable_agents(caller_id):
                parent_tools.remove(*SUBAGENT_TOOL_NAMES)
                request.tool_set = parent_tools
                return
            parent_tools.remove(SpawnAgentTool.name)

        excluded = presets.main_tool_exclusions(
            sid, {tool.name for tool in parent_tools.tools}
        )
        # Keep delegation bound to the unfiltered pool, including request-local tools.
        request.tool_set = (
            ToolSet([tool for tool in parent_tools.tools if tool.name not in excluded])
            if excluded
            else parent_tools
        )
        for tool_type in (
            SpawnAgentTool,
            ListAgentsTool,
            SendMessageTool,
            FollowupTaskTool,
            InterruptAgentTool,
        ):
            if tool_type is SpawnAgentTool and not can_spawn:
                continue
            request.tool_set.add(
                tool_type(
                    ctx=self.ctx,
                    source=source,
                    parent_tools=parent_tools,
                )
            )
