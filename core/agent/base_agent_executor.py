from __future__ import annotations

from asyncio import (
    FIRST_COMPLETED,
    Event,
    Task,
    create_task,
    gather,
    get_running_loop,
    wait,
)
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from copy import copy, deepcopy
from dataclasses import dataclass, field
from functools import partial
from typing import Generic, Literal, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError

from core.agent.message import OpenAIMessage
from core.agent.tool import ToolSet
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

from .config import AgentExecutionConfig
from .hook_context import ToolCallContext
from .hooks import AgentExecutionHooks
from .tool_executor import ToolExecutor

logger = get_logger("agent_executor", "cyan")
llm_logger = get_logger("llm", "purple")


@dataclass
class BaseAgentExecutionContext:
    """Canonical conversation messages shared by all turns of one agent session."""

    messages: list[OpenAIMessage] = field(default_factory=list)
    new_messages: list[OpenAIMessage] = field(default_factory=list)

    def __post_init__(self):
        self.messages[:] = [
            message if isinstance(message, OpenAIMessage) else OpenAIMessage(**message)
            for message in self.messages
        ]

    def append_messages(self, *messages: OpenAIMessage) -> None:
        """Append the same message objects to session history and turn memory."""
        self.messages.extend(messages)
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
AgentExecutorState = Literal["idle", "running", "stopping", "done"]


@dataclass
class _AgentRunState:
    config: AgentExecutionConfig
    model_group: list[LLMModelClient]
    request: LLMRequest
    pending_messages: list[OpenAIMessage] = field(default_factory=list)
    accepting_steering: bool = True
    abort_requested: Event = field(default_factory=Event)
    step_index: int = 0
    model: ModelInfo | None = None


class BaseAgentExecutor(Generic[ContextT]):
    """Execute agent turns with shared steering and queued follow-ups."""

    def __init__(
        self,
        model_group: list[LLMModelClient],
        *,
        context: ContextT,
        request: LLMRequest | None = None,
        hooks: AgentExecutionHooks[ContextT] | None = None,
        tool_executor: ToolExecutor | None = None,
        config: AgentExecutionConfig | None = None,
        on_result: Callable[[AgentStepResult], Awaitable[None]] | None = None,
    ):
        self.model_group = model_group.copy()
        self.context = context
        self.request = request
        self.hooks = hooks if hooks is not None else AgentExecutionHooks()
        self.config = config if config is not None else AgentExecutionConfig()
        self.on_result = on_result
        self.tool_executor = tool_executor if tool_executor is not None else ToolExecutor()
        self._run_state: _AgentRunState | None = None
        self._background_task: Task[AgentStepResult | None] | None = None
        self._queued_messages: deque[OpenAIMessage] = deque()
        self._last_turn_messages: list[OpenAIMessage] | None = None
        self._last_turn_message_count = 0
        self._state: AgentExecutorState = "idle"

    @property
    def state(self) -> AgentExecutorState:
        """Lifecycle across all queued turns; done includes stopped and failed runs."""
        return self._state

    def start(self) -> Task[AgentStepResult | None]:
        """Immediately schedule background execution on the configured context.

        on_result is configured on the executor and receives each step once.
        The configured request supplies tools and non-history options for each
        turn; history comes from context.
        Queued messages start new turns on the same context with fresh budgets.
        The returned task resolves to the last emitted step, or None if no model
        calls ran. Task cancellation and exceptions discard pending follow-ups.
        Execution and callback exceptions remain on the task and are logged.
        abort() waits for the current call and delivers a final stopped result
        with no response text to send.
        """
        return self._start()

    def _start(
        self, message: OpenAIMessage | None = None,
    ) -> Task[AgentStepResult | None]:
        loop = get_running_loop()
        ctx = self.context
        previous_state = self._state
        run_state = self._begin_run()
        previous_new_messages = ctx.new_messages
        if message is not None:
            ctx.new_messages = []
            run_state.pending_messages.append(message)
        coroutine = self._run_background(ctx, run_state)
        try:
            task = loop.create_task(coroutine, name=f"{type(self).__name__}.run")
        except BaseException:
            coroutine.close()
            self._release_run(run_state)
            self._state = previous_state
            ctx.new_messages = previous_new_messages
            raise
        self._background_task = task
        task.add_done_callback(partial(self._background_done, run_state))
        return task

    def _build_request(
        self, tool_set: ToolSet | None,
    ) -> LLMRequest:
        ctx, request = self.context, self.request
        if request is None:
            return LLMRequest(messages=ctx.messages.copy(), tool_set=tool_set)
        built_request = copy(request)
        built_request.messages = ctx.messages.copy()
        built_request.user_prompt = request.user_prompt.copy()
        built_request.system_prompt = request.system_prompt.copy()
        built_request.tool_set = tool_set
        built_request.tools = tool_set.to_list() if tool_set is not None else None
        if built_request.tool_choice is None:
            built_request.tool_choice = "auto" if built_request.tools else "none"
        return built_request

    def _create_run_state(self) -> _AgentRunState:
        config = self.config
        tool_set = self.request.tool_set if self.request is not None else None
        tool_set = ToolSet(tool_set.tools.copy()) if tool_set is not None else None
        return _AgentRunState(
            config=config, model_group=self.model_group.copy(),
            request=self._build_request(tool_set),
            accepting_steering=config.max_steps > 0,
        )

    def _begin_run(self) -> _AgentRunState:
        if self._run_state is not None:
            raise RuntimeError("This agent executor is already running")
        run_state = self._create_run_state()
        self._run_state = run_state
        self._state = "running"
        return run_state

    def _release_run(self, run_state: _AgentRunState) -> None:
        run_state.accepting_steering = False
        if self._run_state is run_state:
            self._run_state = None
            self._queued_messages.clear()
            self._state = "done"

    def _background_done(
        self, run_state: _AgentRunState, task: Task[AgentStepResult | None],
    ) -> None:
        # Cancellation before coroutine startup still needs to release its slot.
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
    ) -> AgentStepResult | None:
        iterator = self._iterate_run(ctx, run_state)
        last_step = None
        try:
            async for step in iterator:
                last_step = step
                if self.on_result is not None:
                    await self.on_result(step)
            return last_step
        finally:
            try:
                await iterator.aclose()
            finally:
                self._release_run(run_state)

    def queue(self, message: str | OpenAIMessage) -> Task[AgentStepResult | None] | None:
        """Queue a follow-up turn using the context supplied at initialization.

        Both drivers consume queued messages with fresh model/tool/config snapshots
        and step budgets. Once idle, including before the first run, a new task
        starts automatically on the same context.
        Returns that task, the active start() task, or None for a caller-driven run.
        Raise RuntimeError while an abort request is awaiting completion.
        """
        message = self._copy_user_message(message)
        if self._run_state is not None:
            if self._run_state.abort_requested.is_set():
                raise RuntimeError("This agent executor is stopping")
            self._queued_messages.append(message)
            task = self._background_task
            return task if task is not None and not task.done() else None
        return self._start(message)

    def abort(self) -> bool:
        """Stop after the current call completes, without cancelling it.

        Call from the executor's event loop. Pending steering and queued turns
        are discarded. Both run() and start() emit a final stopped result once
        execution reaches a call boundary. Result callbacks finish normally.
        Return False when idle or when a stop has already been requested.
        """
        run_state = self._run_state
        if run_state is None or run_state.abort_requested.is_set():
            return False
        run_state.abort_requested.set()
        self._state = "stopping"
        run_state.accepting_steering = False
        run_state.pending_messages.clear()
        self._queued_messages.clear()
        return True

    @staticmethod
    def _copy_user_message(message: str | OpenAIMessage) -> OpenAIMessage:
        if isinstance(message, str):
            message = OpenAIMessage(role="user", content=message)
        elif not isinstance(message, OpenAIMessage):
            raise TypeError("message must be a string or OpenAIMessage")
        if message.role != "user":
            raise ValueError("message must have the user role")
        if not message.content or (isinstance(message.content, str) and not message.content.strip()):
            raise ValueError("message content must not be empty")
        return deepcopy(message)

    def steer(self, message: str | OpenAIMessage) -> bool:
        """Apply a user instruction at the next model request of the current turn.

        Call from the executor's event loop. Idle/final-step calls return False.
        Accepted instructions are copied; in-flight calls are not cancelled and
        the current step budget is never extended.
        """
        message = self._copy_user_message(message)
        run_state = self._run_state
        if run_state is None or not run_state.accepting_steering:
            return False
        run_state.pending_messages.append(message)
        return True

    @staticmethod
    def _append_messages(ctx: ContextT, run_state: _AgentRunState, *messages: OpenAIMessage) -> None:
        ctx.append_messages(*messages)
        run_state.request.messages.extend(messages)

    def _apply_steering(self, ctx: ContextT, run_state: _AgentRunState) -> None:
        if run_state.pending_messages:
            messages = run_state.pending_messages
            run_state.pending_messages = []
            self._append_messages(ctx, run_state, *messages)

    async def _execute_tools(
        self, ctx: ContextT, response: LLMResponse, run_state: _AgentRunState,
    ) -> None:
        await self.tool_executor.execute_tools(
            response, tool_set=run_state.request.tool_set, config=run_state.config.tool_config,
            on_tool_call=partial(self._await_tool_call_hook, ctx, run_state),
            on_tool_result=partial(self.hooks.on_tool_result, ctx),
            should_stop=run_state.abort_requested.is_set,
        )

    async def _await_tool_call_hook(
        self, ctx: ContextT, run_state: _AgentRunState, call_ctx: ToolCallContext,
    ) -> None:
        """Let abort cancel an approval wait before any tool starts executing."""
        call_ctx.agent_context = ctx
        hook_task = create_task(self.hooks.on_tool_call(call_ctx))
        abort_task = create_task(run_state.abort_requested.wait())
        try:
            await wait({hook_task, abort_task}, return_when=FIRST_COMPLETED)
            if not run_state.abort_requested.is_set():
                await hook_task
        finally:
            hook_task.cancel()
            abort_task.cancel()
            await gather(hook_task, abort_task, return_exceptions=True)

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

    async def run(self) -> AsyncIterator[AgentStepResult]:
        """Yield the shared agent loop directly, including any queued follow-ups.

        steer(), queue(), and abort() behave as with start(). The caller consumes results;
        on_result is reserved for the start() task driver. The context and optional
        request are supplied when constructing the executor.
        """
        ctx = self.context
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
        iterator = None
        if ctx.new_messages is self._last_turn_messages:
            # Keep caller-added inputs while leaving previous results intact.
            ctx.new_messages = ctx.new_messages[self._last_turn_message_count:]
        try:
            while True:
                iterator = self._run(ctx, run_state)
                last_step = None
                async for result in iterator:
                    last_step = result
                    if result.is_final:
                        run_state.accepting_steering = False
                    yield result
                if run_state.abort_requested.is_set():
                    model = run_state.model or (run_state.model_group[0].model if run_state.model_group else None)
                    if model is not None:
                        yield AgentStepResult(
                            state="stopped", step_index=run_state.step_index,
                            llm_response=None, new_messages=ctx.new_messages,
                            is_final=True, has_tool_calls=False, model=model,
                        )
                    return
                if (last_step is not None and last_step.state == "stopped") or not self._queued_messages:
                    return
                message = self._queued_messages.popleft()
                run_state = self._create_run_state()
                ctx.new_messages = []
                run_state.pending_messages.append(message)
                self._run_state = run_state
        finally:
            run_state.accepting_steering = False
            try:
                if iterator is not None:
                    await iterator.aclose()
            finally:
                self._last_turn_messages = ctx.new_messages
                self._last_turn_message_count = len(ctx.new_messages)
                self._release_run(run_state)

    async def _run(
        self, ctx: ContextT, run_state: _AgentRunState,
    ) -> AsyncIterator[AgentStepResult]:
        request = run_state.request
        model_group = run_state.model_group
        config = run_state.config
        max_steps = config.max_steps

        if not model_group:
            raise ValueError("model_group must be a non-empty list of LLMModelClient")

        llm_model = model_group[0]

        sid = getattr(getattr(ctx, "event", None), "sid", "agent")

        provider_name = llm_model.model.provider_name
        model_name = llm_model.model.model_name
        llm_logger.info(f"[{sid}] Running agent using {model_name} ({provider_name})")

        if run_state.abort_requested.is_set():
            return
        self._apply_steering(ctx, run_state)
        for step in range(max_steps):
            if run_state.abort_requested.is_set():
                return
            step_index = step + 1
            run_state.step_index = step_index

            state: Literal["success", "stopped", "error"] = "success"
            err = ""
            is_final = step_index == max_steps
            run_state.accepting_steering = not is_final
            self._apply_steering(ctx, run_state)

            # Inject last-step hint so the LLM knows to wrap up
            if is_final and config.final_step_hint:
                final_step_prompt = Prompt(
                    name="final_step_hint",
                    source="system",
                    persist=False,
                    content=config.final_step_hint,
                )
                hint_message = OpenAIMessage(role="user", content=final_step_prompt.to_string())
                request.messages.append(hint_message)

            # Try models in order, failover to next on provider/API errors.
            # Only catch provider-level exceptions (network, timeout, API status).
            # Programming errors (TypeError, ValueError, etc.) should propagate.
            llm_resp = None
            last_exc: Exception | None = None
            for model_idx, model in enumerate(model_group):
                if run_state.abort_requested.is_set():
                    return
                run_state.model = model.model
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
                    if run_state.abort_requested.is_set():
                        return
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
                        await self.hooks.on_exception(
                            ctx, last_exc, source="provider", comp_id=model.model.provider_name,
                        )

            if run_state.abort_requested.is_set():
                return
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

            stopped_by_hook = await self.hooks.on_llm_response(ctx, llm_resp)
            if run_state.abort_requested.is_set():
                return
            if stopped_by_hook:
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
                self._append_messages(ctx, run_state, msg)
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
                await self._execute_tools(ctx, llm_resp, run_state)
            except Exception as e:
                logger.error(f"[{sid}] Tool execution failed: {e}")
                await self.hooks.on_exception(ctx, e, source="tool", comp_id=None)
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
            self._append_messages(ctx, run_state, msg, *tool_msgs)

            if run_state.abort_requested.is_set():
                return
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
