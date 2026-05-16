from __future__ import annotations

import asyncio
import copy
import time
import uuid
from typing import Optional, TYPE_CHECKING

from core.logging_manager import get_logger
from core.agent.agent_executor import AgentExecutor, AgentExecutionContext, NewMemory
from core.agent.tool import ToolSet
from core.prompt_manager import Prompt
from core.provider.llm_model import LLMRequest
from core.chat.message_utils import KiraMessageBatchEvent
from core.chat.session import Session
from core.adapter.adapter_info import AdapterInfo

from .models import SubAgentConfig, SubAgentRequest, SubAgentResponse, ParentContextStrategy

if TYPE_CHECKING:
    from core.provider import ProviderManager, LLMModelClient, LLMResponse
    from core.llm_client import LLMClient
    from core.prompt_manager import PromptManager

logger = get_logger("subagent", "magenta")
llm_logger = get_logger("llm", "purple")


class SubAgent:
    """SubAgent 实体：封装独立的 Persona、工具集、模型和记忆"""

    def __init__(
        self,
        config: SubAgentConfig,
        provider_mgr: ProviderManager,
        llm_api: LLMClient,
        prompt_manager: Optional[PromptManager] = None,
    ):
        self.config = config
        self.provider_mgr = provider_mgr
        self.llm_api = llm_api
        self.prompt_manager = prompt_manager

        self.session_id = None
        self._memory: list = []
        self._lock = asyncio.Lock()

    def _get_model_client(self) -> Optional[LLMModelClient]:
        if self.config.model_uuid:
            parts = self.config.model_uuid.split(":")
            if len(parts) < 2:
                logger.error(
                    f"Invalid model_uuid format '{self.config.model_uuid}', "
                    f"expected 'provider_id:model_id'"
                )
                return None
            provider_id = parts[0]
            model_id = ":".join(parts[1:])
            try:
                client = self.provider_mgr.get_model_client(provider_id, model_id)
                if client is None:
                    logger.error(f"Model '{self.config.model_uuid}' not found in provider manager")
                return client
            except Exception as e:
                logger.error(f"Failed to get model {self.config.model_uuid}: {e}")
                return None
        return self.provider_mgr.get_default_llm()

    def _build_tool_set(self) -> ToolSet:
        tool_set = ToolSet()
        if not self.config.tools:
            return tool_set
        for tool_name in self.config.tools:
            if tool_name in self.llm_api.tools_functions:
                # 内置 tool，通过 ToolSet 包装后注册
                from core.utils.tool_utils import BaseTool

                def make_tool(name: str, llm_api):
                    class DynamicTool(BaseTool):
                        name = name
                        description = ""
                        parameters = {}

                        async def execute(self, event, **kwargs):
                            func = llm_api.tools_functions.get(name)
                            if func:
                                return await func(event, **kwargs)
                            return {"error": f"Tool {name} not found"}

                    return DynamicTool

                DynamicTool = make_tool(tool_name, self.llm_api)

                # 尝试从 tools_definitions 获取描述和参数
                for td in self.llm_api.tools_definitions:
                    if td.get("function", {}).get("name") == tool_name:
                        DynamicTool.description = td["function"].get("description", "")
                        DynamicTool.parameters = td["function"].get("parameters", {})
                        break
                tool_set.add(DynamicTool())
        return tool_set

    def _build_system_prompt(self) -> list[Prompt]:
        prompts: list[Prompt] = []
        if self.config.persona:
            prompts.append(Prompt(self.config.persona, name="persona", source="system"))
        prompts.append(
            Prompt(
                "You are a specialized sub-agent. Focus on your assigned task and respond concisely.",
                name="role",
                source="system",
            )
        )
        return prompts

    def _prepare_context(self, request: SubAgentRequest) -> list[dict]:
        strategy = request.parent_context_strategy
        messages = []

        if strategy == ParentContextStrategy.NONE:
            pass
        elif strategy == ParentContextStrategy.SUMMARY:
            summary = request.metadata.get("context_summary", "")
            if summary:
                messages.append({"role": "system", "content": f"Context summary from parent agent: {summary}"})
        elif strategy == ParentContextStrategy.FULL:
            history = request.metadata.get("context_history", [])
            max_tokens = request.max_tokens or 4000
            # 简单截断：直接取历史后段
            # TODO: 更精确的 token 计算截断
            messages.extend(history[-20:] if len(history) > 20 else history)
        elif strategy == ParentContextStrategy.SELECTIVE:
            selective = request.metadata.get("context_selective", [])
            # TODO: 根据消息 ID 匹配提取
            if selective:
                messages.append({"role": "system", "content": f"Selected context: {selective}"})

        return messages

    async def execute(self, request: SubAgentRequest) -> SubAgentResponse:
        if self._lock.locked():
            return SubAgentResponse(
                correlation_id=request.correlation_id,
                status="cancelled",
                err="SubAgent is busy",
            )

        async with self._lock:
            return await self._do_execute(request)

    async def _do_execute(self, request: SubAgentRequest) -> SubAgentResponse:
        start_time = time.time()
        correlation_id = request.correlation_id

        try:
            llm_model = self._get_model_client()
            if not llm_model:
                return SubAgentResponse(
                    correlation_id=correlation_id,
                    status="model_error",
                    err="No available LLM model",
                )

            tool_set = self._build_tool_set()
            agent_executor = AgentExecutor(self.llm_api, tool_set)

            # 构建请求
            context_messages = self._prepare_context(request)
            system_prompts = self._build_system_prompt()

            allowed_tool_names = {t.name for t in tool_set.tools}
            filtered_tools_definitions = [
                td for td in self.llm_api.tools_definitions
                if td.get("function", {}).get("name") in allowed_tool_names
            ]
            filtered_tool_funcs = {
                name: func for name, func in self.llm_api.tools_functions.items()
                if name in allowed_tool_names
            }

            llm_request = LLMRequest(
                messages=context_messages[:],
                tools=copy.deepcopy(filtered_tools_definitions),
                tool_funcs=filtered_tool_funcs,
                tool_set=tool_set,
            )
            llm_request.system_prompt.extend(system_prompts)
            llm_request.user_prompt.append(Prompt(request.content, name="task", source="user"))
            llm_request.assemble_prompt()
            # 合并 tool_set 中的工具
            llm_request.tools.extend(llm_request.tool_set.to_list())

            new_memory = NewMemory()
            new_memory.user(request.content)

            # 构造最小 stub event，满足 AgentExecutor 对 event.sid / event.is_stopped 的访问
            # 以及 execute_tool 时 tool 函数对 event.adapter 的访问
            stub_session = Session(
                adapter_name="subagent",
                session_type="dm",
                session_id=correlation_id,
            )
            stub_adapter = AdapterInfo(
                enabled=True,
                adapter_id="subagent",
                name="subagent",
                platform="subagent",
                description="SubAgent stub adapter",
            )
            stub_event = KiraMessageBatchEvent(
                message_types=[],
                timestamp=int(time.time()),
                session=stub_session,
                adapter=stub_adapter,
            )

            agent_ctx = AgentExecutionContext(
                event=stub_event,
                request=llm_request,
                llm_model=llm_model,
                new_memory=new_memory,
            )

            max_agent_steps = self.config.max_tool_loop + 1
            final_text = ""
            final_reasoning = ""
            total_input_tokens = 0
            total_output_tokens = 0
            has_error = False
            error_msg = ""

            timeout = self.config.timeout
            deadline = time.time() + timeout
            timed_out = False
            try:
                async for step in self._run_agent_executor(agent_executor, agent_ctx, max_agent_steps):
                    # 超时短路：每步之间检查，避免多烧 token
                    if time.time() > deadline:
                        timed_out = True
                        break

                    # 检查外部取消信号
                    if stub_event.is_stopped:
                        break

                    llm_resp = step.llm_response
                    if not llm_resp:
                        has_error = True
                        error_msg = "Empty LLM response"
                        break

                    if llm_resp.input_tokens:
                        total_input_tokens += llm_resp.input_tokens
                    if llm_resp.output_tokens:
                        total_output_tokens += llm_resp.output_tokens

                    if step.state == "error":
                        has_error = True
                        error_msg = step.err or "Unknown agent error"
                        break

                    if llm_resp.text_response:
                        final_text = llm_resp.text_response
                        final_reasoning = llm_resp.reasoning_content or ""

                    if not step.has_tool_calls or step.is_final:
                        break
            except asyncio.CancelledError:
                raise
            except asyncio.TimeoutError:
                timed_out = True

            if timed_out:
                time_consumed = round(time.time() - start_time, 3)
                logger.warning(
                    f"SubAgent '{self.config.subagent_id}' execution timed out after {timeout}s "
                    f"(correlation_id={correlation_id})"
                )
                return SubAgentResponse(
                    correlation_id=correlation_id,
                    status="timeout",
                    err=f"SubAgent execution timed out after {timeout}s",
                    metadata={
                        "time_consumed": time_consumed,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                )

            # 保存记忆
            self._memory.extend(new_memory.memory_list)

            time_consumed = round(time.time() - start_time, 3)

            if has_error:
                status = "tool_error" if "tool" in error_msg.lower() else "model_error"
                return SubAgentResponse(
                    correlation_id=correlation_id,
                    status=status,
                    result=final_text,
                    err=error_msg,
                    metadata={
                        "time_consumed": time_consumed,
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                    },
                )

            return SubAgentResponse(
                correlation_id=correlation_id,
                status="success",
                result=final_text,
                metadata={
                    "time_consumed": time_consumed,
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "reasoning_content": final_reasoning,
                },
            )

        except Exception as e:
            logger.error(f"SubAgent '{self.config.subagent_id}' execution error: {e}")
            return SubAgentResponse(
                correlation_id=correlation_id,
                status="model_error",
                err=str(e),
                metadata={"time_consumed": round(time.time() - start_time, 3)},
            )

    def fetch_memory(self) -> list:
        return copy.deepcopy(self._memory)

    def write_memory(self, memory: list):
        # SessionManager 传入的是 list[list[dict]] 格式，需要扁平化
        flat = []
        for chunk in memory:
            copied = copy.deepcopy(chunk)
            if isinstance(copied, list):
                flat.extend(copied)
            else:
                flat.append(copied)
        self._memory = flat

    def update_memory(self, new_chunk: list):
        # SessionManager 传入的 new_chunk 可能是 list[dict]
        copied = copy.deepcopy(new_chunk)
        if isinstance(copied, list):
            self._memory.extend(copied)
        else:
            self._memory.append(copied)

    async def _run_agent_executor(self, agent_executor, agent_ctx, max_agent_steps):
        """逐步 yield agent_executor.run 的结果，使外层 asyncio.wait_for 能在每步之间中断"""
        async for step in agent_executor.run(agent_ctx, max_steps=max_agent_steps):
            yield step
