from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, replace

from core.chat.message_elements import Image, Text
from core.chat.message_history import MessageHistoryService
from core.chat.message_utils import KiraCustomEvent, KiraIMMessage, MessageChain
from core.chat.session import Session, User
from core.chat.session_manager import SessionManager
from core.event_bus import EventBus
from core.logging_manager import get_logger
from core.provider import LLMModelClient, LLMRequest, ModelType, ProviderManager
from core.utils.media_refs import MEDIA_REF_TYPE
from core.utils.path_utils import get_data_path

from .base_agent_executor import AgentStepResult
from .config import AgentExecutionConfig, SubAgentConfig, ToolExecutionConfig
from .message import OpenAIMessage
from .subagent_event import SubAgentEvent
from .subagent_executor import SubAgentExecutionContext, SubAgentExecutor
from .tool import ToolSet

logger = get_logger("subagent", "cyan")
SUBAGENT_TOOL_NAMES = frozenset({
    "spawn_agent", "list_agents", "send_message", "followup_task", "interrupt_agent",
})
SUBAGENT_COMPLETED_EVENT = "subagent_completed"


@dataclass
class _Agent:
    session: Session
    config: SubAgentConfig
    parent_tools: ToolSet
    custom_tools: ToolSet
    executor: SubAgentExecutor | None = None
    task: asyncio.Task | None = None
    step: AgentStepResult | None = None
    status: str = "queued"
    result: str = ""
    error: str = ""
    turn: int = 0


class SubAgentManager:
    """Own isolated agent sessions and background tasks without a main tool registry."""

    def __init__(
        self,
        session_manager: SessionManager,
        provider_manager: ProviderManager,
        *,
        message_history: MessageHistoryService,
        event_bus: EventBus,
        max_concurrent: int = 4,
        max_agents: int = 128,
    ):
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in (max_concurrent, max_agents)):
            raise ValueError("Subagent limits must be positive")
        self.session_manager = session_manager
        self.provider_manager = provider_manager
        self.message_history = message_history
        self.event_bus = event_bus
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.max_agents = max_agents
        self._agents: dict[str, _Agent] = {}
        self._closing = False
        self._creation_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Retain history after restart without replaying unfinished external calls."""
        for session in await self.session_manager.get_sessions(include_content=False):
            if session.kind != "subagent":
                continue
            if not isinstance(session.data, dict) or not isinstance(session.data.get("subagent", {}), dict):
                logger.error("Malformed subagent session %s data: %r", session.sid, session.data)
                continue
            state = session.data.get("subagent", {})
            if state.get("status") in {"queued", "running", "stopping"}:
                state = dict(state, status="interrupted")
                await self.session_manager.update_session(
                    session.sid,
                    data={**session.data, "subagent": state},
                )

    @staticmethod
    def _settings(config: SubAgentConfig) -> dict:
        return {
            "tool_mode": config.tool_mode,
            "tool_names": list(config.tool_names),
            "excluded_tools": list(config.excluded_tools),
            "instruction": config.instruction,
            "max_steps": config.execution.max_steps,
            "final_step_hint": config.execution.final_step_hint,
            "tool_config": vars(config.execution.tool_config).copy(),
        }

    @staticmethod
    def _restore_settings(settings: dict) -> SubAgentConfig:
        return SubAgentConfig(
            execution=AgentExecutionConfig(
                max_steps=settings.get("max_steps", 5),
                tool_config=ToolExecutionConfig(**settings.get("tool_config", {})),
                final_step_hint=settings.get("final_step_hint"),
            ),
            tool_mode=settings.get("tool_mode", "inherit"),
            tool_names=tuple(settings.get("tool_names", ())),
            excluded_tools=tuple(settings.get("excluded_tools", ())),
            instruction=settings.get("instruction", SubAgentConfig().instruction),
        )

    @staticmethod
    def _copy_tools(tools: ToolSet | None) -> ToolSet:
        return ToolSet([
            tool for tool in tools.tools if tool.name not in SUBAGENT_TOOL_NAMES
        ]) if tools is not None else ToolSet()

    @staticmethod
    def _tools(config: SubAgentConfig, parent_tools: ToolSet, custom_tools: ToolSet) -> ToolSet:
        pool = custom_tools if config.tool_mode == "custom" else parent_tools
        tools = list(pool.tools)
        if config.tool_mode == "custom" and config.tool_names:
            missing = set(config.tool_names) - {tool.name for tool in tools}
            if missing:
                raise ValueError(f"Unknown subagent tools: {', '.join(sorted(missing))}")
            tools = [tool for tool in tools if tool.name in config.tool_names]
        blocked = SUBAGENT_TOOL_NAMES | set(config.excluded_tools)
        return ToolSet([tool for tool in tools if tool.name not in blocked])

    def _reserve(self) -> None:
        if self._closing:
            raise RuntimeError("Subagent manager is shutting down")
        if len(self._agents) >= self.max_agents:
            for identity, agent in tuple(self._agents.items()):
                if agent.task is None or agent.task.done():
                    del self._agents[identity]
                    break
            else:
                raise RuntimeError("Subagent capacity reached")

    async def spawn(
        self,
        task: str | OpenAIMessage,
        *,
        parent_id: str | None = None,
        permission_session: Session | str | None = None,
        title: str = "",
        config: SubAgentConfig | None = None,
        parent_tools: ToolSet | None = None,
        tools: ToolSet | None = None,
        model_group: list[LLMModelClient] | None = None,
    ) -> dict:
        async with self._creation_lock:
            return await self._spawn(
                task,
                parent_id=parent_id,
                permission_session=permission_session,
                title=title,
                config=config,
                parent_tools=parent_tools,
                tools=tools,
                model_group=model_group,
            )

    async def _spawn(
        self,
        task,
        **options,
    ) -> dict:
        """Create a durable conversation and return after submitting its first turn."""
        parent_id = options["parent_id"]
        permission_session = options["permission_session"]
        config = options["config"]
        parent_tools = options["parent_tools"]
        tools = options["tools"]
        model_group = options["model_group"]
        title = options["title"]
        SubAgentExecutor._copy_user_message(task)
        self._reserve()
        if permission_session is None and parent_id is not None:
            permission_session = parent_id
        scope = await self.session_manager.resolve_session(permission_session) if permission_session is not None else None
        if scope is not None and scope.internal_id is None:
            raise ValueError("Permission session must already be stored")
        config = config or SubAgentConfig()
        parent_tools = self._copy_tools(parent_tools)
        custom_tools = self._copy_tools(tools if tools is not None else parent_tools)
        selected = self._tools(config, parent_tools, custom_tools)
        models = self._models(model_group)
        metadata = {
            "status": "queued",
            "scope_id": scope.internal_id if scope else None,
            "scope_sid": scope.sid if scope else None,
            "settings": self._settings(config),
            "resolved_tools": [tool.name for tool in selected.tools],
            "result": "",
            "error": "",
            "turn": 0,
            "models": [
                {"provider_id": model.model.provider_id, "model_id": model.model.model_id}
                for model in models
            ] if model_group is not None else [],
        }
        session = await self.session_manager.create_subagent_session(
            title=title or (task if isinstance(task, str) else "Subagent")[:100],
            parent_id=parent_id,
            data={"subagent": metadata},
        )
        agent = _Agent(
            session=session,
            config=config,
            parent_tools=parent_tools,
            custom_tools=custom_tools,
        )
        self._build_executor(agent, scope or agent.session, models)
        self._agents[agent.session.internal_id] = agent
        self._track(agent, agent.executor.queue(task))
        return self._info(agent.session, agent)

    @staticmethod
    def _track(agent: _Agent, task: asyncio.Task | None) -> None:
        if task is None or task is agent.task:
            return
        agent.task = task

        def finished(completed):
            if completed.cancelled():
                agent.status = "interrupted"
                agent.error = "CancelledError"
            elif completed.exception() is not None:
                agent.status = "error"
                agent.error = str(completed.exception())
            elif agent.status == "stopping":
                agent.status = "stopped"

        task.add_done_callback(finished)

    def _models(self, models: list[LLMModelClient] | None) -> list[LLMModelClient]:
        if models is not None:
            if not models:
                raise ValueError("A subagent requires at least one model")
            return models
        default = self.provider_manager.get_default_llm()
        if default is None:
            raise ValueError("No default LLM is available for subagent execution")
        return [default]

    def _build_executor(self, agent: _Agent, scope: Session, models: list[LLMModelClient]) -> None:
        event = SubAgentEvent(
            session=scope,
            agent_session=agent.session,
            source_session=scope if scope.internal_id != agent.session.internal_id else None,
            content="",
        )
        ctx = SubAgentExecutionContext(
            event=event,
            messages=agent.session.flatten_content(),
        )
        request = LLMRequest(tool_set=self._tools(agent.config, agent.parent_tools, agent.custom_tools))
        if agent.config.instruction:
            request.messages.append(OpenAIMessage(
                role="system",
                content=agent.config.instruction,
            ))
            ctx.messages.insert(0, request.messages[0])

        async def begin():
            current_scope = await self.session_manager.get_session(ctx.event.session.sid, include_content=False)
            if current_scope is None:
                raise PermissionError("The subagent permission session no longer exists")
            agent.session = await self.session_manager.resolve_session(agent.session.internal_id)
            ctx.event.session = current_scope
            if ctx.event.source_session is not None:
                ctx.event.source_session = current_scope
            ctx.event.agent_session = agent.session
            agent.status = "running"
            agent.step = None
            agent.result = ""
            agent.error = ""
            agent.turn += 1
            metadata = dict(agent.session.data["subagent"])
            metadata.update(
                status="running",
                result="",
                error="",
                turn=agent.turn,
                step_index=0,
                updated_at=int(time.time()),
            )
            saved = await self.session_manager.update_memory(
                agent.session.sid,
                [],
                metadata={"subagent": metadata},
                require_existing=True,
            )
            if not saved:
                raise ValueError("The subagent session no longer exists")
            agent.session.data["subagent"] = metadata

        async def result(step: AgentStepResult):
            agent.step = step
            if step.assistant_message is not None and step.assistant_message.content:
                agent.result = step.assistant_message.content
            if step.err:
                agent.error = step.err
            response = step.llm_response
            if response is not None:
                try:
                    await self.session_manager.db.add_telemetry_llm_usage(
                        timestamp=int(time.time()),
                        model=step.model.model_name,
                        input_tokens=response.input_tokens or 0,
                        output_tokens=response.output_tokens or 0,
                        cached_tokens=response.cached_tokens,
                        response_time_ms=int((response.time_consumed or 0) * 1000),
                        success=step.state != "error",
                    )
                except Exception:
                    logger.exception("Unable to record subagent usage for %s", agent.session.internal_id)

        async def finish(context: SubAgentExecutionContext, error: BaseException | None):
            if error is not None:
                agent.status = "interrupted" if isinstance(error, asyncio.CancelledError) else "error"
                agent.error = str(error) or type(error).__name__
            elif agent.executor.state == "stopping" or (agent.step and agent.step.state == "stopped"):
                agent.status = "stopped"
            elif agent.step and agent.step.state == "error":
                agent.status = "error"
            else:
                agent.status = "done"
            metadata = dict(agent.session.data["subagent"])
            metadata.update(
                status=agent.status,
                result=agent.result,
                error=agent.error,
                turn=agent.turn,
                step_index=agent.step.step_index if agent.step else 0,
                resolved_tools=[tool.name for tool in self._tools(agent.config, agent.parent_tools, agent.custom_tools).tools],
                updated_at=int(time.time()),
            )
            saved = await self.session_manager.update_memory(
                agent.session.sid,
                list(context.new_messages),
                metadata={"subagent": metadata},
                require_existing=True,
            )
            if saved:
                await self._archive(agent, context)
            agent.session.data["subagent"] = metadata
            if error is not None and not isinstance(error, asyncio.CancelledError):
                logger.error(
                    "Subagent %s failed",
                    agent.session.internal_id,
                    exc_info=(type(error), error, error.__traceback__),
                )
            if saved and not self._closing and agent.status != "interrupted":
                current = await self.session_manager.get_session(agent.session.sid, include_content=False)
                if current is not None and current.parent_id is not None:
                    try:
                        await self.event_bus.publish(KiraCustomEvent(
                            event_name=SUBAGENT_COMPLETED_EVENT,
                            source_plugin="subagents",
                            payload=self._info(current, agent),
                            timestamp=int(time.time()),
                        ))
                    except Exception:
                        logger.exception("Unable to publish subagent completion for %s", agent.session.internal_id)

        agent.executor = SubAgentExecutor(
            models,
            context=ctx,
            request=request,
            config=agent.config.execution,
            semaphore=self.semaphore,
            on_turn_start=begin,
            on_turn_end=finish,
            on_result=result,
        )

    async def _archive(self, agent: _Agent, context: SubAgentExecutionContext) -> None:
        """Record visible inputs and outputs using the existing history service."""
        for message in context.new_messages:
            if message.role not in {"user", "assistant"} or not message.content:
                continue
            elements = []
            if isinstance(message.content, str):
                elements.append(Text(message.content))
            else:
                for part in message.content:
                    if part.get("type") == "text":
                        elements.append(Text(part.get("text", "")))
                    elif part.get("type") == "image_url":
                        elements.append(Image(image=part["image_url"]["url"]))
                    elif part.get("type") == MEDIA_REF_TYPE:
                        elements.append(Image(image=str(get_data_path() / part["path"])))
                    else:
                        elements.append(Text(json.dumps(part, ensure_ascii=False)))
            chain = MessageChain(elements)
            identity = message.to_memory_dict()["_extra"]["llm_message_id"]
            try:
                if message.role == "user":
                    record = await self.message_history.record_incoming(
                        KiraIMMessage(
                            message_id=identity,
                            self_id=agent.session.internal_id,
                            chain=chain,
                            timestamp=int(time.time()),
                            sender=User(context.event.session.internal_id or "system", "Delegating agent"),
                        ),
                        agent.session.sid,
                        "subagent",
                    )
                    await self.message_history.link_incoming_messages(agent.session.sid, identity, [record])
                else:
                    record = await self.message_history.record_outgoing(
                        agent.session.sid,
                        chain,
                        platform="subagent",
                        self_id=agent.session.internal_id,
                        llm_message_id=identity,
                        sender_name=agent.session.session_title,
                    )
                    await self.message_history.finish_outgoing(record, status="sent")
            except Exception:
                logger.exception("Unable to archive subagent message for %s", agent.session.internal_id)

    async def _session(self, target: str | Session, caller_id: str | None = None) -> Session:
        if isinstance(target, Session):
            target = target.internal_id or target.sid
        session = await self.session_manager.resolve_session(target)
        if session.kind != "subagent" or session.internal_id is None:
            raise ValueError("Target is not a stored subagent session")
        if not isinstance(session.data.get("subagent", {}), dict):
            raise TypeError("Subagent session metadata must be an object")
        if caller_id is not None and caller_id not in {
            session.parent_id, session.data.get("subagent", {}).get("scope_id"),
        }:
            raise PermissionError("Subagent does not belong to the calling session")
        return session

    @staticmethod
    def _info(session: Session, agent: _Agent | None = None) -> dict:
        state = session.data.get("subagent", {})
        return {
            "id": session.internal_id,
            "sid": session.sid,
            "kind": session.kind,
            "parent_id": session.parent_id,
            "title": session.session_title,
            "permission_sid": state.get("scope_sid"),
            "status": agent.status if agent else state.get("status", "done"),
            "step_index": (agent.step.step_index if agent.step else 0) if agent else state.get("step_index", 0),
            "turn": agent.turn if agent else state.get("turn", 0),
            "result": agent.result if agent else state.get("result", ""),
            "error": agent.error if agent else state.get("error", ""),
        }

    async def get(self, target: str | Session, *, caller_id: str | None = None) -> dict:
        session = await self._session(target, caller_id)
        return self._info(session, self._agents.get(session.internal_id))

    async def list_agents(self, *, caller_id: str | None = None) -> list[dict]:
        result = []
        for session in await self.session_manager.get_sessions(include_content=False):
            if session.kind != "subagent" or not isinstance(session.data, dict):
                continue
            if not isinstance(session.data.get("subagent", {}), dict):
                continue
            if caller_id is not None and caller_id not in {
                session.parent_id, session.data.get("subagent", {}).get("scope_id"),
            }:
                continue
            result.append(self._info(session, self._agents.get(session.internal_id)))
        return result

    async def followup(
        self,
        target: str | Session,
        message: str | OpenAIMessage,
        *,
        caller_id: str | None = None,
        parent_tools: ToolSet | None = None,
        tools: ToolSet | None = None,
        steer: bool = False,
    ) -> dict:
        async with self._creation_lock:
            return await self._followup(
                target,
                message,
                caller_id=caller_id,
                parent_tools=parent_tools,
                tools=tools,
                steer=steer,
            )

    async def _followup(self, target, message, *, caller_id, parent_tools, tools, steer) -> dict:
        SubAgentExecutor._copy_user_message(message)
        if self._closing:
            raise RuntimeError("Subagent manager is shutting down")
        session = await self._session(target, caller_id)
        agent = self._agents.get(session.internal_id)
        if agent is None:
            self._reserve()
            state = session.data.get("subagent", {})
            config = self._restore_settings(state.get("settings", {}))
            if state.get("resolved_tools") and parent_tools is None and tools is None:
                raise ValueError("Resuming this agent requires an explicit tool set")
            scope_id = state.get("scope_id") or state.get("scope_sid")
            scope = await self.session_manager.resolve_session(scope_id) if scope_id else session
            agent = _Agent(
                session=session,
                config=config,
                parent_tools=self._copy_tools(parent_tools),
                custom_tools=self._copy_tools(tools if tools is not None else parent_tools),
                turn=state.get("turn", 0),
            )
            models = []
            for reference in state.get("models", []):
                model = self.provider_manager.get_model_client(
                    reference["provider_id"],
                    reference["model_id"],
                    ModelType.LLM,
                )
                if model is None:
                    raise ValueError(f"Subagent model is unavailable: {reference}")
                models.append(model)
            self._build_executor(agent, scope, self._models(models or None))
            self._agents[session.internal_id] = agent
        selection = replace(
            agent,
            parent_tools=self._copy_tools(parent_tools) if parent_tools is not None else agent.parent_tools,
            custom_tools=self._copy_tools(tools) if tools is not None else agent.custom_tools,
        )
        selected = self._tools(selection.config, selection.parent_tools, selection.custom_tools)
        agent.parent_tools = selection.parent_tools
        agent.custom_tools = selection.custom_tools
        agent.executor.request.tool_set = selected
        agent.executor.request.tool_choice = "auto" if selected.tools else "none"
        if steer and agent.executor.steer(message):
            return self._info(session, agent)
        agent.error = ""
        task = agent.executor.queue(message)
        self._track(agent, task)
        if agent.executor.state != "running" or agent.status in {"done", "stopped", "error", "interrupted"}:
            agent.status = "queued"
        return self._info(session, agent)

    async def interrupt(self, target: str | Session, *, caller_id: str | None = None) -> dict:
        session = await self._session(target, caller_id)
        agent = self._agents.get(session.internal_id)
        if agent is not None and agent.executor.abort():
            agent.status = "stopping"
        return self._info(session, agent)

    async def wait(
        self,
        target: str | Session,
        *,
        timeout: float = 0,
        caller_id: str | None = None,
    ) -> dict:
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 <= timeout <= 30:
            raise ValueError("Wait timeout must be between 0 and 30 seconds")
        session = await self._session(target, caller_id)
        agent = self._agents.get(session.internal_id)
        if timeout and agent and agent.task:
            await asyncio.wait({agent.task}, timeout=timeout)
        return await self.get(session, caller_id=caller_id)

    async def on_session_deleted(self, event) -> None:
        async with self._creation_lock:
            agents = [agent for agent in self._agents.values() if agent.session.sid == event.payload.get("session")]
            for agent in agents:
                del self._agents[agent.session.internal_id]
        for agent in agents:
            agent.executor.abort()
            if agent.task is not None:
                if agent.status != "interrupted":
                    agent.status = "interrupted"
                    agent.task.cancel()
                await asyncio.gather(agent.task, return_exceptions=True)

    async def shutdown(self, timeout: float = 5) -> None:
        async with self._creation_lock:
            self._closing = True
            agents = list(self._agents.values())
        tasks = []
        for agent in agents:
            agent.executor.abort()
            if agent.task is not None and not agent.task.done():
                tasks.append(agent.task)
        if tasks:
            _, pending = await asyncio.wait(tasks, timeout=timeout)
            for agent in agents:
                if agent.task in pending and agent.status != "interrupted":
                    agent.status = "interrupted"
                    agent.task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
