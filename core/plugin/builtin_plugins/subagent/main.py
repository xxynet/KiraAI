import asyncio
import time
import uuid
from dataclasses import dataclass, field

from core.plugin import BasePlugin, register
from core.logging_manager import get_logger
from core.agent.agent_executor import AgentExecutor, AgentExecutionContext
from core.agent.tool import ToolSet
from core.prompt_manager import Prompt
from core.provider import LLMRequest
from core.chat.session import Session
from core.chat.message_utils import KiraMessageBatchEvent
from core.adapter.adapter_info import AdapterInfo

sub_logger = get_logger("subagent", "magenta")


@dataclass
class SubAgentConfig:
    subagent_id: str
    name: str
    description: str
    persona: str = ""
    tools: list[str] = field(default_factory=list)
    max_steps: int = 3
    timeout: float = 60.0


_STUB_ADAPTER = AdapterInfo(
    enabled=True,
    adapter_id="subagent",
    name="subagent",
    platform="subagent",
    description="SubAgent stub adapter",
)


def _code_expert() -> SubAgentConfig:
    return SubAgentConfig(
        subagent_id="code_expert",
        name="代码专家",
        description="擅长编写、审查、重构和解释代码",
        persona=(
            "你是一位资深软件工程师，擅长代码审查、Bug 定位、重构和技术方案评估。"
            "优先给出可运行的代码示例，指出潜在风险，保持代码风格一致。"
        ),
        tools=["read_file", "write_file"],
        max_steps=5,
        timeout=120.0,
    )


class SubAgentPlugin(BasePlugin):
    """SubAgent plugin: lets the main agent delegate tasks to specialized sub-agents."""

    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self._configs: dict[str, SubAgentConfig] = {}

    async def initialize(self):
        self._configs[_code_expert().subagent_id] = _code_expert()
        sub_logger.info(f"SubAgent plugin loaded, registered: {list(self._configs.keys())}")

    def register(self, config: SubAgentConfig):
        """Public API for other plugins to register their own sub-agents."""
        self._configs[config.subagent_id] = config

    @register.tool(
        "call_subagent",
        "调用一个已注册的子代理(subagent)完成子任务。子代理拥有独立的角色设定和工具集，会自主完成任务并返回结果。适用于代码审查、深度分析、翻译等需要专业能力的子任务。",
        {
            "type": "object",
            "properties": {
                "subagent_id": {"type": "string", "description": "子代理ID，例如 'code_expert'"},
                "task": {"type": "string", "description": "需要完成的具体任务描述"},
            },
            "required": ["subagent_id", "task"],
        },
    )
    async def call_subagent(self, event, subagent_id: str, task: str) -> str:
        config = self._configs.get(subagent_id)
        if not config:
            available = list(self._configs.keys())
            return f"Error: SubAgent '{subagent_id}' not found. Available: {available}"

        try:
            llm_model = self.ctx.provider_mgr.get_default_llm()
        except Exception:
            return "Error: No default LLM configured"

        # Build filtered tool set, never allow recursive subagent calls
        allowed = set(config.tools) - {"call_subagent"}
        full_set = self.ctx.llm_api.build_tool_set()
        tool_set = ToolSet()
        for tool in full_set.tools:
            if tool.name in allowed:
                tool_set.add(tool)

        agent_executor = AgentExecutor(self.ctx.llm_api, tool_set)

        messages = []
        system_prompts = []
        if config.persona:
            system_prompts.append(Prompt(config.persona, name="persona", source="system"))
        system_prompts.append(Prompt(
            "You are a specialized sub-agent. Focus on the assigned task and respond concisely. "
            "Return your final answer directly without extra meta-commentary.",
            name="subagent_role",
            source="system",
        ))

        llm_request = LLMRequest(messages=messages, tool_set=tool_set)
        llm_request.system_prompt.extend(system_prompts)
        llm_request.user_prompt.append(Prompt(task, name="task", source="user"))
        llm_request.assemble_prompt()

        cid = f"sub_{uuid.uuid4().hex[:12]}"
        stub_event = KiraMessageBatchEvent(
            message_types=[],
            timestamp=int(time.time()),
            session=Session(adapter_name="subagent", session_type="dm", session_id=cid),
            adapter=_STUB_ADAPTER,
        )

        agent_ctx = AgentExecutionContext(
            event=stub_event,
            request=llm_request,
            new_messages=[],
            model_group=[llm_model],
        )

        async def _run():
            final_text = ""
            async for step in agent_executor.run(agent_ctx, max_steps=config.max_steps):
                resp = step.llm_response
                if not resp:
                    break
                if resp.text_response:
                    final_text = resp.text_response
                if step.state == "error":
                    return f"Error: agent error - {step.err or 'unknown'}"
                if not step.has_tool_calls or step.is_final:
                    break
            return final_text

        try:
            result = await asyncio.wait_for(_run(), timeout=config.timeout)
        except asyncio.TimeoutError:
            return f"Error: SubAgent '{subagent_id}' timed out after {config.timeout}s"
        except Exception as e:
            sub_logger.error(f"SubAgent '{subagent_id}' error: {e}")
            return f"Error: SubAgent '{subagent_id}' failed: {e}"

        if result.startswith("Error:"):
            return result
        return f"SubAgent '{subagent_id}' result:\n{result}"
