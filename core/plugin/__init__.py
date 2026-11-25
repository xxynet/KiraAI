from core.agent.hook_context import ToolCallContext
from core.logging_manager import get_logger

from .base import BasePlugin
from .decorators import on, register, register_tool
from .handlers import EventType, Priority
from .manager import PluginManager
from .metadata import PluginInfo
from .pages import PageMenu, PluginPage
from .plugin_agent_executor import PluginAgentExecutor
from .plugin_context import PluginContext
from .subagent import SubAgentPreset

logger = get_logger("plugin", "orange")


__all__ = [
    'BasePlugin',
    "EventType",
    'PageMenu',
    'PluginAgentExecutor',
    'PluginContext',
    'PluginInfo',
    'PluginManager',
    'PluginPage',
    "Priority",
    "SubAgentPreset",
    "ToolCallContext",
    'logger',
    "on",
    "register",
    "register_tool"
]
