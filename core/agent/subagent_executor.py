from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.persona.persona_manager import PersonaManager
from core.plugin.handlers import EventType, event_handler_reg
from core.provider import LLMModelClient, LLMRequest
from core.utils.media_refs import session_media_scope

from .base_agent_executor import (
    AgentStepResult,
    BaseAgentExecutionContext,
    BaseAgentExecutor,
)
from .config import SubAgentConfig
from .hook_context import ToolCallContext
from .hooks import AgentExecutionHooks
from .im_tool_executor import IMToolExecutor
from .message import OpenAIMessage
from .skills_mgr import SkillsManager
from .subagent_event import SubAgentEvent

if TYPE_CHECKING:
    from .base_agent_executor import _AgentRunState


@dataclass(kw_only=True)
class SubAgentExecutionContext(BaseAgentExecutionContext):
    """Keep one child conversation while exposing its permission-scoped event."""

    event: SubAgentEvent


class SubAgentToolExecutor(IMToolExecutor):
    """Execute inherited tools with the subagent event and retain its context."""

    event: SubAgentEvent

    def __init__(self, context: SubAgentExecutionContext):
        super().__init__(context.event)
        self.context = context


class SubAgentExecutionHooks(AgentExecutionHooks[SubAgentExecutionContext]):
    """Run shared tool approvals without broadcasting IM response hooks."""

    def __init__(
        self,
        *,
        config: SubAgentConfig | None = None,
        persona_manager: PersonaManager | None = None,
        skills_manager: SkillsManager | None = None,
    ):
        self.config = config or SubAgentConfig()
        self.persona_manager = persona_manager
        self.skills_manager = skills_manager
        self._persona_message: OpenAIMessage | None = None
        self._request_system_message: OpenAIMessage | None = None

    async def on_llm_request(self, ctx: SubAgentExecutionContext, request: LLMRequest) -> None:
        if self.config.instruction_source == "persona":
            original = self._persona_message
            system = await self._refresh_persona(ctx)
        else:
            system = ctx.messages[0] if ctx.messages and ctx.messages[0].role == "system" else None
            original = system
        skills_prompt = self._skills_prompt(ctx.event.sid)
        if skills_prompt is not None:
            instruction = system.content if system is not None else None
            content = f"{instruction}\n\n{skills_prompt}" if instruction else skills_prompt
            system = OpenAIMessage(role="system", content=content)

        # The Skills listing belongs to the current model request only.
        if request.messages and (
            request.messages[0] is original or request.messages[0] is self._request_system_message
        ):
            request.messages.pop(0)
        if system is not None:
            request.messages.insert(0, system)
        self._request_system_message = system

    async def _refresh_persona(self, ctx: SubAgentExecutionContext) -> OpenAIMessage:
        if self.persona_manager is None:
            raise ValueError("Persona manager unavailable")
        persona = await self.persona_manager.get_persona(self.config.persona_id)
        if persona is None:
            raise ValueError(f"Subagent persona is unavailable: {self.config.persona_id or 'active'}")
        message = OpenAIMessage(
            role="system",
            content=persona.content or "",
        )
        ctx.messages[:] = [item for item in ctx.messages if item is not self._persona_message]
        ctx.messages.insert(0, message)
        self._persona_message = message
        return message

    def _skills_prompt(self, session_id: str) -> str | None:
        manager = self.skills_manager
        if manager is None:
            return None

        names = set(self.config.skill_names)
        mode = self.config.tool_mode
        skills = [
            skill for skill in manager.skills_info
            if skill.enabled
            and manager.is_skill_allowed(skill.name, session_id)
            and (mode != "exclude" or skill.name not in names)
            and (mode != "custom" or skill.name in names)
        ]
        return manager.build_skills_prompt(skills).to_string() if skills else None

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
        on_turn_start: Callable[[], Awaitable[list[LLMModelClient] | None]],
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

    @staticmethod
    def _append_messages(
        ctx: SubAgentExecutionContext, run_state: _AgentRunState, *messages: OpenAIMessage,
    ) -> None:
        BaseAgentExecutor._append_messages(ctx, run_state, *messages)
        for message in messages:
            if message.role == "user":
                ctx.event.append_input(message)

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
                ctx.event.begin_turn()
                models = await self.on_turn_start()
                if models is not None:
                    run_state.model_group = models
                ctx.event.model_group = run_state.model_group.copy()
                run_state.request.messages = ctx.messages.copy()
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
