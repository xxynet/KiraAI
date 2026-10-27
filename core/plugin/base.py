from abc import ABC, abstractmethod

from .plugin_context import PluginContext


class BasePlugin(ABC):
    def __init__(self, ctx: PluginContext, cfg: dict):
        self.ctx = ctx
        self.plugin_cfg = cfg

    @abstractmethod
    async def initialize(self):
        """Called when the plugin is loaded"""

    @abstractmethod
    async def terminate(self):
        """Called before the plugin is to be turned off"""

