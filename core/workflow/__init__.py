from __future__ import annotations

from abc import ABC
from asyncio import Semaphore
from typing import Generic, TYPE_CHECKING, TypeVar

from .base_stage import BaseStage
from .workflow_context import WorkflowContext
from core.chat import KiraMessageEvent, KiraMessageBatchEvent

if TYPE_CHECKING:
    from .src.im.context import IMWorkflowContext

ContextT = TypeVar("ContextT")


class BaseWorkflow(ABC, Generic[ContextT]):
    def __init__(self, ctx: ContextT):
        self.ctx = ctx


class IMWorkflow(BaseWorkflow["IMWorkflowContext"]):
    def __init__(self, ctx: IMWorkflowContext, max_concurrent_messages: int = 3):
        super().__init__(ctx)
        self.message_processing_semaphore = Semaphore(max_concurrent_messages)

    async def handle_event(self, event: KiraMessageEvent):
        raise NotImplementedError

    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        raise NotImplementedError


__all__ = ["BaseStage", "BaseWorkflow", "IMWorkflow", "WorkflowContext"]
