from __future__ import annotations

import asyncio
from typing import Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING
from enum import Enum, auto
from dataclasses import dataclass, field
from datetime import datetime
import uuid

from .statistics import Statistics
from .logging_manager import get_logger

from core.chat import KiraMessageEvent, KiraCommentEvent


class EventType(Enum):
    """事件类型枚举"""
    KiraAILoaded = auto()

    """When a message arrives, could be KiraMessageEvent, KiraCommentEvent, etc..."""
    MsgRecv = auto()

    """THe message has been processed and has a result"""
    MsgResult = auto()

    """The message has been sent to adapter"""
    MsgSent = auto()


class EventBus:
    """事件总线"""

    def __init__(self, stats: Statistics, event_queue: asyncio.Queue, message_processor: "MessageProcessor"):
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

        self.total_messages_stats = {
            "total_messages": 0,
        }
        self.stats.set_stats("messages", self.total_messages_stats)

        self._running_event = asyncio.Event()
        self._pending_dispatches: set[asyncio.Task] = set()
        self.logger = get_logger("event_bus", "blue")

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
        await self.event_queue.put(event)

    async def dispatch(self):
        """start event bus"""
        self._running_event.set()

        while self._running_event.is_set():
            event = await self.event_queue.get()
            # None sentinel injected by stop() to unblock the consumer
            if event is None:
                break
            if isinstance(event, (KiraMessageEvent, KiraCommentEvent)):
                self.total_messages_stats["total_messages"] += 1
                self.stats.set_stats("messages", self.total_messages_stats)
            task = asyncio.create_task(self._dispatch_event(event))
            self._pending_dispatches.add(task)

            def _on_task_done(t: asyncio.Task):
                self._pending_dispatches.discard(t)
                try:
                    exc = t.exception()
                    if exc:
                        self.event_bus_stats["errors"] += 1
                        self.stats.set_stats("event_bus", self.event_bus_stats)
                        self.logger.error(f"Error in event dispatch task: {exc}")
                    else:
                        self.event_bus_stats["processed"] += 1
                        self.stats.set_stats("event_bus", self.event_bus_stats)
                except asyncio.CancelledError:
                    return

            task.add_done_callback(_on_task_done)

    async def stop(self):
        """stop event bus"""
        self._running_event.clear()
        await self.event_queue.put(None)
        if self._pending_dispatches:
            await asyncio.wait(self._pending_dispatches, timeout=10.0)

    def get_stats(self) -> Dict[str, int]:
        """get statistics of event bus"""
        return self.event_bus_stats.copy()
