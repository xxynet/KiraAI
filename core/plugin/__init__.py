from .base import BasePlugin
from .plugin_context import PluginContext
from .manager import PluginManager
from .metadata import PluginInfo
from .pages import PluginPage, PageMenu
from .decorators import register_tool, on, register
from .handlers import EventType, Priority

from core.logging_manager import get_logger

logger = get_logger("plugin", "orange")


__all__ = [
    'BasePlugin',
    'PluginContext',
    'PluginManager',
    'PluginInfo',
    'PluginPage',
    'PageMenu',
    "register_tool",
    "register",
    "on",
    "EventType",
    "Priority",
    'logger'
]
