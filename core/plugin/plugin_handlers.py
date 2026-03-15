from enum import Enum, IntEnum
from dataclasses import dataclass
from typing import Optional, Union, Callable, Any, Dict, List

from core.logging_manager import get_logger

logger = get_logger("hook", "orange")


class Priority(IntEnum):
    """Priority of event handlers, DO NOT use SYS_LOW or SYS_HIGH in user plugins"""

    SYS_LOW = -100
    LOW = -50
    MEDIUM = 0
    HIGH = 50
    SYS_HIGH = 100


class EventType(Enum):
    ON_IM_MESSAGE = "on_im_message"  # 消息到达时
    ON_MESSAGE_BUFFERED = "on_message_buffered"  # 消息进入缓冲区后
    ON_IM_BATCH_MESSAGE = "on_im_batch_message"  # 消息合并后
    ON_LLM_REQUEST = "on_llm_request"  # LLM请求前
    ON_LLM_RESPONSE = "on_llm_response"  # LLM 原始输出
    AFTER_XML_PARSE = "after_xml_parse"  # XML 解析后 (MessageChain)
    ON_TOOL_RESULT = "on_tool_result"  # 工具调用结果
    ON_STEP_RESULT = "on_step_result"  # Agent 步骤结果
    ON_FINAL_RESULT = "on_final_result"  # 最终消息结果
    ...


@dataclass
class EventHandler:
    event_type: EventType

    priority: Union[Priority, int]

    handler: Callable

    desc: Optional[str] = None

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
