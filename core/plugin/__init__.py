from core.logging_manager import get_logger

from .base import BasePlugin
from .decorators import on, register, register_tool
from .handlers import EventType, Priority
from .manager import PluginManager
from .metadata import PluginInfo
from .pages import PageMenu, PluginPage
from .plugin_context import PluginContext

logger = get_logger("plugin", "orange")


__all__ = [
    'BasePlugin',
    "EventType",
    'PageMenu',
    'PluginContext',
    'PluginInfo',
    'PluginManager',
    'PluginPage',
    "Priority",
    'logger',
    "on",
    "register",
    "register_tool"
]
