import asyncio

from core.adapter.base import BaseAdapter
from core.adapter.capabilities import IMCapability
from .im import WebChatIMCapability


class WebChatAdapter(BaseAdapter):
    """One application-owned adapter, deliberately outside the adapter catalog."""
    NAME = "webchat"
    SID = NAME + ":dm:admin"

    def __init__(self, ctx, store):
        super().__init__(ctx)
        self.store = store
        self._stopped = asyncio.Event()
        self.register_capability(IMCapability, WebChatIMCapability(self))

    async def start(self):
        await self._stopped.wait()

    async def stop(self):
        self._stopped.set()

    def get_client(self):
        return self.store
