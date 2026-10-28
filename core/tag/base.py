from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.chat.message_elements import BaseMessageElement

# Importing core.plugin at runtime would cycle: core.plugin -> manager -> core.tag -> core.plugin.
if TYPE_CHECKING:
    from core.plugin import PluginContext


class BaseTag(ABC):
    def __init__(self, ctx: PluginContext | None = None, **kwargs):
        self.ctx = ctx
        self.kwargs = kwargs

    name: str = None
    description: str = None
    parent: str | None = "msg"

    @abstractmethod
    async def handle(self, value: str, **kwargs) -> list[BaseMessageElement]:
        ...


@dataclass
class RootTagAction:
    """A root-level tag action to be executed between messages during send phase."""
    tag: BaseTag
    value: str
    attrs: dict
