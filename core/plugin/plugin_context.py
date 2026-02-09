from dataclasses import dataclass

from ..provider import ProviderManager
from ..adapter import AdapterManager
from core.chat.memory_manager import MemoryManager
from core.config import KiraConfig
from core.event_bus import EventBus
from core.llm_client import LLMClient
from core.persona import PersonaManager


@dataclass
class PluginContext:
    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    llm_api: LLMClient

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    memory_mgr: MemoryManager
