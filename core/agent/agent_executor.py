from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional, TYPE_CHECKING, Union, Literal

from openai import APIStatusError, APITimeoutError, APIConnectionError

from core.logging_manager import get_logger
from core.llm_client import LLMClient
from core.provider import LLMRequest, LLMResponse, LLMModelClient
from core.agent.tool import ToolSet
from core.plugin.plugin_handlers import event_handler_reg, EventType

if TYPE_CHECKING:
    from core.chat.message_utils import KiraMessageBatchEvent


logger = get_logger("agent_executor", "cyan")
llm_logger = get_logger("llm", "purple")


@dataclass
class AgentExecutionContext:
    event: KiraMessageBatchEvent
    request: LLMRequest
    llm_model: LLMModelClient
    new_memory: NewMemory


@dataclass
class AgentStepResult:
    state: Literal["success", "stopped", "error"]
    step_index: int
    llm_response: Optional[LLMResponse]
    new_memory: NewMemory
    is_final: bool
    has_tool_calls: bool
    err: Optional[str] = None


@dataclass
class NewMemory:
    memory_list: list = field(default_factory=list)

    def user(self, content: Union[str, dict]):
        self.memory_list.append(
            {
                "role": "user",
                "content": content
            }
        )

    # Add reasoning_content param, defaults to blank string，to satisfy the requirements of Kimi API
    def assistant(self, content: str, tool_calls: Optional[list[dict]] = None, reasoning_content: str = ""):
        if not tool_calls:
            self.memory_list.append(
                {
                    "role": "assistant",
                    "content": content,
                    "reasoning_content": reasoning_content
                }
            )
        else:
            self.memory_list.append(
                {
                    "role": "assistant",
                    "content": content,
                    "tool_calls": tool_calls,
                    "reasoning_content": reasoning_content
                }
            )

    def tool(self, tool_results: list[dict]):
        self.memory_list.extend(tool_results)
        # self.memory_list.append({
        #     "role": "tool",
        #     "tool_call_id": tool_call_id,
        #     "name": name,
        #     "content": str(result)
        # })


class AgentExecutor:
    def __init__(self, llm_api: LLMClient, tool_set: Optional[ToolSet] = None):
        self.llm_api = llm_api
        self.tool_set = tool_set

    async def run(
        self,
        ctx: AgentExecutionContext,
        max_steps: int,
    ) -> AsyncIterator[AgentStepResult]:
        event = ctx.event
        request = ctx.request
        llm_model = ctx.llm_model

        # Session Info
        sid = ctx.event.sid

        provider_name = llm_model.model.provider_name
        model_id = llm_model.model.model_id
        llm_logger.info(f"[{sid}] Running agent using {model_id} ({provider_name})")

        for step in range(max_steps):
            step_index = step + 1

            state: Literal["success", "stopped", "error"] = "success"
            err = ""
            is_final = step_index == max_steps

            try:
                llm_resp = await llm_model.chat(request)
            except Exception as e:
                logger.error(f"{type(e).__name__}: {e}")
                llm_resp = LLMResponse(f"[{type(e).__name__}] {e}")

                state = "error"
                err = f"{type(e).__name__}: {e}"
                is_final = True

            has_tool_calls = bool(llm_resp.tool_calls)

            llm_resp.agent_step_index = step_index
            llm_logger.debug(llm_resp)
            llm_logger.info(
                f"[{sid}] Time consumed: {llm_resp.time_consumed}s, Input tokens: {llm_resp.input_tokens}, output tokens: {llm_resp.output_tokens}, step: {step_index}/{max_steps}"
            )

            llm_resp_handlers = event_handler_reg.get_handlers(event_type=EventType.ON_LLM_RESPONSE)
            for handler in llm_resp_handlers:
                await handler.exec_handler(event, llm_resp)
                if event.is_stopped:
                    is_final = True
                    logger.info("Event stopped")
                    yield AgentStepResult(
                        state="stopped",
                        step_index=step_index,
                        llm_response=llm_resp,
                        new_memory=ctx.new_memory,
                        is_final=is_final,
                        has_tool_calls=has_tool_calls,
                    )
                    return

            if not has_tool_calls:
                is_final = True
                assistant_content = llm_resp.text_response or ""
                reasoning = llm_resp.reasoning_content or ""
                # Add reasoning_content
                request.messages.append(
                    {
                        "role": "assistant",
                        "content": assistant_content,
                        "reasoning_content": reasoning
                    }
                )
                ctx.new_memory.assistant(assistant_content, reasoning_content=reasoning)
                yield AgentStepResult(
                    state=state,
                    err=err,
                    step_index=step_index,
                    llm_response=llm_resp,
                    new_memory=ctx.new_memory,
                    is_final=is_final,
                    has_tool_calls=has_tool_calls,
                )
                return

            assistant_content = llm_resp.text_response or ""
            reasoning = llm_resp.reasoning_content or ""

            await self.llm_api.execute_tool(event, llm_resp, tool_set=self.tool_set)
            # Add reasoning_content
            request.messages.append(
                {
                    "role": "assistant",
                    "content": assistant_content,
                    "tool_calls": llm_resp.tool_calls,
                    "reasoning_content": reasoning
                }
            )
            ctx.new_memory.assistant(assistant_content, llm_resp.tool_calls, reasoning_content=reasoning)
            request.messages.extend(llm_resp.tool_results)
            ctx.new_memory.tool(llm_resp.tool_results)

            yield AgentStepResult(
                state=state,
                err=err,
                step_index=step_index,
                llm_response=llm_resp,
                new_memory=ctx.new_memory,
                is_final=is_final,
                has_tool_calls=has_tool_calls,
            )
            if is_final:
                return
