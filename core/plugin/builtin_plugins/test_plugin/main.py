import json
from pathlib import Path

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent

from core.utils.tool_utils import BaseTool


class TestPlugin(BasePlugin):
    """
    Test plugin that provides a simple test functionality
    """
    
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.default_value = None
    
    async def initialize(self):
        """
        Initialize the search plugin
        Load Tavily API key from plugin configuration
        """
        # Get default_value from plugin config
        self.default_value = self.plugin_cfg.get('test_string')

        logger.info(f"[TestPlugin] Config: {self.plugin_cfg}")
    
    async def terminate(self):
        """
        Cleanup when plugin is terminated
        """
        pass

    @on.im_message(priority=Priority.MEDIUM)
    async def handle_msg(self, event: KiraMessageEvent):
        pass
