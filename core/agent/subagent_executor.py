from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.plugin.handlers import EventType, event_handler_reg
from core.utils.media_refs import session_media_scope
from core.utils.tool_utils import BaseTool

from .base_agent_executor import (
    AgentStepResult,
    BaseAgentExecutionContext,
    BaseAgentExecutor,
)
from .hook_context import ToolCallContext
from .hooks import AgentExecutionHooks
from .subagent_event import SubAgentEvent
from .tool_executor import ToolExecutor

if TYPE_CHECKING:
    from .base_agent_executor import _AgentRunState


@dataclass(kw_only=True)
class SubAgentExecutionContext(BaseAgentExecutionContext):
    """Keep one child conversation while exposing its permission-scoped event."""

    event: SubAgentEvent


class SubAgentToolExecutor(ToolExecutor):
    """Supply the dedicated event to tools inherited from a parent request."""

    def __init__(self, context: SubAgentExecutionContext):
        self.context = context
        self.event = context.event

    async def invoke_tool(self, tool: BaseTool, args: dict) -> object:
        for message in reversed(self.context.messages):
            if message.role == "user":
                self.event.content = message
                break
        return await tool.execute(self.event, **args)


class SubAgentExecutionHooks(AgentExecutionHooks[SubAgentExecutionContext]):
    """Run shared tool approvals without broadcasting IM response hooks."""

    async def on_tool_call(self, ctx: ToolCallContext) -> None:
        for handler in event_handler_reg.get_handlers(EventType.ON_TOOL_CALL):
            await handler.exec_handler(ctx)
            if ctx.result is not None:
                return


class SubAgentExecutor(BaseAgentExecutor[SubAgentExecutionContext]):
    """Reuse the agent loop with bounded concurrency and per-turn persistence."""

    def __init__(
        self,
        model_group,
        *,
        context: SubAgentExecutionContext,
        semaphore: asyncio.Semaphore,
        on_turn_end: Callable[[SubAgentExecutionContext, BaseException | None], Awaitable[None]],
        on_turn_start: Callable[[], Awaitable[None]],
        **kwargs,
    ):
        super().__init__(
            model_group,
            context=context,
            hooks=kwargs.pop("hooks", None) or SubAgentExecutionHooks(),
            tool_executor=kwargs.pop("tool_executor", None) or SubAgentToolExecutor(context),
            **kwargs,
        )
        self.semaphore = semaphore
        self.on_turn_end = on_turn_end
        self.on_turn_start = on_turn_start
        context.event._on_stop = self.abort

    async def _run(
        self,
        ctx: SubAgentExecutionContext,
        run_state: _AgentRunState,
    ) -> AsyncIterator[AgentStepResult]:
        async with session_media_scope():
            error = None
            iterator = None
            slot = asyncio.create_task(self.semaphore.acquire())
            stopped = asyncio.create_task(run_state.abort_requested.wait())
            try:
                done, _ = await asyncio.wait({slot, stopped}, return_when=asyncio.FIRST_COMPLETED)
                if slot not in done:
                    return
                slot.result()
                if run_state.abort_requested.is_set():
                    return
                await self.on_turn_start()
                ctx.event._stopped = False
                iterator = super()._run(ctx, run_state)
                async for step in iterator:
                    yield step
            except BaseException as exc:
                error = exc
                raise
            finally:
                for pending in (slot, stopped):
                    if not pending.done():
                        pending.cancel()
                await asyncio.gather(slot, stopped, return_exceptions=True)
                if not slot.cancelled() and slot.exception() is None and slot.result():
                    self.semaphore.release()
                if iterator is not None:
                    await iterator.aclose()
                task = asyncio.create_task(self.on_turn_end(ctx, error))
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
