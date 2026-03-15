import asyncio
import time
from typing import Optional

from .logging_manager import get_logger
from .config import KiraConfig
from .sticker_manager import StickerManager
from .message_manager import MessageProcessor
from .prompt_manager import PromptManager
from core.chat.session_manager import SessionManager
from .adapter import AdapterManager
from .statistics import Statistics
from .llm_client import LLMClient
from .tool_manager import register_all_tools
from .event_bus import EventBus
from .persona import PersonaManager
from .provider import ProviderManager
from .plugin import PluginContext, PluginManager
from core.agent.mcp_mgr import MCPManager
from core.config import VERSION
from core.utils.path_utils import get_data_path
from core.temp_monitor import AsyncTempMonitor


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self, stats: Statistics):
        self.stats = stats

        self.kira_config: Optional[KiraConfig] = None

        self.provider_manager: Optional[ProviderManager] = None

        self.llm_api: Optional[LLMClient] = None

        self.adapter_manager: Optional[AdapterManager] = None

        self.memory_manager: Optional[SessionManager] = None

        self.persona_manager: Optional[PersonaManager] = None

        self.prompt_manager: Optional[PromptManager] = None

        self.message_processor: Optional[MessageProcessor] = None

        self.sticker_manager: Optional[StickerManager] = None

        self.event_bus: Optional[EventBus] = None

        self.plugin_context: Optional[PluginContext] = None

        self.plugin_manager: Optional[PluginManager] = None

        self.temp_monitor: Optional[AsyncTempMonitor] = None

        self.mcp_manager: Optional[MCPManager] = None
        self.tasks: list[asyncio.Task] = []

    async def schedule_tasks(self):
        self.tasks = [
            asyncio.create_task(self.sticker_manager.scan_and_register_sticker(), name="sticker_scan")
        ]
        results = await asyncio.gather(*self.tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task = self.tasks[i]
                logger.error(f"Scheduled task '{task.get_name()}' failed: {result}")

    async def init_and_run_system(self):
        """主函数：负责启动和初始化各个模块"""
        logger.info(f"✨ Starting KiraAI {VERSION}...")

        # ====== event bus ======
        event_queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()

        # ====== init KiraAI config ======
        self.kira_config = KiraConfig()

        # ====== init ProviderManager config ======
        self.provider_manager = ProviderManager(self.kira_config)

        # ====== init LLMClient ======
        self.llm_api = LLMClient(self.kira_config, self.provider_manager)
        await register_all_tools(self.llm_api)

        # ====== init adapter manager ======
        self.adapter_manager = AdapterManager(self.kira_config, loop, event_queue, self.llm_api)
        await self.adapter_manager.initialize()

        # ====== init sticker manager ======
        self.sticker_manager = StickerManager(self.llm_api)

        # ====== init memory manager ======
        self.memory_manager = SessionManager(self.kira_config)

        # ====== init persona manager ======
        self.persona_manager = PersonaManager()

        # ====== init prompt manager ======
        self.prompt_manager = PromptManager(self.kira_config,
                                            self.sticker_manager,
                                            self.persona_manager)

        # ====== init message processor ======
        self.message_processor = MessageProcessor(self.kira_config,
                                                  self.llm_api,
                                                  self.provider_manager,
                                                  self.adapter_manager,
                                                  self.memory_manager,
                                                  self.prompt_manager)

        self.event_bus = EventBus(self.stats, event_queue, self.message_processor)

        # ====== init MCP manager ======
        try:
            self.mcp_manager = MCPManager(self.llm_api)
            await self.mcp_manager.init_mcp()
        except Exception as e:
            logger.error(f"Failed to initialize MCPManager: {e}")

        # ====== init plugin system ======
        self.plugin_context = PluginContext(
            config=self.kira_config,
            event_bus=self.event_bus,
            provider_mgr=self.provider_manager,
            llm_api=self.llm_api,
            adapter_mgr=self.adapter_manager,
            persona_mgr=self.persona_manager,
            sticker_manager=self.sticker_manager,
            session_mgr=self.memory_manager,
            message_processor=self.message_processor
        )

        self.plugin_manager = PluginManager(self.plugin_context)
        self.plugin_context.plugin_mgr = self.plugin_manager
        await self.plugin_manager.init()

        # ====== init temp folder monitor ======
        temp_folder = get_data_path() / "temp"
        max_temp_size = getattr(self.kira_config, "max_temp_size_mb", 100)  # 从配置读取，默认100MB
        check_interval = getattr(self.kira_config, "temp_check_interval", 60)  # 默认60秒

        self.temp_monitor = AsyncTempMonitor(
            folder_path=str(temp_folder),
            max_size_mb=50,
            check_interval=10,
            batch_size=20
        )

        self.tasks.append(
            asyncio.create_task(
                self.temp_monitor.start_monitoring(),
                name="temp_folder_monitor"
            )
        )

        # ====== schedule tasks ======
        asyncio.create_task(self.schedule_tasks())

        self.stats.set_stats("started_ts", int(time.time()))

        logger.info("All modules initialized, starting message processing loop...")

        await self.event_bus.dispatch()

    async def stop(self):
        # terminate all running adapters
        await self.adapter_manager.stop_adapters()
        await self.event_bus.stop()

        # cancel all tasks
        for task in self.tasks:
            task.cancel()
