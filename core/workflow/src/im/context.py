from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from core.agent.message import OpenAIMessage
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraStepResult
from core.provider import LLMModelClient, LLMRequest
from core.tag import TagSet

if TYPE_CHECKING:
    from core.agent.func_tool_manager import FuncToolManager
    from core.agent.mcp_mgr import MCPManager
    from core.agent.skills_mgr import SkillsManager
    from core.chat.message_history import MessageHistoryService
    from core.chat.session_manager import SessionManager
    from core.config import KiraConfig
    from core.db.service import DatabaseService
    from core.event_bus import EventBus
    from core.chat.session_buffer import SessionBufferManager
    from core.workflow.src.im.message_delivery import MessageDeliveryService
    from core.workflow.src.im.message_formatter import MessageFormatter
    from core.workflow.src.im.native_content import MessageMediaService
    from core.prompt_manager import PromptManager
    from core.provider import ProviderManager


@dataclass
class IMWorkflowContext:
    """Services shared by IM stages without depending on the event dispatcher."""

    message_formatter: MessageFormatter
    message_media: MessageMediaService
    message_buffer: SessionBufferManager
    message_delivery: MessageDeliveryService
    config: KiraConfig
    session_manager: SessionManager
    prompt_manager: PromptManager
    provider_mgr: ProviderManager
    tool_manager: FuncToolManager
    skills_manager: SkillsManager
    mcp_manager: MCPManager
    db: DatabaseService
    message_history: MessageHistoryService | None = None
    event_bus: EventBus | None = None


@dataclass
class IMEventContext:
    services: IMWorkflowContext
    event: KiraMessageEvent

    sid: str = field(init=False)

    def __post_init__(self):
        self.sid = self.event.session.sid


@dataclass
class IMBatchContext:
    """Mutable state belongs to one batch and is never stored on a stage."""

    services: IMWorkflowContext
    event: KiraMessageBatchEvent
    image_mode: str = "vlm_description"
    incoming_record_ids: dict[int, str | None] = field(default_factory=dict)
    request: LLMRequest | None = None
    tag_set: TagSet = field(default_factory=TagSet)
    model_group: list[LLMModelClient] = field(default_factory=list)
    new_messages: list[OpenAIMessage] = field(default_factory=list)
    turn_steps: list[KiraStepResult] = field(default_factory=list)

    sid: str = field(init=False)

    def __post_init__(self):
        self.sid = self.event.session.sid
