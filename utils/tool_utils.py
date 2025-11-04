from abc import abstractmethod, ABC
from typing import Callable, Dict, Any


class BaseTool(ABC):
    def __init__(self):
        pass

    name = None
    description = None
    parameters = None

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """工具的具体执行逻辑，子类必须实现"""
        pass

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """获取工具的function calling schema"""
        return {
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.parameters
        }