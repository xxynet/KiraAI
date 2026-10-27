from __future__ import annotations

import inspect
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.agent.func_tool_manager import FuncToolManager
from core.chat import (
    Group,
    KiraIMMessage,
    KiraIMSentResult,
    KiraMessageEvent,
    MessageChain,
    User,
)
from core.chat.session_manager import SessionManager
from core.config import KiraConfig
from core.event_bus import EventBus
from core.persona import PersonaManager
from core.sticker_manager import StickerManager
from core.utils.path_utils import get_data_path
from core.workflow.src.im.batching import publish_buffered_messages

from ..adapter import AdapterManager, BaseAdapter, BaseCapability, IMCapability
from ..provider import EmbeddingModelClient, LLMModelClient, ModelType, ProviderManager

if TYPE_CHECKING:
    from core.agent.mcp_mgr import MCPManager
    from core.agent.skills_mgr import SkillsManager
    from core.chat.message_history import MessageHistoryService
    from core.chat.session_buffer import SessionBufferManager
    from core.db.service import DatabaseService
    from core.image_desc_cache import ImageDescCache
    from core.message_manager import MessageProcessor
    from core.prompt_manager import PromptManager
    from core.workflow.src.im.message_delivery import MessageDeliveryService

    from .manager import PluginManager


@dataclass
class PluginContext:
    db: DatabaseService

    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    tool_mgr: FuncToolManager

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    sticker_mgr: StickerManager

    session_mgr: SessionManager

    prompt_mgr: PromptManager

    skills_mgr: SkillsManager

    mcp_mgr: MCPManager | None

    message_processor: MessageProcessor

    # Query structured incoming/outgoing messages and their memory links.
    message_history: MessageHistoryService

    image_desc_cache: ImageDescCache

    session_buffer_mgr: SessionBufferManager

    message_delivery: MessageDeliveryService

    plugin_mgr: PluginManager | None = None

    @property
    def sticker_manager(self) -> StickerManager:
        """Compatibility alias for plugins using the original attribute name."""
        return self.sticker_mgr

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

    def get_plugin_inst(self, plugin_id: str):
        inst = self.plugin_mgr.get_plugin_inst(plugin_id)
        return inst

    def get_buffer(self, sid: str):
        buffer = self.session_buffer_mgr.get_buffer(sid)
        return buffer

    async def get_session_capabilities(self, sid: str) -> dict:
        global_capabilities = self.config.get_config("bot_config.capabilities", {})
        return await self.session_mgr.get_effective_capabilities(sid, global_capabilities)

    
    async def flush_session_messages(
        self,
        sid: str,
        filter_fn: Callable[[KiraMessageEvent], bool] | None = None,
    ) -> bool:
        """Publish matching buffered events, leaving unmatched events buffered.

        Return True when a batch is published, or False when no events match.
        Publication does not imply processing has completed. Errors propagate.
        """
        return await publish_buffered_messages(
            self.session_buffer_mgr, self.event_bus, sid, filter_fn=filter_fn,
        )

    def get_default_llm_client(self) -> LLMModelClient:
        client = self.get_llm_client(llm_type="default")
        return client

    def get_default_fast_llm_client(self) -> LLMModelClient:
        client = self.get_llm_client(llm_type="fast")
        return client

    def get_llm_client(self, model_uuid: str | None = None, llm_type: str | None = None) -> LLMModelClient | None:
        """
        Get LLMModelClient object by model uuid
        :param model_uuid: provider_id:model_id
        :param llm_type: default or fast or None
        :return: LLMModelClient
        """
        if llm_type and llm_type == "default":
            client = self.provider_mgr.get_default_llm()
            if isinstance(client, LLMModelClient):
                return client

        if llm_type and llm_type == "fast":
            client = self.provider_mgr.get_default_fast_llm()
            if isinstance(client, LLMModelClient):
                return client
        try:
            parts = model_uuid.split(":")
            provider_id = parts[0]
            model_id = ":".join(parts[1:])
            client = self.provider_mgr.get_model_client(provider_id, model_id, ModelType.LLM)
        except:
            return
        if isinstance(client, LLMModelClient):
            return client
        return

    async def register_provider(self, relative_path: str) -> str:
        """Register a Provider directory for the calling plugin."""
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            module_name = frame.f_globals.get("__name__", "")
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        return await self.plugin_mgr.register_plugin_provider(plugin_id, relative_path)

    async def unregister_provider(self, provider_format: str) -> bool:
        """Unregister a Provider type owned by the calling plugin."""
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            module_name = frame.f_globals.get("__name__", "")
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        return await self.plugin_mgr.unregister_plugin_provider(plugin_id, provider_format)

    async def register_adapter(self, relative_path: str) -> str:
        """Register an Adapter directory for the calling plugin."""
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            module_name = frame.f_globals.get("__name__", "")
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        return await self.plugin_mgr.register_plugin_adapter(plugin_id, relative_path)

    async def unregister_adapter(self, platform: str) -> bool:
        """Unregister an Adapter type owned by the calling plugin."""
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            module_name = frame.f_globals.get("__name__", "")
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        return await self.plugin_mgr.unregister_plugin_adapter(plugin_id, platform)

    async def register_adapter_capability(
        self, *, platform: str, capability_type: type[BaseCapability],
        factory: Callable[[BaseAdapter], BaseCapability],
    ) -> None:
        """Attach a plugin-owned capability to existing and future platform accounts.

        The synchronous factory receives one adapter and returns a fresh capability.
        Optional async initialize/terminate hooks may own resources and requests.
        Registration is atomic across current instances; duplicates never replace
        native capabilities. Hooks must not mutate capability registrations.
        """
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(
                frame.f_globals.get("__name__", ""),
            )
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        await self.plugin_mgr.register_plugin_adapter_capability(
            plugin_id, platform, capability_type, factory,
        )

    async def unregister_adapter_capability(
        self, *, platform: str, capability_type: type[BaseCapability],
    ) -> bool:
        """Withdraw only the calling plugin's binding and close its instances."""
        frame = inspect.currentframe().f_back
        plugin_id = None
        if frame and self.plugin_mgr:
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(
                frame.f_globals.get("__name__", ""),
            )
        if not plugin_id:
            raise RuntimeError("Plugin context is not associated with a loaded plugin")
        return await self.plugin_mgr.unregister_plugin_adapter_capability(
            plugin_id, platform, capability_type,
        )

    def get_default_embedding_client(self) -> EmbeddingModelClient | None:
        client = self.provider_mgr.get_default_embedding()
        if isinstance(client, EmbeddingModelClient):
            return client

    def get_embedding_client(self, model_uuid: str, default: bool = False) -> EmbeddingModelClient | None:
        if default:
            client = self.provider_mgr.get_default_embedding()
            if isinstance(client, EmbeddingModelClient):
                return client
            return
        try:
            parts = model_uuid.split(":")
            provider_id = parts[0]
            model_id = ":".join(parts[1:])
            client = self.provider_mgr.get_model_client(provider_id, model_id, ModelType.EMBEDDING)
        except:
            return
        if isinstance(client, EmbeddingModelClient):
            return client
        return

    async def emit_custom_event(self, event_name: str, payload: dict | None = None):
        from core.chat.message_utils import KiraCustomEvent

        plugin_id = None
        frame = inspect.currentframe().f_back
        if frame and self.plugin_mgr:
            module_name = frame.f_globals.get("__name__", "")
            plugin_id = self.plugin_mgr.get_plugin_id_for_module(module_name)

        event = KiraCustomEvent(
            event_name=event_name,
            source_plugin=plugin_id or "unknown",
            payload=payload or {},
            timestamp=int(time.time()),
        )

        await self.event_bus.publish(event)
        return event

    async def publish_notice(self, session: str, chain: MessageChain, is_mentioned: bool = True):
        """
        Publish a notice message to the event bus.
        :param session: session string in the format of "adapter_name:session_type:session_id"
        :param chain: MessageChain object
        :param is_mentioned: whether the AI is mentioned
        """
        import time
        cur_time = int(time.time())
        parts = session.split(":", maxsplit=2)
        if len(parts) != 3 or any(not part for part in parts):
            raise ValueError("Failed to parse session string")
        ada_name, st, sid = parts
        ada = self.adapter_mgr.get_adapter(ada_name)
        if not ada:
            raise ValueError(f"Failed to get adapter: {ada_name}")
        try:
            im = ada.get_capability(IMCapability)
        except ValueError:
            supported_elements = []
        else:
            supported_elements = list((await im.get_message_metadata()).supported_elements)
        group = None
        if st == "gm":
            group = Group(group_id=sid)
        message_obj = KiraMessageEvent(
            adapter=ada.info,
            supported_elements=supported_elements,
            message=KiraIMMessage(
                timestamp=cur_time,
                sender=User(
                    user_id=sid if st == "dm" else "unknown",
                    nickname="system"
                ),
                group=group,
                message_id="system_message",
                self_id=ada.config.get("self_id"),
                is_notice=True,
                is_mentioned=is_mentioned,
                chain=chain,
            ),
            timestamp=cur_time,
        )
        await self.event_bus.publish(message_obj)
    
    async def send_message_chain(self, session: str, chain: MessageChain, *, bot: User | None = None) -> KiraIMSentResult:
        """
        Send a message chain to the specified session.
        :param session: session string in the format of "adapter_name:session_type:session_id"
        :param chain: MessageChain object
        :param bot: Bot identity to include in outgoing history.
        :return: KiraIMSentResult object
        """
        return await self.message_delivery.send_message_chain(session, chain, bot=bot)

    def get_lang(self) -> str:
        """Get the configured backend language code (e.g. 'zh', 'en').

        Returns 'en' as default if not set.
        """
        return self.config.get_config("locale.lang", "en")

    def get_timezone(self):
        """Get the configured timezone object for the application.

        Returns a ZoneInfo object if locale.TZ is configured and valid,
        or None otherwise — callers should fall back to datetime.now().
        """
        return self.config.get_timezone()
