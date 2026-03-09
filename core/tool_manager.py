import importlib
import inspect
import json
import asyncio
import os
from pathlib import Path
from typing import Type, List, Any, Dict

from fastmcp import Client

from core.utils.tool_utils import BaseTool
from core.logging_manager import get_logger

tool_logger = get_logger("tool_manager", "orange")


def _iter_tool_modules(package_path: str, package_name: str) -> List[str]:
    module_names = []
    for entry in os.listdir(package_path):
        if entry.startswith("_"):
            continue
        full_path = os.path.join(package_path, entry)
        if os.path.isdir(full_path) and os.path.isfile(os.path.join(full_path, "__init__.py")):
            # Recurse into subpackages
            subpackage = f"{package_name}.{entry}"
            module_names.append(subpackage)
            module_names.extend(_iter_tool_modules(full_path, subpackage))
        elif entry.endswith(".py") and entry != "__init__.py" and entry != "registry.py":
            module_names.append(f"{package_name}.{entry[:-3]}")
    return module_names


def _discover_tool_classes(module) -> List[Type[BaseTool]]:
    tool_classes: List[Type[BaseTool]] = []
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, BaseTool) and obj is not BaseTool:
            tool_classes.append(obj)
    return tool_classes


async def register_all_tools(llm_api) -> None:
    """Discover all subclasses of BaseTool under core.tools and register them."""
    package_name = "data.tools"
    try:
        package = importlib.import_module(package_name)
        package_path = os.path.dirname(package.__file__)

        modules = _iter_tool_modules(package_path, package_name)
    except Exception as e:
        tool_logger.error(f"Failed to register tools: {e}")
        return

    for module_name in modules:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        for ToolClass in _discover_tool_classes(module):
            try:
                tool_instance = ToolClass()
            except Exception:
                continue

            schema = tool_instance.get_schema()

            def _make_func(tool):
                async def _wrapped(*args, **kwargs):
                    return await tool.execute(*args, **kwargs)

                return _wrapped

            tool_logger.info(f"Registered tool: {schema['name']}")

            llm_api.register_tool(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
                func=_make_func(tool_instance)
            )
