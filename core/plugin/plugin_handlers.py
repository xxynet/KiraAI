from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Union, Callable, Any, Dict, List

from core.logging_manager import get_logger

logger = get_logger("hook", "orange")


class Priority(Enum):
    """Priority of a event handler"""

    LOW = 0
    MEDIUM = 20
    HIGH = 40


class EventType(Enum):
    IMMessage = auto()
    ...


@dataclass
class EventHandler:
    event_type: EventType

    priority: Union[Priority, int]

    handler: Callable

    desc: Optional[str] = None

    def __post_init__(self):
        if isinstance(self.priority, Priority):
            self.priority = self.priority.value

    def __lt__(self, other):
        return self.priority < other.priority

    def __gt__(self, other):
        return self.priority > other.priority

    async def exec_handler(self, event, *args, **kwargs):
        try:
            await self.handler(event, *args, **kwargs)
        except Exception:
            import traceback
            logger.error(traceback.format_exc())


class EventHandlerRegistry:
    def __init__(self):
        self._handlers: Dict[Any, List[EventHandler]] = {}

    def register(self, eh: EventHandler):
        self._handlers.setdefault(eh.event_type, [])
        self._handlers[eh.event_type].append(eh)
        self._handlers[eh.event_type].sort(reverse=True)

    def get_handlers(self, event_type: EventType) -> List[EventHandler]:
        return self._handlers.setdefault(event_type, [])

    def del_handler(self, handler: EventHandler):
        for k, hl in self._handlers.items():
            if handler in hl:
                hl.remove(handler)
                break


event_handler_reg = EventHandlerRegistry()
