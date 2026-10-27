from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.plugin import PluginContext


class BaseTool(ABC):
    def __init__(self, *args, ctx: PluginContext | None = None, **kwargs):
        self.ctx = ctx
        self.args = args
        self.kwargs = kwargs

    name = None
    description = None
    parameters = None

    @abstractmethod
    async def execute(self, *args, **kwargs) -> str:
        """工具的具体执行逻辑，子类必须实现"""
        ...

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """获取工具的function calling schema"""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.parameters
        }
