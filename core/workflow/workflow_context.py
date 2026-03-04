from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..provider import ProviderManager
from ..adapter import AdapterManager
from core.chat.session_manager import SessionManager
from core.config import KiraConfig
from core.event_bus import EventBus
from core.llm_client import LLMClient
from core.persona import PersonaManager
from core.utils.path_utils import get_data_path

if TYPE_CHECKING:
    from core.plugin.plugin_registry import PluginManager


@dataclass
class WorkflowContext:
    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    llm_api: LLMClient

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    memory_mgr: SessionManager

    plugin_mgr: Optional["PluginManager"] = None
