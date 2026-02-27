from abc import ABC, abstractmethod

from .workflow_context import WorkflowContext
from .workflow_registry import register_workflow, WorkflowType
from core.chat import KiraMessageEvent, KiraMessageBatchEvent


class BaseWorkflow(ABC):
    type: WorkflowType

    def __init__(self, ctx: WorkflowContext):
        self.ctx = ctx


class IMWorkflow(BaseWorkflow):
    def __init__(self, ctx: WorkflowContext):
        super().__init__(ctx)

    async def handle_event(self, event: KiraMessageEvent):
        raise NotImplementedError

    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        raise NotImplementedError


__all__ = ["BaseWorkflow", "IMWorkflow", "register_workflow", "WorkflowType", "WorkflowContext"]
