from dataclasses import dataclass
import inspect
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from ..provider import ProviderManager
from ..adapter import AdapterManager
from core.chat.memory_manager import MemoryManager
from core.config import KiraConfig
from core.event_bus import EventBus
from core.llm_client import LLMClient
from core.persona import PersonaManager
from core.utils.path_utils import get_data_path

if TYPE_CHECKING:
    from .plugin_registry import PluginManager


@dataclass
class PluginContext:
    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    llm_api: LLMClient

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    memory_mgr: MemoryManager

    plugin_mgr: Optional["PluginManager"] = None

    def get_plugin_data_dir(self):
        base_dir = get_data_path() / "plugin_data"
        frame = inspect.currentframe()
        if frame is None:
            return base_dir
        caller_frame = frame.f_back
        if caller_frame is None:
            return base_dir
        module_name = caller_frame.f_globals.get("__name__", "")
        plugin_id = None
        if self.plugin_mgr is not None and module_name:
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)
        if not plugin_id:
            return
        plugin_dir = base_dir / plugin_id
        plugin_dir.mkdir(parents=True, exist_ok=True)
        return plugin_dir
