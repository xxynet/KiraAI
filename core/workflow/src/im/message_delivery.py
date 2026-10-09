from __future__ import annotations

import asyncio
import xml.etree.ElementTree as ET
from asyncio import Lock
from typing import List, Union, TYPE_CHECKING

from core.adapter.capabilities import IMCapability
from core.agent.message import OpenAIMessage
from core.chat.message_elements import BaseMessageElement
from core.chat.message_utils import KiraIMSentResult, MessageChain
from core.logging_manager import get_logger

if TYPE_CHECKING:
    from core.tag import TagSet, RootTagAction
    from core.adapter import AdapterManager
    from core.chat.message_history import MessageHistoryService
    from core.config.config_loader import KiraConfig

logger = get_logger("message", "cyan")


class MessageDeliveryService:
    """Own message sending, delivery history, XML handling, and session send locks."""

    def __init__(
        self,
        kira_config: KiraConfig,
        adapter_mgr: AdapterManager,
        message_history: MessageHistoryService | None = None,
    ):
        self.kira_config = kira_config
        self.adapter_mgr = adapter_mgr
        self.message_history = message_history
        self.session_locks: dict[str, asyncio.Lock] = {}

    def _read_delay(self, key: str, default: float) -> float:
        value = self.kira_config.get_config(key, default)
        try:
            return float(value)
        except (TypeError, ValueError):
            logger.warning("Invalid %s value; using default of %s", key, default)
            return default

    @property
    def min_message_delay(self) -> float:
        return self._read_delay("bot_config.bot.min_message_delay", 0.8)

    @property
    def max_message_delay(self) -> float:
        return self._read_delay("bot_config.bot.max_message_delay", 1.5)

    def get_session_lock(self, sid: str) -> Lock:
        """get session lock to avoid sending message simultaneously"""
        if sid not in self.session_locks:
            self.session_locks[sid] = asyncio.Lock()
        return self.session_locks[sid]

    async def send_message_chain(self, session: str, chain: MessageChain, *, memory_message: OpenAIMessage | None = None, self_id: str | None = None) -> KiraIMSentResult:
        """
        Send a MessageChain to target.

        :param session: adapter_name:dm|gm:session_id
        :param chain: MessageChain instance
        :return: KiraIMSentResult instance
        """
        parts = session.split(":", maxsplit=2)
        if len(parts) != 3 or any(not part for part in parts):
            raise ValueError("invalid target, must follow <adapter>:<dm|gm>:<id>")

        adapter_name, chat_type, pid = parts
        adapter = self.adapter_mgr.get_adapter(adapter_name)
        if adapter is None:
            raise ValueError(f"Adapter '{adapter_name}' is not available")
        if chat_type not in {"dm", "gm"}:
            raise ValueError("chat_type must be 'dm' or 'gm'")
        target = adapter.get_capability(IMCapability)

        history = getattr(self, "message_history", None)
        record_id = None
        if history is not None:
            try:
                config = adapter.config
                bot_id = self_id or config.get("self_id") or config.get("bot_pid") or config.get("app_id")
                llm_message_id = None
                if memory_message is not None:
                    llm_message_id = memory_message.to_memory_dict()["_extra"]["llm_message_id"]
                record_id = await history.record_outgoing(
                    session, chain, platform=adapter.info.platform,
                    self_id=str(bot_id) if bot_id is not None else None,
                    llm_message_id=llm_message_id,
                )
            except Exception as exc:
                logger.error("Unable to store outgoing message (%s)", type(exc).__name__)

        async def finish(status, platform_id=None, error_type=None):
            if record_id:
                try:
                    await history.finish_outgoing(
                        record_id, status=status, platform_message_id=platform_id, error_type=error_type)
                except Exception as exc:
                    logger.error("Unable to update delivery status (%s)", type(exc).__name__)

        try:
            if chat_type == "dm":
                result = await target.send_direct_message(pid, chain)
            else:
                result = await target.send_group_message(pid, chain)
        except BaseException as exc:
            await finish("unknown", error_type=type(exc).__name__)
            raise
        if not result:
            result = KiraIMSentResult(ok=False)
        await finish("sent" if result.ok else "failed", result.message_id)
        result.history_id = record_id
        return result

    @staticmethod
    async def parse_xml(xml_data, tag_set: TagSet) -> list[Union[MessageChain, RootTagAction]]:
        """Parse xml into an ordered list of MessageChain and RootTagAction."""
        from core.tag import RootTagAction

        root = ET.fromstring(f"<root>{xml_data}</root>")
        actions: list[Union[MessageChain, RootTagAction]] = []

        for element in root:
            if element.tag == "msg":
                message_elements = []
                for child in element:
                    tag = child.tag
                    value = child.text.strip() if child.text else ""
                    attrs = child.attrib

                    if tag in tag_set:
                        tag_inst = tag_set.get(name=tag)
                        tag_res = await tag_inst.handle(value, **attrs)

                        if isinstance(tag_res, BaseMessageElement):
                            message_elements.append(tag_res)
                        elif isinstance(tag_res, list):
                            message_elements.extend(tag_res)

                if message_elements:
                    actions.append(MessageChain(message_elements))
            elif element.tag in tag_set:
                root_tag = tag_set.get(name=element.tag)
                if root_tag and root_tag.parent is None:
                    value = element.text.strip() if element.text else ""
                    actions.append(RootTagAction(tag=root_tag, value=value, attrs=element.attrib))

        return actions

    @staticmethod
    def add_message_ids(xml_data: str, message_results: List[KiraIMSentResult]) -> str:
        """为XML响应添加消息ID"""
        try:
            root = ET.fromstring(f"<root>{xml_data}</root>")

            for i, msg in enumerate(root.findall("msg")):
                if i < len(message_results):
                    message_id = message_results[i].message_id
                    if not message_id:
                        message_id = ""
                    msg.set("message_id", message_id)

            return ET.tostring(root, encoding='unicode', method='xml')[6:-7]

        except Exception as e:
            logger.error(f"Error adding message IDs: {str(e)}")
            return xml_data
