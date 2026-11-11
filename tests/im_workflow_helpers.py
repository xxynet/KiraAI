from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from core.agent.subagent_presets import SubAgentPresetStore
from core.chat.im_message_route import IMMessageRoute
from core.chat.message_router import MessageRouter
from core.chat.session_buffer import SessionBufferManager
from core.chat.session_manager import SessionManager
from core.workflow import IMWorkflow
from core.workflow.src.im.context import IMWorkflowContext
from core.workflow.src.im.message_delivery import MessageDeliveryService
from core.workflow.src.im.message_formatter import MessageFormatter
from core.workflow.src.im.native_content import MessageMediaService


def make_session_manager():
    """Resolve test targets through the real manager without stored records."""
    return SessionManager(SimpleNamespace(
        get_chat_session=AsyncMock(return_value=None),
        get_chat_session_by_id=AsyncMock(return_value=None),
    ), Mock())


def make_message_router(adapter_mgr, message_delivery=None, *, workflow=None):
    """Build real IM routing with explicit adapter and delivery test services."""
    if message_delivery is None:
        message_delivery = MessageDeliveryService(Mock(), adapter_mgr, None)
    if workflow is None:
        session_manager = make_session_manager()
        workflow = Mock(spec=IMWorkflow)
    else:
        session_manager = workflow.ctx.session_manager
    router = MessageRouter(session_manager=session_manager)
    if hasattr(workflow, "ctx"):
        workflow.ctx.message_router = router
    router.register_route(
        IMMessageRoute(
            delivery=message_delivery,
            adapter_mgr=adapter_mgr,
            workflow=workflow,
        ),
        priority=-100,
    )
    return router


def make_workflow_context(**overrides):
    """Build explicit services for workflow tests without a processor factory."""
    config = overrides.pop("config", SimpleNamespace(get_config=lambda key, default=None: default))
    session_manager = overrides.pop("session_manager", make_session_manager())
    provider_mgr = overrides.pop("provider_mgr", Mock())
    message_history = overrides.pop("message_history", None)
    persona_mgr = overrides.pop("persona_mgr", None)
    adapter_mgr = overrides.pop("adapter_mgr", Mock())
    image_desc_cache = overrides.pop("image_desc_cache", None)
    services = {
        "config": config,
        "session_manager": session_manager,
        "provider_mgr": provider_mgr,
        "message_history": message_history,
        "message_formatter": MessageFormatter(config, provider_mgr, session_manager, image_desc_cache),
        "message_delivery": MessageDeliveryService(
            config, adapter_mgr, persona_mgr, message_history,
        ),
        "message_media": MessageMediaService(),
        "message_buffer": SessionBufferManager(),
        "event_bus": SimpleNamespace(publish=AsyncMock()),
        "prompt_manager": Mock(),
        "tool_manager": Mock(),
        "skills_manager": Mock(),
        "subagent_manager": SimpleNamespace(presets=SubAgentPresetStore()),
        "mcp_manager": Mock(),
        "db": Mock(),
    }
    services.update(overrides)
    if "message_router" not in overrides:
        services["message_router"] = make_message_router(
            adapter_mgr=services["message_delivery"].adapter_mgr,
            message_delivery=services["message_delivery"],
        )
    return IMWorkflowContext(**services)
