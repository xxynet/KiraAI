import asyncio
from asyncio import Lock, Semaphore
from typing import Callable, Optional, TYPE_CHECKING

from core.agent.func_tool_manager import FuncToolManager
from core.agent.message import OpenAIMessage
from core.agent.mcp_mgr import MCPManager
from core.agent.skills_mgr import SkillsManager
from core.adapter import AdapterManager
from core.image_desc_cache import ImageDescCache
from core.chat.session_buffer import SessionBuffer, SessionBufferManager
from core.workflow.src.im.message_delivery import MessageDeliveryService
from core.workflow.src.im.message_formatter import MessageFormatter
from core.chat.message_history import MessageHistoryService
from core.workflow.src.im.native_content import MessageMediaService
from core.chat.message_utils import (
    KiraIMMessage, KiraIMSentResult, KiraMessageEvent, KiraMessageBatchEvent,
    KiraCommentEvent, MessageChain,
)
from core.chat.session_manager import SessionManager
from core.db.service import DatabaseService
from core.logging_manager import get_logger
from core.plugin.handlers import event_handler_reg, EventType
from core.prompt_manager import PromptManager
from core.provider import ProviderManager
from core.workflow.src.im.batching import publish_buffered_messages
from core.workflow.src.im.context import IMWorkflowContext
from core.workflow.src.im.workflow import DefaultIMWorkflow

if TYPE_CHECKING:
    from core.event_bus import EventBus

logger = get_logger("message", "cyan")


class MessageProcessor:
    """Core message processor, responsible for IM processing and comment event delivery"""

    def __init__(self,
                 db: DatabaseService,
                 kira_config,
                 tool_manager: FuncToolManager,
                 provider_manager: ProviderManager,
                 skills_manager: SkillsManager,
                 adapter_manager: AdapterManager,
                 session_manager: SessionManager,
                 prompt_manager: PromptManager,
                 mcp_manager: MCPManager,
                 message_history: MessageHistoryService,
                 max_concurrent_messages: int = 3):
        self.db = db
        self.kira_config = kira_config
        self.bot_config = kira_config["bot_config"].get("bot")
        self.max_message_interval = float(self.bot_config.get("max_message_interval"))
        self.max_buffer_messages = int(self.bot_config.get("max_buffer_messages"))

        self.tool_manager = tool_manager
        self.event_bus: Optional[EventBus] = None

        self.message_processing_semaphore = Semaphore(max_concurrent_messages)

        # managers
        self.session_manager = session_manager
        self.message_history = message_history
        self.prompt_manager = prompt_manager
        self.provider_mgr = provider_manager
        self.adapter_mgr = adapter_manager
        self.skills_manager = skills_manager
        self.mcp_manager = mcp_manager

        # message buffer
        self.session_locks: dict[str, asyncio.Lock] = {}

        self.session_buffer = SessionBufferManager(max_count=self.max_buffer_messages)

        # image description cache
        self.image_desc_cache = ImageDescCache(db)

        logger.info("MessageProcessor initialized")

    async def handle_event(self, event):
        """Handle events received from the event bus."""
        if isinstance(event, KiraMessageBatchEvent):
            await self.handle_im_batch_message(event)
            return

        async with self.message_processing_semaphore:
            if isinstance(event, KiraMessageEvent):
                await self.handle_im_message(event)
            elif isinstance(event, KiraCommentEvent):
                await self.handle_cmt_message(event)

    @property
    def message_formatter(self) -> MessageFormatter:
        if not hasattr(self, "_message_formatter"):
            self._message_formatter = MessageFormatter(
                self.kira_config,
                getattr(self, "provider_mgr", None),
                getattr(self, "session_manager", None),
                getattr(self, "image_desc_cache", None),
            )
        return self._message_formatter

    @property
    def message_media(self) -> MessageMediaService:
        if not hasattr(self, "_message_media"):
            self._message_media = MessageMediaService()
        return self._message_media

    @property
    def message_delivery(self) -> MessageDeliveryService:
        if not hasattr(self, "_message_delivery"):
            self._message_delivery = MessageDeliveryService(
                self.kira_config,
                getattr(self, "adapter_mgr", None),
                getattr(self, "message_history", None),
            )
        return self._message_delivery

    @property
    def session_buffer(self) -> SessionBufferManager:
        if not hasattr(self, "_session_buffer"):
            self._session_buffer = SessionBufferManager(
                max_count=getattr(self, "max_buffer_messages", None))
        return self._session_buffer

    @session_buffer.setter
    def session_buffer(self, value: SessionBufferManager):
        self._session_buffer = value

    @property
    def session_locks(self) -> dict[str, asyncio.Lock]:
        return self.message_delivery.session_locks

    @session_locks.setter
    def session_locks(self, value: dict[str, asyncio.Lock]):
        self.message_delivery.session_locks = value

    @property
    def min_message_delay(self) -> float:
        return self.message_delivery.min_message_delay

    @property
    def max_message_delay(self) -> float:
        return self.message_delivery.max_message_delay

    def get_session_lock(self, sid: str) -> Lock:
        """get session lock to avoid sending message simultaneously"""
        return self.message_delivery.get_session_lock(sid)

    def get_session_buffer_length(self, sid: str) -> int:
        return self.session_buffer.get_buffer(sid).get_length()

    async def pop_session_messages(self, sid: str, count: int = 1):
        self.session_buffer.get_buffer(sid).pop(count)

    async def flush_session_messages(
        self,
        sid: str,
        extra_event: KiraMessageEvent | None = None,
        filter_fn: Optional[Callable[[KiraMessageEvent], bool]] = None,
    ) -> bool:
        """Publish buffered events matching a synchronous predicate, or all events by default."""
        return await publish_buffered_messages(
            self.session_buffer, self.event_bus, sid, extra_event=extra_event, filter_fn=filter_fn)

    async def message_format_to_text(self, message_chain: MessageChain, session_id: Optional[str] = None, capabilities: Optional[dict] = None):
        """将平台使用标准消息格式封装的消息转换为LLM可以接收的字符串"""
        return await self.message_formatter.format_to_text(message_chain, session_id, capabilities)

    @staticmethod
    def _iter_message_images(message_chain: MessageChain):
        """Yield every image-like element contained in a message chain."""
        yield from MessageMediaService.iter_images(message_chain)

    async def _build_native_content(self, message: KiraIMMessage, session_id: str) -> list[dict]:
        """Persist incoming images and create the provider-independent content parts."""
        return await self.message_media.build_native_content(message, session_id)

    async def _record_incoming_message(self, message, session_id, platform):
        history = getattr(self, "message_history", None)
        if history is not None:
            return await history.record_incoming_safely(message, session_id, platform)

    async def send_message_chain(self, session: str, chain: MessageChain, *, memory_message: OpenAIMessage | None = None, self_id: str | None = None) -> KiraIMSentResult:
        return await self.message_delivery.send_message_chain(
            session, chain, memory_message=memory_message, self_id=self_id)

    async def cleanup_image_desc_cache_task(self):
        """Background task: clean up expired image desc cache every 24 hours."""
        await self.image_desc_cache.cleanup_task()

    @property
    def im_workflow(self) -> DefaultIMWorkflow:
        """Inject shared services on first use and refresh the late-bound event bus."""
        if not hasattr(self, "_im_workflow"):
            self._im_workflow = DefaultIMWorkflow(IMWorkflowContext(
                message_formatter=self.message_formatter,
                message_media=self.message_media,
                message_buffer=self.session_buffer,
                message_delivery=self.message_delivery,
                config=self.kira_config,
                session_manager=self.session_manager,
                prompt_manager=self.prompt_manager,
                provider_mgr=self.provider_mgr,
                tool_manager=self.tool_manager,
                skills_manager=self.skills_manager,
                mcp_manager=self.mcp_manager,
                db=self.db,
                message_history=getattr(self, "message_history", None),
            ))
        self._im_workflow.ctx.event_bus = self.event_bus
        return self._im_workflow

    async def handle_im_message(self, event: KiraMessageEvent):
        """process im message"""
        await self.im_workflow.handle_event(event)

    async def handle_im_batch_message(self, event: KiraMessageBatchEvent):
        await self.im_workflow.handle_batch_event(event)

    async def handle_cmt_message(self, event: KiraCommentEvent):
        """Deliver comments to plugins without prescribing a processing workflow."""
        for handler in tuple(event_handler_reg.get_handlers(EventType.ON_COMMENT)):
            if event.is_stopped:
                break
            await handler.exec_handler(event)
