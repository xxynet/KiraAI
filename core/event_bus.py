import asyncio
from typing import Any, Callable, Dict, List, Optional, Union
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .statistics import Statistics

from core.chat import KiraMessageEvent, KiraCommentEvent
from core.message_manager import MessageProcessor


class EventType(Enum):
    """事件类型枚举"""
    KiraAILoaded = auto()

    """When a message arrives, could be KiraMessageEvent, KiraCommentEvent, etc..."""
    MsgRecv = auto()

    """THe message has been processed and has a result"""
    MsgResult = auto()

    """The message has been sent to adapter"""
    MsgSent = auto()


# @dataclass
# class Event:
#     """统一事件对象"""
#     event_type: EventType
#     payload: Any
#     source: str
#     timestamp: datetime = field(default_factory=datetime.now)
#     event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
#     priority: int = 0  # 0 = normal, 1 = high, 2 = critical
#     metadata: Dict[str, Any] = field(default_factory=dict)


class EventBus:
    """事件总线"""

    def __init__(self, stats: Statistics, event_queue: asyncio.Queue, message_processor: MessageProcessor):
        self.stats = stats

        self.event_queue: asyncio.Queue = event_queue

        self.message_processor = message_processor

        # TODO make max concurrent messages as a config
        self.message_processing_semaphore = asyncio.Semaphore(3)

        # subscribers dict：{event_type: [handlers]}
        self.subscribers: Dict[EventType, List[Callable]] = {}

        # event handlers
        self.event_handlers: Dict[Union[KiraMessageEvent, KiraCommentEvent], Callable]

        # middleware list
        self.middlewares: List[Callable] = []

        # statistics
        self.event_bus_stats = {
            "published": 0,
            "processed": 0,
            "errors": 0,
            "dropped": 0
        }

        self.stats.set_stats("event_bus", self.event_bus_stats)

        self._running_event = asyncio.Event()
        # self._running_tasks: List[asyncio.Task] = []

    async def _dispatch_event(self, event):
        async with self.message_processing_semaphore:
            if isinstance(event, KiraMessageEvent):
                await self.message_processor.handle_im_message(event)
            elif isinstance(event, KiraCommentEvent):
                await self.message_processor.handle_cmt_message(event)

    def subscribe(self, event_type: EventType, handler: Callable):
        """subscribe event"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Callable):
        """unsubscribe event"""
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(handler)

    def add_middleware(self, middleware: Callable):
        """add a middleware"""
        self.middlewares.append(middleware)

    async def publish(self, event):
        """publish an event"""
        try:
            # 通过中间件处理
            for middleware in self.middlewares:
                event = await middleware(event)
                if event is None:  # 中间件可以过滤事件
                    return

            try:
                self.event_queue.put_nowait(event)
            except asyncio.QueueFull:
                self.event_bus_stats["dropped"] += 1
                self.stats.set_stats("event_bus", self.event_bus_stats)

            self.event_bus_stats["published"] += 1
            self.stats.set_stats("event_bus", self.event_bus_stats)

        except Exception as e:
            self.event_bus_stats["errors"] += 1
            self.stats.set_stats("event_bus", self.event_bus_stats)
            raise

    async def _consumer_loop(self):
        """消费者循环"""
        while self._running_event.is_set():
            try:
                try:
                    event = self.event_queue.get_nowait()
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.1)
                    continue

                if event:
                    await self._process_event(event)
                    self.event_bus_stats["processed"] += 1
                    self.stats.set_stats("event_bus", self.event_bus_stats)

            except Exception as e:
                self.event_bus_stats["errors"] += 1
                self.stats.set_stats("event_bus", self.event_bus_stats)

    async def _process_event(self, event):
        """处理单个事件"""
        event_type = event.event_type

        # 处理所有订阅者
        if event_type in self.subscribers:
            for handler in self.subscribers[event_type]:
                try:
                    await handler(event)
                except Exception as e:
                    self.event_bus_stats["errors"] += 1
                    self.stats.set_stats("event_bus", self.event_bus_stats)

    async def dispatch(self):
        """start event bus"""
        self._running_event.set()

        while self._running_event.is_set():
            event: Union[KiraMessageEvent, KiraCommentEvent] = await self.event_queue.get()
            asyncio.create_task(self._dispatch_event(event))

    async def stop(self):
        """stop event bus"""
        self._running_event.clear()
        # for task in self._running_tasks:
        #     task.cancel()
        # await asyncio.gather(*self._running_tasks, return_exceptions=True)

    def get_stats(self) -> Dict[str, int]:
        """get statistics of event bus"""
        return self.event_bus_stats.copy()
