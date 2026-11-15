from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.chat.session import Session

    from .agent_executor import AgentExecutor
    from .message import OpenAIMessage


class MainAgentRuns:
    """Track foreground IM executors by session identity on the workflow event loop."""

    def __init__(self) -> None:
        self._by_target: dict[str, set[AgentExecutor]] = {}

    @asynccontextmanager
    async def track(self, session: Session, executor: AgentExecutor) -> AsyncIterator[None]:
        targets = {session.sid}
        if session.internal_id:
            targets.add(session.internal_id)
        for target in targets:
            self._by_target.setdefault(target, set()).add(executor)
        try:
            yield
        finally:
            for target in targets:
                executors = self._by_target[target]
                executors.remove(executor)
                if not executors:
                    del self._by_target[target]

    def steer(self, target: str, message: str | OpenAIMessage) -> bool:
        executors = self._by_target.get(target)
        if not executors or len(executors) != 1:
            return False
        executor = next(iter(executors))
        return not executor.context.event.is_stopped and executor.steer(message)
