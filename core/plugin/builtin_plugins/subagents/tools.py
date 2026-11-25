from typing import ClassVar

from core.agent.subagent_manager import SUBAGENT_TOOL_NAMES
from core.agent.tool import ToolSet
from core.config.tool_execution import build_tool_execution_config
from core.utils.tool_utils import BaseTool


def format_agent(agent: dict) -> str:
    """Render agent identity, progress and retained turn output."""
    title = str(agent["title"]).replace("\n", "\n  ")
    lines = [
        f"id: {agent['id']}",
        f"sid: {agent['sid']}",
        f"kind: {agent['kind']}",
        f"parent_id: {agent['parent_id']}",
        f"title: {title}",
        f"permission_sid: {agent['permission_sid']}",
        f"status: {agent['status']}",
        f"step_index: {agent['step_index']}",
        f"turn: {agent['turn']}",
    ]
    if agent["result"]:
        lines.append("result: " + agent["result"].replace("\n", "\n  "))
    if agent["error"]:
        lines.append("error: " + agent["error"].replace("\n", "\n  "))
    return "\n".join(lines)


class SubAgentTool(BaseTool):
    """Bind agent controls to the caller and share tool selection helpers."""

    def __init__(self, *, ctx, source, parent_tools: ToolSet):
        super().__init__(ctx=ctx)
        self.source = source
        self.parent_tools = parent_tools

    async def _get_source(self):
        return await self.ctx.session_mgr.get_session(self.source.sid, ensure_session=True)

    def _custom_tools(self, names: list[str], preset_id: str | None = None) -> ToolSet:
        pool = self.ctx.tool_mgr.build_tool_set()
        selected = []
        private_names = {tool.name for tool in self.ctx.subagent_mgr.presets.get_plugin_tools(preset_id)}
        server_map = self.ctx.mcp_mgr.get_tool_server_map() if self.ctx.mcp_mgr else {}
        for name in names:
            if name in private_names:
                continue
            tool = self.parent_tools.get(name)
            if tool is None:
                tool = pool.get(name)
            if name in SUBAGENT_TOOL_NAMES:
                raise ValueError(f"Unknown or unavailable child tool: {name}")
            if tool is None:
                continue
            server = server_map.get(name)
            if server and not self.ctx.mcp_mgr.is_server_allowed(server, self.source.sid):
                raise PermissionError(f"MCP server is not allowed for the calling session: {server}")
            selected.append(tool)
        return ToolSet(selected)

    async def _followup(self, event, agent_id: str, message: str, *, steer: bool) -> dict:
        source = await self._get_source()
        target = await self.ctx.session_mgr.resolve_session(agent_id)
        state = target.data.get("subagent", {})
        settings = state.get("settings", {})
        names = settings.get("tool_names", [])
        tools = self._custom_tools(names, state.get("preset_id")) if settings.get("tool_mode") == "custom" else None
        return await self.ctx.subagent_mgr.followup(
            target,
            message,
            caller_id=source.internal_id,
            parent_tools=self.parent_tools,
            tools=tools,
            steer=steer,
            source_event=event,
        )


class SpawnAgentTool(SubAgentTool):
    name = "spawn_agent"
    description = "Delegate an independent task to a background agent using an enabled subagent preset. Returns immediately; results are delivered to this session as a system notice after each turn."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Complete, self-contained task instructions"},
            "name": {"type": "string", "description": "Short session title"},
            "preset_name": {
                "type": "string",
                "minLength": 1,
                "description": "Exact name of an available subagent preset",
            },
            "session_retention_hours": {
                "type": "integer",
                "minimum": 0,
                "description": "Hours to retain this idle session since its last update. Use 0 to keep it indefinitely, or omit to use the configured default.",
            },
        },
        "required": ["task", "preset_name"],
        "additionalProperties": False,
    }

    async def execute(
        self,
        event,
        *,
        task: str,
        preset_name: str,
        name: str | None = None,
        session_retention_hours: int | None = None,
    ):
        if not isinstance(preset_name, str) or not preset_name.strip():
            raise ValueError("preset_name must be a non-empty string")
        preset_id, preset = self.ctx.subagent_mgr.presets.get_enabled_by_name(
            preset_name.strip(),
            session_id=self.source.sid,
        )
        source = await self._get_source()
        config = preset.execution_config(build_tool_execution_config(self.ctx.config))
        tools = self._custom_tools(list(config.tool_names), preset_id) if config.tool_mode == "custom" else None
        result = await self.ctx.subagent_mgr.spawn(
            task,
            parent_id=source.internal_id,
            permission_session=source,
            title=preset.name if name is None else name,
            config=config,
            parent_tools=self.parent_tools,
            tools=tools,
            preset_id=preset_id,
            source_event=event,
            session_retention_hours=session_retention_hours,
        )
        return format_agent(result)


class ListAgentsTool(SubAgentTool):
    name = "list_agents"
    description = "List your child agents, their current state and retained results."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def execute(self, event, **args):
        source = await self._get_source()
        agents = await self.ctx.subagent_mgr.list_agents(caller_id=source.internal_id)
        return "\n\n".join(format_agent(agent) for agent in agents) or "No child agents."


class SendMessageTool(SubAgentTool):
    name = "send_message"
    description = "Steer a running child agent; start a fresh turn if it is idle or cannot accept steering."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Subagent internal ID or full session SID"},
            "message": {"type": "string", "description": "Instruction or follow-up task"},
        },
        "required": ["agent_id", "message"],
    }

    async def execute(self, event, **args):
        result = await self._followup(
            event,
            args["agent_id"],
            args["message"],
            steer=True,
        )
        return format_agent(result)


class FollowupTaskTool(SubAgentTool):
    name = "followup_task"
    description = "Queue another task on a child session with a fresh step budget."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Subagent internal ID or full session SID"},
            "message": {"type": "string", "description": "Instruction or follow-up task"},
        },
        "required": ["agent_id", "message"],
    }

    async def execute(self, event, **args):
        result = await self._followup(
            event,
            args["agent_id"],
            args["message"],
            steer=False,
        )
        return format_agent(result)


class InterruptAgentTool(SubAgentTool):
    name = "interrupt_agent"
    description = "Stop a child after its current model or tool call finishes; discard pending follow-ups."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "agent_id": {"type": "string", "description": "Subagent internal ID or full session SID"},
        },
        "required": ["agent_id"],
    }

    async def execute(self, event, **args):
        source = await self._get_source()
        result = await self.ctx.subagent_mgr.interrupt(
            args["agent_id"],
            caller_id=source.internal_id,
        )
        return format_agent(result)
