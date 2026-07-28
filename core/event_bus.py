from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING, Type
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .statistics import Statistics
from .logging_manager import get_logger

from core.chat import KiraMessageEvent, KiraCommentEvent
from core.chat.message_utils import KiraMessageBatchEvent, KiraCustomEvent


@dataclass
class SystemEvent:
    """统一事件对象"""
    event_type: str
    payload: Any
    source: str
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    priority: int = 0  # 0 = normal, 1 = high, 2 = critical
    metadata: Dict[str, Any] = field(default_factory=dict)


if TYPE_CHECKING:
    from core.db.service import DatabaseService


class EventBus:
    """事件总线"""

    def __init__(self, stats: Statistics, event_queue: asyncio.Queue,
                 db: DatabaseService = None):
        self.stats = stats
        self.db = db

        self.event_queue: asyncio.Queue = event_queue

        # subscribers dict：{event_type: [handlers]}
        self.subscribers: Dict[Union[str, Type], List[Callable]] = {}

        # Built-in events have one fixed owner. Later registrations cannot
        # replace it, while application-specific events remain multicast.
        self._single_handler_event_types = {
            KiraMessageEvent,
            KiraMessageBatchEvent,
            KiraCustomEvent,
            KiraCommentEvent,
        }

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

        self.total_messages_stats = {
            "total_messages": 0,
        }
        self.stats.set_stats("messages", self.total_messages_stats)

        self._running_event = asyncio.Event()
        self.logger = get_logger("event_bus", "blue")

        self.subscribe(KiraCustomEvent, self._dispatch_custom_event)

    async def _dispatch_event(self, event):
        await self._process_event(event)

    async def _dispatch_custom_event(self, event: KiraCustomEvent):
        from core.plugin.plugin_handlers import event_handler_reg, EventType as PluginEventType

        for handler in event_handler_reg.get_handlers(PluginEventType.ON_CUSTOM_EVENT):
            filter_name = getattr(handler.handler, '_custom_event_name', None)
            if filter_name is None or filter_name == event.event_name:
                await handler.exec_handler(event)

    def subscribe(self, event_type: Union[str, Type], handler: Callable):
        """subscribe event"""
        if event_type in self._single_handler_event_types:
            if event_type in self.subscribers:
                self.logger.warning(
                    "Handler for built-in event %s is already registered; ignoring replacement",
                    event_type.__name__,
                )
                return
            self.subscribers[event_type] = [handler]
            return
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: Union[str, Type], handler: Callable):
        """unsubscribe event"""
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(handler)
            if not self.subscribers[event_type]:
                del self.subscribers[event_type]

    def add_middleware(self, middleware: Callable):
        """add a middleware"""
        self.middlewares.append(middleware)

    async def publish(self, event):
        """publish an event"""
        await self.event_queue.put(event)
        # try:
        #     # 通过中间件处理
        #     for middleware in self.middlewares:
        #         event = await middleware(event)
        #         if event is None:  # 中间件可以过滤事件
        #             return
        #
        #     try:
        #         self.event_queue.put_nowait(event)
        #     except asyncio.QueueFull:
        #         pass
        #
        # except Exception as e:
        #     raise

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
                    if isinstance(event, (KiraMessageEvent, KiraCommentEvent)):
                        self.total_messages_stats["total_messages"] += 1
                        self.stats.set_stats("messages", self.total_messages_stats)
                    await self._process_event(event)
                    self.event_bus_stats["processed"] += 1
                    self.stats.set_stats("event_bus", self.event_bus_stats)

            except Exception as e:
                self.event_bus_stats["errors"] += 1
                self.stats.set_stats("event_bus", self.event_bus_stats)

    async def _process_event(self, event):
        """处理单个事件"""
        if isinstance(event, (KiraMessageEvent, KiraMessageBatchEvent, KiraCustomEvent, KiraCommentEvent)):
            event_type = type(event)
        else:
            event_type = getattr(event, "event_type", None)

        # 处理所有订阅者
        if event_type in self.subscribers:
            for handler in tuple(self.subscribers[event_type]):
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
            if isinstance(event, (KiraMessageEvent, KiraCommentEvent)):
                self.total_messages_stats["total_messages"] += 1
                self.stats.set_stats("messages", self.total_messages_stats)
                if self.db:
                    platform = getattr(getattr(event, "adapter", None), "platform", None) or getattr(event, "platform", "unknown")
                    try:
                        await self.db.add_telemetry_message(int(time.time()), platform)
                    except Exception as e:
                        self.logger.debug(f"Failed to record telemetry message: {e}")
            task = asyncio.create_task(self._dispatch_event(event))

            def _log_task_error(t: asyncio.Task):
                try:
                    exc = t.exception()
                    if exc:
                        self.event_bus_stats["errors"] += 1
                        self.stats.set_stats("event_bus", self.event_bus_stats)
                        self.logger.error(f"Error in event dispatch task: {exc}")
                except asyncio.CancelledError:
                    return

            task.add_done_callback(_log_task_error)

    async def stop(self):
        """stop event bus"""
        self._running_event.clear()
        # for task in self._running_tasks:
        #     task.cancel()
        # await asyncio.gather(*self._running_tasks, return_exceptions=True)

    def get_stats(self) -> Dict[str, int]:
        """get statistics of event bus"""
        return self.event_bus_stats.copy()
