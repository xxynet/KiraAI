import json
from typing import ClassVar

from core.agent.subagent_manager import SUBAGENT_TOOL_NAMES
from core.agent.tool import ToolSet
from core.config.tool_execution import build_tool_execution_config
from core.utils.tool_utils import BaseTool


class SubAgentTool(BaseTool):
    """Bind agent controls to the caller and share tool selection helpers."""

    def __init__(self, *, ctx, source, request):
        super().__init__(ctx=ctx)
        self.source = source
        self.request = request

    async def _get_source(self):
        return await self.ctx.session_mgr.get_session(self.source.sid, ensure_session=True)

    def _custom_tools(self, names: list[str]) -> ToolSet:
        pool = self.ctx.tool_mgr.build_tool_set()
        selected = []
        server_map = self.ctx.mcp_mgr.get_tool_server_map() if self.ctx.mcp_mgr else {}
        for name in names:
            tool = self.request.tool_set.get(name)
            if tool is None:
                tool = pool.get(name)
            if tool is None or name in SUBAGENT_TOOL_NAMES:
                raise ValueError(f"Unknown or unavailable child tool: {name}")
            server = server_map.get(name)
            if server and not self.ctx.mcp_mgr.is_server_allowed(server, self.source.sid):
                raise PermissionError(f"MCP server is not allowed for the calling session: {server}")
            selected.append(tool)
        return ToolSet(selected)

    async def _followup(self, agent_id: str, message: str, *, steer: bool) -> dict:
        source = await self._get_source()
        target = await self.ctx.session_mgr.resolve_session(agent_id)
        settings = target.data.get("subagent", {}).get("settings", {})
        names = settings.get("tool_names", [])
        tools = self._custom_tools(names) if settings.get("tool_mode") == "custom" else None
        return await self.ctx.subagent_mgr.followup(
            target,
            message,
            caller_id=source.internal_id,
            parent_tools=self.request.tool_set,
            tools=tools,
            steer=steer,
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
        },
        "required": ["task", "preset_name"],
        "additionalProperties": False,
    }

    async def execute(self, event, *, task: str, preset_name: str, name: str | None = None):
        if not isinstance(preset_name, str) or not preset_name.strip():
            raise ValueError("preset_name must be a non-empty string")
        preset_id, preset = self.ctx.subagent_mgr.presets.get_enabled_by_name(preset_name.strip())
        source = await self._get_source()
        config = preset.execution_config(build_tool_execution_config(self.ctx.config))
        tools = self._custom_tools(list(config.tool_names)) if config.tool_mode == "custom" else None
        result = await self.ctx.subagent_mgr.spawn(
            task,
            parent_id=source.internal_id,
            permission_session=source,
            title=preset.name if name is None else name,
            config=config,
            parent_tools=self.request.tool_set,
            tools=tools,
            preset_id=preset_id,
        )
        return json.dumps(result, ensure_ascii=False)


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
        result = {"agents": await self.ctx.subagent_mgr.list_agents(caller_id=source.internal_id)}
        return json.dumps(result, ensure_ascii=False)


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
            args["agent_id"],
            args["message"],
            steer=True,
        )
        return json.dumps(result, ensure_ascii=False)


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
            args["agent_id"],
            args["message"],
            steer=False,
        )
        return json.dumps(result, ensure_ascii=False)


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
        return json.dumps(result, ensure_ascii=False)
