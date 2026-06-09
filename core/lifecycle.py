import asyncio
import os
import time
from typing import Optional

from .logging_manager import get_logger, setup_logging
from .config import KiraConfig
from .sticker_manager import StickerManager
from .message_manager import MessageProcessor
from .prompt_manager import PromptManager
from core.chat.session_manager import SessionManager
from .adapter import AdapterManager
from .statistics import Statistics
from .llm_client import LLMClient
from .event_bus import EventBus
from .persona import PersonaManager
from .provider import ProviderManager
from .plugin import PluginContext, PluginManager
from .plugin.plugin_handlers import event_handler_reg, EventType
from core.agent.mcp_mgr import MCPManager
from core.agent.skills_mgr import SkillsManager
from core.config import VERSION
from core.utils.path_utils import get_data_path
from core.temp_monitor import AsyncTempMonitor
from core.telemetry import TelemetryClient
from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.db.migrate_to_db import run_migrations


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self, stats: Statistics):
        self.stats = stats

        self.kira_config: Optional[KiraConfig] = None

        self.db_manager: Optional[DatabaseManager] = None

        self.db_service: Optional[DatabaseService] = None

        self.provider_manager: Optional[ProviderManager] = None

        self.llm_api: Optional[LLMClient] = None

        self.adapter_manager: Optional[AdapterManager] = None

        self.session_manager: Optional[SessionManager] = None

        self.persona_manager: Optional[PersonaManager] = None

        self.prompt_manager: Optional[PromptManager] = None

        self.message_processor: Optional[MessageProcessor] = None

        self.sticker_manager: Optional[StickerManager] = None

        self.event_bus: Optional[EventBus] = None

        self.plugin_context: Optional[PluginContext] = None

        self.plugin_manager: Optional[PluginManager] = None

        self.temp_monitor: Optional[AsyncTempMonitor] = None

        self.mcp_manager: Optional[MCPManager] = None

        self.skills_manager: Optional[SkillsManager] = None

        self.telemetry_client: Optional[TelemetryClient] = None

        self.tasks: list[asyncio.Task] = []

    async def schedule_tasks(self):
        self.tasks = [
            # asyncio.create_task(self.sticker_manager.scan_and_register_sticker(), name="sticker_scan")
        ]
        results = await asyncio.gather(*self.tasks, return_exceptions=True)
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                task = self.tasks[i]
                logger.error(f"Scheduled task '{task.get_name()}' failed: {result}")

    def _apply_network_env(self):
        network = self.kira_config.get("network") or {}
        proxy = network.get("http_proxy")
        if proxy:
            if not proxy.startswith(("http://", "https://")):
                logger.warning(f"Ignoring invalid http_proxy (must start with http:// or https://): {proxy}")
            else:
                os.environ["HTTP_PROXY"] = proxy
                os.environ["HTTPS_PROXY"] = proxy
                logger.info(f"HTTP proxy set from config: {proxy}")
        mirror = network.get("pypi_mirror")
        if mirror and not mirror.startswith(("http://", "https://")):
            logger.warning(f"Ignoring invalid pypi_mirror (must start with http:// or https://): {mirror}")

    async def init_and_run_system(self):
        """主函数：负责启动和初始化各个模块"""
        logger.info(f"✨ Starting KiraAI {VERSION}...")

        # ====== event bus ======
        event_queue: asyncio.Queue = asyncio.Queue()

        # ====== init KiraAI config ======
        self.kira_config = KiraConfig()

        # ====== apply network proxy config ======
        self._apply_network_env()

        # ====== apply logging config ======
        setup_logging(
            log_level=self.kira_config.get_config("logging.log_level", "INFO"),
            log_file_path=self.kira_config.get_config("logging.log_file_path"),
            log_file_max_size=self.kira_config.get_config("logging.log_file_max_size", 10),
        )

        # ====== init database manager ======
        db_url = self.kira_config.get_config("database.url")
        if not db_url:
            db_path = get_data_path() / "data.db"
            db_url = f"sqlite+aiosqlite:///{db_path.as_posix()}"
        db_echo = self.kira_config.get_config("database.echo", False)
        self.db_manager = DatabaseManager(db_url, echo=db_echo)
        await self.db_manager.init()
        logger.info(f"DatabaseManager initialized with URL: {db_url}")

        self.db_service = DatabaseService(self.db_manager)
        await self.db_service.init_tables()
        logger.info("Database tables initialized")

        await run_migrations(self.db_service)

        # ====== record startup time and init telemetry ======
        self.stats.set_stats("started_ts", int(time.time()))
        self.telemetry_client = TelemetryClient(self.db_service, self.kira_config, self.stats)
        try:
            await self.telemetry_client.initialize()
        except Exception as e:
            logger.debug(f"Telemetry client initialization failed: {e}")

        # ====== init ProviderManager config ======
        self.provider_manager = ProviderManager(self.db_service, self.kira_config)

        # ====== init LLMClient ======
        self.llm_api = LLMClient(self.kira_config, self.provider_manager)
        # ====== init adapter manager ======
        self.adapter_manager = AdapterManager(self.kira_config, event_queue)
        await self.adapter_manager.initialize()

        # ====== init session manager ======
        self.session_manager = SessionManager(self.db_service, self.kira_config)

        # ====== init persona manager ======
        self.persona_manager = PersonaManager(db=self.db_service)
        await self.persona_manager.init_persona()

        # ====== init sticker manager ======
        self.sticker_manager = StickerManager(db=self.db_service)
        await self.sticker_manager.init()

        # ====== init prompt manager ======
        self.prompt_manager = PromptManager(self.kira_config,
                                            self.persona_manager)

        # ====== init MCP manager ======
        try:
            self.mcp_manager = MCPManager(self.llm_api)
            await self.mcp_manager.init_mcp()
        except Exception as e:
            logger.error(f"Failed to initialize MCPManager: {e}")

        # ====== init skills manager ======

        self.skills_manager = SkillsManager()

        # ====== init message processor ======
        self.message_processor = MessageProcessor(
            db=self.db_service,
            kira_config=self.kira_config,
            llm_api=self.llm_api,
            provider_manager=self.provider_manager,
            skills_manager=self.skills_manager,
            adapter_manager=self.adapter_manager,
            session_manager=self.session_manager,
            prompt_manager=self.prompt_manager,
            mcp_manager=self.mcp_manager)

        self.tasks.append(
            asyncio.create_task(
                self.message_processor.cleanup_image_desc_cache_task(),
                name="image_desc_cache_cleanup"
            )
        )

        self.event_bus = EventBus(self.stats, event_queue, self.message_processor, db=self.db_service)
        self.message_processor.event_bus = self.event_bus

        # ====== init plugin system ======
        self.plugin_context = PluginContext(
            db=self.db_service,
            config=self.kira_config,
            event_bus=self.event_bus,
            provider_mgr=self.provider_manager,
            llm_api=self.llm_api,
            adapter_mgr=self.adapter_manager,
            persona_mgr=self.persona_manager,
            sticker_manager=self.sticker_manager,
            session_mgr=self.session_manager,
            message_processor=self.message_processor
        )

        self.plugin_manager = PluginManager(self.plugin_context)
        self.plugin_context.plugin_mgr = self.plugin_manager
        await self.plugin_manager.init()
        webui_app = getattr(self, "webui_app", None)
        if webui_app is not None:
            self.plugin_manager.set_web_app(webui_app)

        # Fire ON_LOADED lifecycle event (all plugins are initialized)
        loaded_handlers = event_handler_reg.get_handlers(EventType.ON_LOADED)
        for handler in loaded_handlers:
            await handler.exec_handler()

        # ====== init temp folder monitor ======
        temp_folder = get_data_path() / "temp"

        self.temp_monitor = AsyncTempMonitor(
            folder_path=str(temp_folder),
            kira_config=self.kira_config,
            check_interval=10,
            batch_size=20,
        )

        self.tasks.append(
            asyncio.create_task(
                self.temp_monitor.start_monitoring(),
                name="temp_folder_monitor"
            )
        )

        # ====== schedule tasks ======
        asyncio.create_task(self.schedule_tasks())

        logger.info("All modules initialized, starting message processing loop...")

        await self.event_bus.dispatch()

    async def stop(self):
        # Fire ON_SHUTDOWN lifecycle event (before any teardown)
        shutdown_handlers = event_handler_reg.get_handlers(EventType.ON_SHUTDOWN)
        for handler in shutdown_handlers:
            await handler.exec_handler()

        # shutdown telemetry client
        if self.telemetry_client:
            try:
                await self.telemetry_client.shutdown()
            except Exception as e:
                logger.error(f"Telemetry shutdown error: {e}")

        # terminate all plugins
        if self.plugin_manager:
            await self.plugin_manager.terminate()

        # terminate all running adapters
        await self.adapter_manager.stop_adapters()
        await self.event_bus.stop()

        # dispose database manager
        if self.db_manager:
            await self.db_manager.dispose()

        # cancel all tasks
        for task in self.tasks:
            task.cancel()
