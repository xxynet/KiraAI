import asyncio
from typing import Any

from core.adapter.access import ListAccessPolicy
from core.adapter.base import AdapterTargetId, BaseAdapter
from core.adapter.capabilities import IMCapability
from core.chat.message_utils import KiraIMSentResult, MessageChain

from .im import WebChatIMCapability


class WebChatAdapter(BaseAdapter):
    """One application-owned adapter, deliberately outside the adapter catalog."""

    NAME = "webchat"
    SID = NAME + ":dm:admin"

    def __init__(self, ctx, store) -> None:
        super().__init__(ctx)
        self.config.setdefault("allow_file_tools", True)
        self.config.setdefault("allow_exec", False)
        self.store = store
        self._stopped = asyncio.Event()
        self.register_capability(IMCapability, WebChatIMCapability(self))
        self.access.set_policy(
            capability_type=IMCapability,
            permission="im.direct.receive",
            policy=ListAccessPolicy.from_lists("allow_list", allow_list=["admin"]),
        )

    async def start(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()

    def get_client(self) -> Any:
        return self.store

    async def send_direct_message(
        self,
        user_id: AdapterTargetId,
        send_message_obj: MessageChain,
    ) -> KiraIMSentResult | None:
        """Deprecated compatibility wrapper; use the IM capability directly.

        await adapter.get_capability(IMCapability).send_direct_message(user_id, message)
        """
        return await self.get_capability(IMCapability).send_direct_message(
            user_id, send_message_obj
        )

    async def send_group_message(
        self,
        group_id: AdapterTargetId,
        send_message_obj: MessageChain,
    ) -> KiraIMSentResult | None:
        """Deprecated compatibility wrapper; use the IM capability directly.

        await adapter.get_capability(IMCapability).send_group_message(group_id, message)
        """
        return await self.get_capability(IMCapability).send_group_message(
            group_id, send_message_obj
        )
