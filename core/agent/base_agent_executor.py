from __future__ import annotations

from asyncio import Task, get_running_loop
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import deepcopy
from dataclasses import dataclass, field
from functools import partial
from typing import Generic, Literal, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError

from core.agent.message import OpenAIMessage
from core.agent.tool import ToolResult, ToolSet
from core.logging_manager import get_logger
from core.prompt_manager import Prompt
from core.provider import (
    LLMModelClient,
    LLMRequest,
    LLMResponse,
    ModelInfo,
    ProviderAPIError,
)
from core.utils.media_refs import MEDIA_REF_TYPE
from core.utils.tool_utils import BaseTool

from .config import AgentExecutionConfig, ToolExecutionConfig
from .tool_executor import ToolExecutor

logger = get_logger("agent_executor", "cyan")
llm_logger = get_logger("llm", "purple")


@dataclass
class BaseAgentExecutionContext:
    """Request and message state owned by one independent agent run."""

    request: LLMRequest
    model_group: list[LLMModelClient]
    new_messages: list[OpenAIMessage] = field(default_factory=list)

    def append_messages(self, *messages: OpenAIMessage) -> None:
        """Add shared message objects to the request and this turn's memory."""
        self.request.messages.extend(messages)
        self.new_messages.extend(messages)


@dataclass
class AgentStepResult:
    state: Literal["success", "stopped", "error"]
    step_index: int
    llm_response: LLMResponse | None
    new_messages: list[OpenAIMessage]
    is_final: bool
    has_tool_calls: bool
    model: ModelInfo
    err: str | None = None
    assistant_message: OpenAIMessage | None = None


ContextT = TypeVar("ContextT", bound=BaseAgentExecutionContext)


@dataclass
class _AgentRunState:
    config: AgentExecutionConfig
    pending_messages: list[OpenAIMessage] = field(default_factory=list)
    accepting_steering: bool = True


class BaseAgentExecutor(Generic[ContextT]):
    """Run one model/tool loop at a time without chat events or global plugin hooks."""

    def __init__(
        self,
        tool_set: ToolSet | None = None,
        *,
        config: AgentExecutionConfig | None = None,
    ):
        self.tool_executor = ToolExecutor()
        self.tool_set = tool_set
        self.config = config if config is not None else AgentExecutionConfig()
        self._run_state: _AgentRunState | None = None
        self._background_task: Task[AgentStepResult | None] | None = None

    def start(
        self,
        ctx: ContextT,
        *,
        on_result: Callable[[AgentStepResult], Awaitable[None]] | None = None,
    ) -> Task[AgentStepResult | None]:
        """Schedule a background loop and reserve it before returning the task.

        Call inside a running event loop. steer() may be used immediately after
        start(), including before the first model call. The async on_result
        callback receives every AgentStepResult, including the final one, and is
        awaited before the loop continues. The task returns the last result, or
        None for a zero-step run. Execution and callback exceptions propagate
        through the task and are also logged; cancellation propagates normally.
        The executor remains reserved until the task and its callbacks finish.
        """
        loop = get_running_loop()
        run_state = self._begin_run()
        coroutine = self._run_background(ctx, run_state, on_result)
        try:
            task = loop.create_task(coroutine, name=f"{type(self).__name__}.run")
        except BaseException:
            coroutine.close()
            self._release_run(run_state)
            raise
        self._background_task = task
        task.add_done_callback(partial(self._background_done, run_state))
        return task

    def _begin_run(self) -> _AgentRunState:
        if self._run_state is not None:
            raise RuntimeError("This agent executor is already running")
        config = self.config
        run_state = _AgentRunState(config=config, accepting_steering=config.max_steps > 0)
        self._run_state = run_state
        return run_state

    def _release_run(self, run_state: _AgentRunState) -> None:
        run_state.accepting_steering = False
        if self._run_state is run_state:
            self._run_state = None

    def _background_done(
        self, run_state: _AgentRunState, task: Task[AgentStepResult | None],
    ) -> None:
        # A task cancelled before its coroutine starts still owns its reservation.
        self._release_run(run_state)
        if self._background_task is task:
            self._background_task = None
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                logger.error(
                    "Background agent execution failed",
                    exc_info=(type(error), error, error.__traceback__),
                )

    async def _run_background(
        self, ctx: ContextT, run_state: _AgentRunState,
        on_result: Callable[[AgentStepResult], Awaitable[None]] | None,
    ) -> AgentStepResult | None:
        iterator = self._iterate_run(ctx, run_state)
        try:
            last_step = None
            async for step in iterator:
                last_step = step
                if on_result is not None:
                    await on_result(step)
            return last_step
        finally:
            try:
                await iterator.aclose()
            finally:
                self._release_run(run_state)

    def steer(self, message: str | OpenAIMessage) -> bool:
        """Queue a user instruction for the next model request of an active run.

        Call from the same event loop as run() or start(). One executor supports
        only one active run. Returns False if it is inactive or has started its final
        allowed step. Accepted messages are copied and recorded in both the
        request and new_messages when consumed.
        In-flight calls are not cancelled, and max_steps is never extended.
        Pending instructions are discarded if the run stops or fails first.
        """
        if isinstance(message, str):
            message = OpenAIMessage(role="user", content=message)
        elif not isinstance(message, OpenAIMessage):
            raise TypeError("steer message must be a string or OpenAIMessage")
        if message.role != "user":
            raise ValueError("steer message must have the user role")
        if not message.content or (isinstance(message.content, str) and not message.content.strip()):
            raise ValueError("steer message content must not be empty")

        run_state = self._run_state
        if run_state is None or not run_state.accepting_steering:
            return False
        run_state.pending_messages.append(deepcopy(message))
        return True

    @staticmethod
    def _apply_steering(ctx: ContextT, run_state: _AgentRunState) -> None:
        if run_state.pending_messages:
            messages = run_state.pending_messages
            run_state.pending_messages = []
            ctx.append_messages(*messages)

    def _get_log_id(self, ctx: ContextT) -> str:
        return "agent"

    def _get_final_step_hint(self) -> str:
        return (
            "<system_reminder>This is the final model call for this run. "
            "Conclude the task using the information already available. "
            "Any tool result will not invoke you again during this run. "
            "If information is insufficient, clearly state what is missing."
            "</system_reminder>"
        )

    async def _on_llm_response(self, ctx: ContextT, response: LLMResponse) -> bool:
        """Return True to stop before adding the response to message history."""
        return False

    async def _on_exception(
        self, ctx: ContextT, exception: Exception, *, source: str, comp_id: str | None,
    ) -> None:
        """Allow integrations to report failures without coupling the loop to events."""

    async def _execute_tools(
        self, ctx: ContextT, response: LLMResponse, config: ToolExecutionConfig,
    ) -> None:
        tool_set = self.tool_set if self.tool_set is not None else ctx.request.tool_set
        await self.tool_executor.execute_tools(
            response, tool_set=tool_set, config=config,
            invoke_tool=partial(self._invoke_tool, ctx),
            on_tool_result=partial(self._on_tool_result, ctx),
        )

    async def _invoke_tool(self, ctx: ContextT, tool: BaseTool, args: dict) -> object:
        return await tool.execute(**args)

    async def _on_tool_result(self, ctx: ContextT, result: ToolResult) -> bool:
        """Return False to stop the batch before recording this tool result."""
        return True

    @staticmethod
    def _build_tool_messages(tool_results: list[dict]) -> list[OpenAIMessage]:
        """Build the tool messages of one agent step from raw tool results.

        Media references embedded by tools (``kira_image_ref`` parts) are
        relocated into a single user message appended after the tool results:
        some providers reject image parts inside tool-role messages, while a
        user message carrying images is supported by every vision-capable
        provider. Both the request and the persisted history receive the same
        relocated shape, so replays stay consistent with what the model saw.
        """
        messages: list[OpenAIMessage] = []
        media_parts: list[dict] = []
        media_tool_names: list[str] = []
        for result in tool_results:
            content = result.get("content")
            if isinstance(content, list):
                text_parts = [
                    part for part in content
                    if not (isinstance(part, dict) and part.get("type") == MEDIA_REF_TYPE)
                ]
                refs = [
                    part for part in content
                    if isinstance(part, dict) and part.get("type") == MEDIA_REF_TYPE
                ]
                if refs:
                    media_parts.extend(refs)
                    tool_name = result.get("name") or "unknown_tool"
                    if tool_name not in media_tool_names:
                        media_tool_names.append(tool_name)
                    # Refs were the only non-text parts, so joining the rest
                    # always restores the original plain-text tool output.
                    tool_content = "".join(
                        part.get("text", "") if isinstance(part, dict) else str(part)
                        for part in text_parts
                    )
                    messages.append(OpenAIMessage(
                        role="tool",
                        tool_call_id=result.get("tool_call_id"),
                        name=result.get("name"),
                        content=tool_content,
                    ))
                    continue
            messages.append(OpenAIMessage(**result))

        if media_parts:
            joined_names = ", ".join(media_tool_names)
            messages.append(OpenAIMessage(
                role="user",
                content=[
                    {"type": "text", "text": f"Media returned by tool call(s): {joined_names}"},
                    *media_parts,
                ],
            ))
        return messages

    async def run(
        self,
        ctx: ContextT,
    ) -> AsyncIterator[AgentStepResult]:
        """Run one loop; overlapping calls on this executor raise RuntimeError."""
        run_state = self._begin_run()
        iterator = self._iterate_run(ctx, run_state)
        try:
            async for result in iterator:
                yield result
        finally:
            try:
                await iterator.aclose()
            finally:
                self._release_run(run_state)

    async def _iterate_run(
        self, ctx: ContextT, run_state: _AgentRunState,
    ) -> AsyncIterator[AgentStepResult]:
        iterator = self._run(ctx, run_state)
        try:
            async for result in iterator:
                if result.is_final:
                    run_state.accepting_steering = False
                yield result
        finally:
            run_state.accepting_steering = False
            await iterator.aclose()

    async def _run(
        self, ctx: ContextT, run_state: _AgentRunState,
    ) -> AsyncIterator[AgentStepResult]:
        request = ctx.request
        model_group = ctx.model_group
        config = run_state.config
        max_steps = config.max_steps
        tool_config = config.tool_config

        if not model_group:
            raise ValueError("model_group must be a non-empty list of LLMModelClient")

        llm_model = model_group[0]

        sid = self._get_log_id(ctx)

        provider_name = llm_model.model.provider_name
        model_name = llm_model.model.model_name
        llm_logger.info(f"[{sid}] Running agent using {model_name} ({provider_name})")

        for step in range(max_steps):
            step_index = step + 1

            state: Literal["success", "stopped", "error"] = "success"
            err = ""
            is_final = step_index == max_steps
            run_state.accepting_steering = not is_final
            self._apply_steering(ctx, run_state)

            # Inject last-step hint so the LLM knows to wrap up
            if is_final:
                final_step_prompt = Prompt(
                    name="final_step_hint",
                    source="system",
                    persist=False,
                    content=self._get_final_step_hint(),
                )
                request.messages.append(OpenAIMessage(
                    role="user",
                    content=final_step_prompt.to_string(),
                ))

            # Try models in order, failover to next on provider/API errors.
            # Only catch provider-level exceptions (network, timeout, API status).
            # Programming errors (TypeError, ValueError, etc.) should propagate.
            llm_resp = None
            last_exc: Exception | None = None
            for model_idx, model in enumerate(model_group):
                provider_name = model.model.provider_name
                model_name = model.model.model_name
                try:
                    self._apply_steering(ctx, run_state)
                    llm_resp = await model.chat(request)
                    if model_idx > 0:
                        llm_logger.info(f"[{sid}] Successfully switched to model: {model_name} ({provider_name})")
                    break
                except (APIStatusError, APITimeoutError, APIConnectionError, ProviderAPIError) as e:
                    last_exc = e
                    logger.error(f"[{sid}] Model {model.model.model_name} failed: {type(e).__name__}: {e}")
                    if model_idx < len(model_group) - 1:
                        next_model = model_group[model_idx + 1]
                        llm_logger.warning(f"[{sid}] Falling back to next model: {next_model.model.model_name} ({next_model.model.provider_name})")
                        continue
                    else:
                        err = (
                            f"All models in the group failed to respond. "
                            f"{type(last_exc).__name__}: {last_exc}"
                        )
                        llm_resp = LLMResponse(f"[ProviderError] {err}", status="error")
                        state = "error"
                        is_final = True
                        await self._on_exception(
                            ctx, last_exc, source="provider", comp_id=model.model.provider_name,
                        )

            if llm_resp.status == "error":
                state = "error"
                err = err or llm_resp.text_response
            has_tool_calls = llm_resp.status != "error" and bool(llm_resp.tool_calls)

            llm_resp.agent_step_index = step_index
            llm_logger.debug(llm_resp)

            cached_tokens_info = ""
            if llm_resp.cached_tokens is not None:
                cached_tokens_info = f", Cached tokens: {llm_resp.cached_tokens}"
                if llm_resp.input_tokens:
                    cache_hit_rate = llm_resp.cached_tokens / llm_resp.input_tokens * 100
                    cached_tokens_info += f" (Cache hit rate: {cache_hit_rate:.1f}%)"

            llm_logger.info(
                f"[{sid}] Time consumed: {llm_resp.time_consumed}s, Input tokens: {llm_resp.input_tokens}, output tokens: {llm_resp.output_tokens}{cached_tokens_info}, step: {step_index}/{max_steps}"
            )

            if await self._on_llm_response(ctx, llm_resp):
                yield AgentStepResult(
                    state="stopped",
                    step_index=step_index,
                    llm_response=llm_resp,
                    new_messages=ctx.new_messages,
                    is_final=True,
                    has_tool_calls=has_tool_calls,
                    model=model.model,
                )
                return

            if not has_tool_calls:
                is_final = is_final or state == "error" or not run_state.pending_messages
                assistant_content = llm_resp.text_response or ""
                reasoning = llm_resp.reasoning_content or ""
                msg = OpenAIMessage(
                    role="assistant",
                    content=assistant_content,
                    reasoning_content=reasoning
                )
                ctx.append_messages(msg)
                yield AgentStepResult(
                    state=state,
                    assistant_message=msg,
                    err=err,
                    step_index=step_index,
                    llm_response=llm_resp,
                    new_messages=ctx.new_messages,
                    is_final=is_final,
                    has_tool_calls=has_tool_calls,
                    model=model.model,
                )
                if is_final:
                    return
                continue

            assistant_content = llm_resp.text_response or ""
            reasoning = llm_resp.reasoning_content or ""

            try:
                await self._execute_tools(ctx, llm_resp, tool_config)
            except Exception as e:
                logger.error(f"[{sid}] Tool execution failed: {e}")
                await self._on_exception(ctx, e, source="tool", comp_id=None)
                raise
            # An integration may stop tool execution with partial results. Keep the
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
            tool_msgs = self._build_tool_messages(llm_resp.tool_results)
            ctx.append_messages(msg, *tool_msgs)

            yield AgentStepResult(
                state=state,
                assistant_message=msg,
                err=err,
                step_index=step_index,
                llm_response=llm_resp,
                new_messages=ctx.new_messages,
                is_final=is_final,
                has_tool_calls=has_tool_calls,
                model=model.model,
            )
            if is_final:
                return
