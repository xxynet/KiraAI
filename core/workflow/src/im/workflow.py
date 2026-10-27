from core.chat import KiraMessageBatchEvent, KiraMessageEvent
from core.utils.media_refs import session_media_scope
from core.workflow import BaseStage, IMWorkflow

from .context import IMBatchContext, IMEventContext, IMWorkflowContext
from .stages.assemble import AssembleRequestStage
from .stages.execute import ExecuteAgentStage
from .stages.finalize import FinalizeStage
from .stages.prepare import PrepareBatchStage
from .stages.receive import ReceiveStage, RouteStage
from .stages.request import BuildRequestStage


class DefaultIMWorkflow(IMWorkflow):
    """Coordinate stateless stages with a fresh context for every event.

    A stage returns False to end the pipeline. Do not stop solely on event.stop():
    once agent execution starts, final-result hooks and memory saving still run.
    """

    def __init__(self, ctx: IMWorkflowContext, max_concurrent_messages: int = 3):
        super().__init__(ctx, max_concurrent_messages=max_concurrent_messages)
        self.event_stages: tuple[BaseStage[IMEventContext], ...] = (
            ReceiveStage(), RouteStage(),
        )
        self.batch_stages: tuple[BaseStage[IMBatchContext], ...] = (
            PrepareBatchStage(),
            BuildRequestStage(),
            AssembleRequestStage(),
            ExecuteAgentStage(),
            FinalizeStage(),
        )

    async def handle_event(self, event: KiraMessageEvent):
        async with self.message_processing_semaphore:
            ctx = IMEventContext(self.ctx, event)
            for stage in self.event_stages:
                if not await stage.run(ctx):
                    return

    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        async with session_media_scope():
            ctx = IMBatchContext(self.ctx, event)
            for stage in self.batch_stages:
                if not await stage.run(ctx):
                    return
