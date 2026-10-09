from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from core.chat.session_buffer import SessionBufferManager
from core.workflow.src.im.context import IMWorkflowContext
from core.workflow.src.im.message_delivery import MessageDeliveryService
from core.workflow.src.im.message_formatter import MessageFormatter
from core.workflow.src.im.native_content import MessageMediaService


def make_workflow_context(**overrides):
    """Build explicit services for workflow tests without a processor factory."""
    config = overrides.pop("config", SimpleNamespace(get_config=lambda key, default=None: default))
    session_manager = overrides.pop("session_manager", Mock())
    provider_mgr = overrides.pop("provider_mgr", Mock())
    message_history = overrides.pop("message_history", None)
    adapter_mgr = overrides.pop("adapter_mgr", Mock())
    image_desc_cache = overrides.pop("image_desc_cache", None)
    services = dict(
        config=config,
        session_manager=session_manager,
        provider_mgr=provider_mgr,
        message_history=message_history,
        message_formatter=MessageFormatter(config, provider_mgr, session_manager, image_desc_cache),
        message_delivery=MessageDeliveryService(config, adapter_mgr, message_history),
        message_media=MessageMediaService(),
        message_buffer=SessionBufferManager(),
        event_bus=SimpleNamespace(publish=AsyncMock()),
        prompt_manager=Mock(),
        tool_manager=Mock(),
        skills_manager=Mock(),
        mcp_manager=Mock(),
        db=Mock(),
    )
    services.update(overrides)
    return IMWorkflowContext(**services)
