from __future__ import annotations

from dataclasses import dataclass
import inspect
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Literal

from ..provider import ProviderManager, LLMModelClient, EmbeddingModelClient
from core.chat.session_manager import SessionManager
from ..adapter import AdapterManager
from core.event_bus import EventBus
from core.agent.func_tool_manager import FuncToolManager
from core.chat import KiraMessageEvent, KiraIMMessage, MessageChain, User, Group, KiraIMSentResult
from core.config import KiraConfig
from core.persona import PersonaManager
from core.sticker_manager import StickerManager
from core.utils.path_utils import get_data_path
from core.chat.message_elements import Text

if TYPE_CHECKING:
    from .plugin_registry import PluginManager
    from core.message_manager import MessageProcessor
    from core.db.service import DatabaseService


@dataclass
class PluginContext:
    db: DatabaseService

    config: KiraConfig

    event_bus: EventBus

    provider_mgr: ProviderManager

    tool_mgr: FuncToolManager

    adapter_mgr: AdapterManager

    persona_mgr: PersonaManager

    sticker_manager: StickerManager

    session_mgr: SessionManager

    message_processor: MessageProcessor

    plugin_mgr: Optional[PluginManager] = None

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
        buffer = self.message_processor.session_buffer.get_buffer(sid)
        return buffer
    
    async def flush_session_messages(self, sid: str):
        await self.message_processor.flush_session_messages(sid)

    def get_default_llm_client(self) -> LLMModelClient:
        client = self.get_llm_client(llm_type="default")
        return client

    def get_default_fast_llm_client(self) -> LLMModelClient:
        client = self.get_llm_client(llm_type="fast")
        return client

    def get_llm_client(self, model_uuid: Optional[str] = None, llm_type: Optional[str] = None) -> Optional[LLMModelClient]:
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
            client = self.provider_mgr.get_model_client(provider_id, model_id)
        except:
            return
        if isinstance(client, LLMModelClient):
            return client
        return

    def get_default_embedding_client(self) -> Optional[EmbeddingModelClient]:
        client = self.provider_mgr.get_default_embedding()
        if isinstance(client, EmbeddingModelClient):
            return client

    def get_embedding_client(self, model_uuid: str, default: bool = False) -> Optional[EmbeddingModelClient]:
        if default:
            client = self.provider_mgr.get_default_embedding()
            if isinstance(client, EmbeddingModelClient):
                return client
            return
        try:
            parts = model_uuid.split(":")
            provider_id = parts[0]
            model_id = ":".join(parts[1:])
            client = self.provider_mgr.get_model_client(provider_id, model_id)
        except:
            return
        if isinstance(client, EmbeddingModelClient):
            return client
        return

    async def emit_custom_event(self, event_name: str, payload: dict = None):
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
        group = None
        if st == "gm":
            group = Group(group_id=sid)
        message_obj = KiraMessageEvent(
            adapter=ada.info,
            message_types=ada.message_types,
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
    
    async def send_message_chain(self, session: str, chain: MessageChain) -> KiraIMSentResult:
        """
        Send a message chain to the specified session.
        :param session: session string in the format of "adapter_name:session_type:session_id"
        :param chain: MessageChain object
        :return: KiraIMSentResult object
        """
        return await self.message_processor.send_message_chain(session, chain)

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
