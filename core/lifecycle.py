import asyncio
import os
import time
from typing import Optional

from .logging_manager import get_logger, setup_logging
from .config import KiraConfig
from .sticker_manager import StickerManager
from .message_manager import MessageProcessor
from core.chat.session_buffer import SessionBufferManager
from core.workflow.src.im.context import IMWorkflowContext
from core.workflow.src.im.workflow import DefaultIMWorkflow
from core.workflow.src.im.message_delivery import MessageDeliveryService
from core.workflow.src.im.message_formatter import MessageFormatter
from core.workflow.src.im.native_content import MessageMediaService
from .image_desc_cache import ImageDescCache
from .prompt_manager import PromptManager
from core.chat.session_manager import SessionManager
from core.chat.session_media_manager import SessionMediaManager
from core.chat.message_history import MessageHistoryService
from core.chat.message_history_cleanup import MessageHistoryCleanup
from .adapter import AdapterManager
from .statistics import Statistics
from .agent.func_tool_manager import FuncToolManager
from .event_bus import EventBus
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraCommentEvent
from .persona import PersonaManager
from .provider import ProviderManager
from .plugin import PluginContext, PluginManager
from .plugin.handlers import event_handler_reg, EventType
from core.agent.mcp_mgr import MCPManager
from core.agent.skills_mgr import SkillsManager
from core.config import VERSION
from core.utils.path_utils import get_data_path
from core.temp_monitor import AsyncTempMonitor
from core.telemetry import TelemetryClient
from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.db.migrate_to_db import run_migrations, migrate_selfie_reference_image


logger = get_logger("lifecycle", "blue")


class KiraLifecycle:
    """life cycle of KiraAI, managing all tasks and modules"""

    def __init__(self, stats: Statistics):
        self.stats = stats

        self.kira_config: Optional[KiraConfig] = None

        self.db_manager: Optional[DatabaseManager] = None

        self.db_service: Optional[DatabaseService] = None

        self.provider_manager: Optional[ProviderManager] = None

        self.tool_manager: Optional[FuncToolManager] = None

        self.adapter_manager: Optional[AdapterManager] = None

        self.session_manager: Optional[SessionManager] = None

        self.persona_manager: Optional[PersonaManager] = None

        self.prompt_manager: Optional[PromptManager] = None

        self.message_processor: Optional[MessageProcessor] = None

        self.image_desc_cache: Optional[ImageDescCache] = None

        self.sticker_manager: Optional[StickerManager] = None

        self.event_bus: Optional[EventBus] = None

        self.plugin_context: Optional[PluginContext] = None

        self.plugin_manager: Optional[PluginManager] = None

        self.temp_monitor: Optional[AsyncTempMonitor] = None

        self.mcp_manager: Optional[MCPManager] = None

        self.skills_manager: Optional[SkillsManager] = None

        self.telemetry_client: Optional[TelemetryClient] = None

        self.message_history: Optional[MessageHistoryService] = None

        self.message_history_cleanup: Optional[MessageHistoryCleanup] = None

        self.tasks: list[asyncio.Task] = []

    def schedule_tasks(self):
        """Report failures of registered background tasks as soon as they finish."""
        def report_result(task: asyncio.Task):
            if task.cancelled():
                return
            error = task.exception()
            if error is not None:
                logger.error(
                    "Scheduled task '%s' failed: %s", task.get_name(), error,
                    exc_info=(type(error), error, error.__traceback__),
                )

        for task in self.tasks:
            task.add_done_callback(report_result)

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

        # ====== init function tool manager ======
        self.tool_manager = FuncToolManager(self.kira_config)
        # ====== init adapter manager ======
        self.adapter_manager = AdapterManager(self.kira_config, event_queue)
        await self.adapter_manager.initialize()

        # ====== init event bus ======
        self.event_bus = EventBus(self.stats, event_queue, db=self.db_service)

        # ====== init session manager ======
        self.session_manager = SessionManager(
            self.db_service,
            self.kira_config,
            event_bus=self.event_bus,
        )
        self.session_media_manager = SessionMediaManager(
            self.event_bus, self.session_manager
        )

        # ====== init persona manager ======
        self.persona_manager = PersonaManager(db=self.db_service)
        await self.persona_manager.init_persona()
        await migrate_selfie_reference_image(self.persona_manager, self.kira_config)

        # ====== init sticker manager ======
        self.sticker_manager = StickerManager(db=self.db_service)
        await self.sticker_manager.init()

        # ====== init prompt manager ======
        self.prompt_manager = PromptManager(self.kira_config,
                                            self.persona_manager)

        # ====== init MCP manager ======
        try:
            self.mcp_manager = MCPManager(self.tool_manager)
            await self.mcp_manager.init_mcp()
        except Exception as e:
            logger.error(f"Failed to initialize MCPManager: {e}")

        # ====== init skills manager ======

        self.skills_manager = SkillsManager()

        # ====== init message history ======
        self.message_history = MessageHistoryService(self.db_service, self.session_manager)
        await self.message_history.initialize()
        self.event_bus.subscribe("session_deleted", self.message_history.on_session_deleted)

        # ====== init image description cache ======
        self.image_desc_cache = ImageDescCache(self.db_service)

        # ====== assemble shared IM services and workflow ======
        message_buffer = SessionBufferManager(
            max_count=int(self.kira_config.get_config("bot_config.bot.max_buffer_messages", 3)),
        )
        message_delivery = MessageDeliveryService(
            self.kira_config, self.adapter_manager, self.message_history,
        )
        message_formatter = MessageFormatter(
            self.kira_config, self.provider_manager, self.session_manager, self.image_desc_cache,
        )
        workflow = DefaultIMWorkflow(IMWorkflowContext(
            message_formatter=message_formatter,
            message_media=MessageMediaService(),
            message_buffer=message_buffer,
            message_delivery=message_delivery,
            config=self.kira_config,
            session_manager=self.session_manager,
            prompt_manager=self.prompt_manager,
            provider_mgr=self.provider_manager,
            tool_manager=self.tool_manager,
            skills_manager=self.skills_manager,
            mcp_manager=self.mcp_manager,
            db=self.db_service,
            message_history=self.message_history,
            event_bus=self.event_bus,
        ))
        self.message_processor = MessageProcessor(workflow)

        self.tasks.append(
            asyncio.create_task(
                self.image_desc_cache.cleanup_task(),
                name="image_desc_cache_cleanup"
            )
        )

        self.message_history_cleanup = MessageHistoryCleanup(
            self.message_history, self.kira_config
        )
        self.message_history_cleanup.start()
        self.event_bus.subscribe(KiraMessageEvent, workflow.handle_event)
        self.event_bus.subscribe(KiraMessageBatchEvent, workflow.handle_batch_event)
        self.event_bus.subscribe(KiraCommentEvent, self.message_processor.handle_cmt_event)

        # ====== init plugin system ======
        self.plugin_context = PluginContext(
            db=self.db_service,
            config=self.kira_config,
            event_bus=self.event_bus,
            provider_mgr=self.provider_manager,
            tool_mgr=self.tool_manager,
            adapter_mgr=self.adapter_manager,
            persona_mgr=self.persona_manager,
            sticker_mgr=self.sticker_manager,
            session_mgr=self.session_manager,
            prompt_mgr=self.prompt_manager,
            skills_mgr=self.skills_manager,
            mcp_mgr=self.mcp_manager,
            message_processor=self.message_processor,
            session_buffer_mgr=message_buffer,
            message_delivery=message_delivery,
            message_history=self.message_history,
            image_desc_cache=self.image_desc_cache,
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
            check_interval=5 * 60,
            batch_size=20,
        )

        self.tasks.append(
            asyncio.create_task(
                self.temp_monitor.start_monitoring(),
                name="temp_folder_monitor"
            )
        )

        self.schedule_tasks()

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

        # close persistent MCP connections
        if self.mcp_manager:
            try:
                await self.mcp_manager.shutdown()
            except Exception as e:
                logger.error(f"MCP manager shutdown error: {e}")

        # terminate all running adapters
        if self.adapter_manager:
            await self.adapter_manager.stop_adapters()
        if self.event_bus:
            await self.event_bus.stop()

        if self.message_history_cleanup:
            await self.message_history_cleanup.stop()

        # Stop background tasks before disposing the database they use.
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # dispose database manager
        if self.db_manager:
            await self.db_manager.dispose()
