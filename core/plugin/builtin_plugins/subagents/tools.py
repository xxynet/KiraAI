import json
from typing import ClassVar

from core.agent.config import AgentExecutionConfig, SubAgentConfig
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
    description = "Delegate an independent task to a background agent. Returns immediately; results are delivered to this session as a system notice after each turn."
    parameters: ClassVar[dict] = {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "Complete, self-contained task instructions"},
            "name": {"type": "string", "description": "Short session title"},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 50},
            "tool_mode": {"type": "string", "enum": ["inherit", "exclude", "custom"]},
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Excluded tools or the custom tool list",
            },
        },
        "required": ["task"],
    }

    async def execute(self, event, **args):
        source = await self._get_source()
        mode = args.get("tool_mode", "inherit")
        names = args.get("tools", [])
        if not isinstance(names, list) or any(not isinstance(name, str) or not name for name in names):
            raise ValueError("tools must be a list of non-empty tool names")
        tools = self._custom_tools(names) if mode == "custom" else None
        max_steps = args.get("max_steps", self.ctx.config.get_config("bot_config.agent.max_tool_loop", 5))
        if not isinstance(max_steps, int) or isinstance(max_steps, bool) or not 1 <= max_steps <= 50:
            raise ValueError("max_steps must be an integer between 1 and 50")
        result = await self.ctx.subagent_mgr.spawn(
            args["task"],
            parent_id=source.internal_id,
            permission_session=source,
            title=args.get("name", ""),
            config=SubAgentConfig(
                execution=AgentExecutionConfig(
                    max_steps=max_steps,
                    tool_config=build_tool_execution_config(self.ctx.config),
                ),
                tool_mode=mode,
                tool_names=tuple(names) if mode == "custom" else (),
                excluded_tools=tuple(names) if mode == "exclude" else (),
            ),
            parent_tools=self.request.tool_set,
            tools=tools,
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
