from dataclasses import dataclass, field
from asyncio import Queue
from typing import Callable

from ..provider import ProviderManager
from ..adapter import AdapterManager
from ..memory_manager import MemoryManager
from core.config import KiraConfig


@dataclass
class PluginContext:
    config: KiraConfig

    event_queue: Queue

    provider_mgr: ProviderManager

    adapter_mgr: AdapterManager

    memory_mgr: MemoryManager

    _registered_tools: dict = field(default_factory=dict, init=False)

    _registered_hooks: dict = field(default_factory=dict, init=False)
