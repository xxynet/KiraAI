from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from core.agent.func_tool_manager import FuncToolManager
from core.chat.session_manager import SessionManager
from core.config import KiraConfig
from core.event_bus import EventBus
from core.persona import PersonaManager

from ..adapter import AdapterManager
from ..provider import ProviderManager

if TYPE_CHECKING:
    from core.plugin.manager import PluginManager


@dataclass
class WorkflowContext:
    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    tool_mgr: FuncToolManager

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    memory_mgr: SessionManager

    plugin_mgr: Optional["PluginManager"] = None
