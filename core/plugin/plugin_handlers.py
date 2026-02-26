from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional, Union, Callable, Any, Dict, List

from core.logging_manager import get_logger

logger = get_logger("hook", "orange")


class Priority(Enum):
    """Priority of a event handler"""

    LOW = -50
    MEDIUM = 0
    HIGH = 50


class EventType(Enum):
    ON_IM_MESSAGE = "on_im_message"  # 第一步：消息到达时
    ON_IM_BATCH_MESSAGE = "on_im_batch_message"  # 第二步：消息合并后
    ON_LLM_REQUEST = "on_llm_request"  # 第三步：LLM请求前
    ON_LLM_RESPONSE = "on_llm_response"  # 第四步：LLM 原始输出
    AFTER_XML_PARSE = "after_xml_parse"  # 第五步：XML 解析后
    ON_TOOL_RESULT = "on_tool_result"  # 第六步：工具调用结果
    ON_FINAL_RESULT = "on_final_result"  # 第七步：最终消息结果
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
