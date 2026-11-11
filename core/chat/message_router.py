from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from .message_utils import KiraIMSentResult, MessageChain
from .session import Session, User

if TYPE_CHECKING:
    from core.agent.message import OpenAIMessage
    from core.chat.session_manager import SessionManager


class MessageRoute(Protocol):
    """Match complete sessions and define their receiving and sending handlers."""

    def matches(self, session: Session) -> bool: ...

    async def receive_message(self, session: Session, message: object) -> None: ...

    async def send_message_chain(
        self, session: Session, chain: MessageChain, *,
        memory_message: OpenAIMessage | None = None, bot: User | None = None,
    ) -> KiraIMSentResult: ...


class MessageRouter:
    """Select routes by priority, then registration order, using full sessions.

    The event-bus entry loads session context through SessionManager. Matching
    does not interpret session IDs or define implicit transport fallbacks.
    """

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self._routes: list[tuple[int, MessageRoute]] = []

    def register_route(self, route: MessageRoute, *, priority: int = 0) -> None:
        """Register a route; higher priorities are matched first."""
        if any(registered is route for _, registered in self._routes):
            raise ValueError("Route is already registered")
        self._routes.append((priority, route))
        self._routes.sort(key=lambda item: item[0], reverse=True)

    def unregister_route(self, route: MessageRoute) -> bool:
        """Remove only the supplied route instance."""
        for index, (_, registered) in enumerate(self._routes):
            if registered is route:
                del self._routes[index]
                return True
        return False

    def _resolve(self, session: Session) -> MessageRoute:
        if not isinstance(session, Session):
            raise TypeError("MessageRouter requires a Session object")
        for _, route in self._routes:
            if route.matches(session):
                return route
        raise ValueError(f"No message route matches session {session.internal_id or session.sid!r}")

    async def handle_event(self, event: Any) -> None:
        """Load an incoming event's session context before selecting its receiver."""
        target = getattr(event, "target_session", event.session)
        session = await self.session_manager.get_session(target.sid)
        if session is not None:
            session.session_title = target.session_title or session.session_title
            target = session
        if hasattr(event, "target_session"):
            event.target_session = target
        else:
            event.session = target
        await self.receive_message(
            target,
            event,
        )

    async def receive_message(self, session: Session, message: object) -> None:
        """Hand an incoming message to the handler selected for its session."""
        await self._resolve(session).receive_message(
            session,
            message,
        )

    async def send_message_chain(
        self, session: Session, chain: MessageChain, *,
        memory_message: OpenAIMessage | None = None, bot: User | None = None,
    ) -> KiraIMSentResult:
        """Return the target handler's delivery receipt without joining its work."""
        return await self._resolve(session).send_message_chain(
            session,
            chain,
            memory_message=memory_message,
            bot=bot,
        )
