from dataclasses import dataclass, field
from asyncio import Queue
from typing import Callable

from ..provider import ProviderManager
from ..adapter import AdapterManager
from ..memory_manager import MemoryManager
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

    _registered_tools: dict = field(default_factory=dict, init=False)

    _registered_hooks: dict = field(default_factory=dict, init=False)
