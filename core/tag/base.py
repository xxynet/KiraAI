from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from core.chat.message_elements import BaseMessageElement
from core.plugin import PluginContext


class BaseTag(ABC):
    def __init__(self, ctx: Optional[PluginContext] = None, **kwargs):
        self.ctx = ctx
        self.kwargs = kwargs

    name: str = None
    description: str = None
    parent: str = "msg"

    @abstractmethod
    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        ...


@dataclass
class RootTagAction:
    """A root-level tag action to be executed between messages during send phase."""
    tag: BaseTag
    value: str
    attrs: dict
