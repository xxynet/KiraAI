from __future__ import annotations

from dataclasses import dataclass
from typing import AsyncIterator, Optional, TYPE_CHECKING, Literal

from openai import APIStatusError, APITimeoutError, APIConnectionError

from core.logging_manager import get_logger
from core.llm_client import LLMClient
from core.provider import LLMRequest, LLMResponse, LLMModelClient
from core.agent.tool import ToolSet
from core.agent.message import OpenAIMessage
from core.plugin.plugin_handlers import event_handler_reg, EventType

if TYPE_CHECKING:
    from core.chat.message_utils import KiraMessageBatchEvent


logger = get_logger("agent_executor", "cyan")
llm_logger = get_logger("llm", "purple")


@dataclass
class AgentExecutionContext:
    event: KiraMessageBatchEvent
    request: LLMRequest
    new_messages: list[OpenAIMessage]
    model_group: list[LLMModelClient]


@dataclass
class AgentStepResult:
    state: Literal["success", "stopped", "error"]
    step_index: int
    llm_response: Optional[LLMResponse]
    new_messages: list[OpenAIMessage]
    is_final: bool
    has_tool_calls: bool
    model_id: str = ""
    err: Optional[str] = None


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
        model_group = ctx.model_group

        if not model_group:
            raise ValueError("AgentExecutionContext.model_group must be a non-empty list of LLMModelClient")

        llm_model = model_group[0]

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

            # Inject last-step hint so the LLM knows to wrap up
            if is_final:
                request.messages.append(OpenAIMessage(
                    role="system",
                    content="⚠️ This is your last response opportunity in this turn. There will be no more conversation turns after this. If you need to communicate anything to the user, output it directly in this response. If you choose to end silently (<msg/>), no output is needed."
                ))

            # Try models in order, failover to next on provider/API errors.
            # Only catch provider-level exceptions (network, timeout, API status).
            # Programming errors (TypeError, ValueError, etc.) should propagate.
            llm_resp = None
            last_exc: Optional[Exception] = None
            for model_idx, model in enumerate(model_group):
                try:
                    llm_resp = await model.chat(request)
                    llm_model = model
                    if model_idx > 0:
                        provider_name = llm_model.model.provider_name
                        model_id = model.model.model_id
                        llm_logger.info(f"[{sid}] Successfully switched to model: {model_id} ({provider_name})")
                    break
                except (APIStatusError, APITimeoutError, APIConnectionError) as e:
                    last_exc = e
                    logger.error(f"[{sid}] Model {model.model.model_id} failed: {type(e).__name__}: {e}")
                    if model_idx < len(model_group) - 1:
                        next_model = model_group[model_idx + 1]
                        llm_logger.warning(f"[{sid}] Falling back to next model: {next_model.model.model_id}")
                        continue
                    else:
                        llm_resp = LLMResponse(f"[ProviderError] All models in the group failed to respond. {type(last_exc).__name__}: {last_exc}")
                        state = "error"
                        err = f"All models failed. Last error: {type(last_exc).__name__}: {last_exc}"
                        is_final = True

            has_tool_calls = bool(llm_resp.tool_calls)

            llm_resp.agent_step_index = step_index
            llm_logger.debug(llm_resp)

            cached_tokens_info = f", Cached tokens: {llm_resp.cached_tokens}" if llm_resp.cached_tokens is not None else ""

            llm_logger.info(
                f"[{sid}] Time consumed: {llm_resp.time_consumed}s, Input tokens: {llm_resp.input_tokens}, output tokens: {llm_resp.output_tokens}{cached_tokens_info}, step: {step_index}/{max_steps}"
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
                        new_messages=ctx.new_messages,
                        is_final=is_final,
                        has_tool_calls=has_tool_calls,
                        model_id=model_id,
                    )
                    return

            if not has_tool_calls:
                is_final = True
                assistant_content = llm_resp.text_response or ""
                reasoning = llm_resp.reasoning_content or ""
                msg = OpenAIMessage(
                    role="assistant",
                    content=assistant_content,
                    reasoning_content=reasoning
                )
                request.messages.append(msg)
                ctx.new_messages.append(msg)
                yield AgentStepResult(
                    state=state,
                    err=err,
                    step_index=step_index,
                    llm_response=llm_resp,
                    new_messages=ctx.new_messages,
                    is_final=is_final,
                    has_tool_calls=has_tool_calls,
                    model_id=model_id,
                )
                return

            assistant_content = llm_resp.text_response or ""
            reasoning = llm_resp.reasoning_content or ""

            await self.llm_api.execute_tool(event, llm_resp, tool_set=self.tool_set)
            # An ON_TOOL_RESULT handler may stop the event mid multi-tool-call turn,
            # leaving execute_tool to produce only partial tool_results. Keep the
            # assistant message's tool_calls consistent with the tool_results actually
            # produced (matched by id), so history never contains an assistant message
            # with unanswered tool_calls (which would 400 the next OpenAI request).
            answered_ids = {r.get("tool_call_id") for r in llm_resp.tool_results}
            answered_tool_calls = [
                tc for tc in llm_resp.tool_calls if tc.get("id") in answered_ids
            ]
            msg = OpenAIMessage(
                role="assistant",
                content=assistant_content,
                tool_calls=answered_tool_calls,
                reasoning_content=reasoning
            )
            request.messages.append(msg)
            ctx.new_messages.append(msg)
            tool_msgs = [OpenAIMessage(**r) for r in llm_resp.tool_results]
            request.messages.extend(tool_msgs)
            ctx.new_messages.extend(tool_msgs)

            yield AgentStepResult(
                state=state,
                err=err,
                step_index=step_index,
                llm_response=llm_resp,
                new_messages=ctx.new_messages,
                is_final=is_final,
                has_tool_calls=has_tool_calls,
                model_id=model_id,
            )
            if is_final:
                return
