from abc import ABC, abstractmethod

from core.workflow import WorkflowContext, WorkflowType, register_workflow, IMWorkflow
from core.chat import KiraMessageEvent, KiraMessageBatchEvent


@register_workflow("default", WorkflowType.IM)
class DefaultIMWorkflow(IMWorkflow):
    def __init__(self, ctx: WorkflowContext):
        super().__init__(ctx)

    async def handle_event(self, event: KiraMessageEvent):
        pass

    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        pass
