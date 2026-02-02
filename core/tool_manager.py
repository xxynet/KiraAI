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


def _load_mcp_config() -> Dict[str, Any]:
    config_path = Path(__file__).parents[1] / "data" / "tools" / "mcp.json"
    if not config_path.exists():
        return {}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get_mcp_servers() -> Dict[str, Any]:
    config = _load_mcp_config()
    servers = config.get("mcpServers", {})
    if not isinstance(servers, dict):
        return {}
    return servers


async def _register_mcp_tools(llm_api) -> None:
    servers = _get_mcp_servers()
    if not servers:
        return

    client = Client(servers)

    async with client:
        try:
            tools_response = await client.list_tools()
        except Exception as e:
            tool_logger.error(f"Failed to list MCP tools: {e}")
        if isinstance(tools_response, dict):
            tools = tools_response.get("tools", [])
        elif isinstance(tools_response, list):
            tools = tools_response
        else:
            tools = []

    for tool in tools:
        if hasattr(tool, "model_dump"):
            tool_dict = tool.model_dump()
        else:
            tool_dict = tool

        name = tool_dict.get("name", "")
        description = tool_dict.get("description", "")
        parameters = tool_dict.get("inputSchema", {})

        if not name:
            continue

        async def _make_mcp_func(tool_name: str):
            async def _wrapped(**kwargs):
                client_inner = Client(servers)
                async with client_inner:
                    result = await client_inner.call_tool(tool_name, kwargs, timeout=10)
                    return str(result)

            return _wrapped

        func = await _make_mcp_func(name)

        tool_logger.info(f"Registered MCP tool: {name}")

        llm_api.register_tool(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )


async def register_all_tools(llm_api) -> None:
    """Discover all subclasses of BaseTool under core.tools and register them."""
    package_name = "data.tools"
    package = importlib.import_module(package_name)
    package_path = os.path.dirname(package.__file__)

    modules = _iter_tool_modules(package_path, package_name)

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
                def _wrapped(**kwargs):
                    return tool.execute(**kwargs)

                return _wrapped

            tool_logger.info(f"Registered tool: {schema['name']}")

            llm_api.register_tool(
                name=schema["name"],
                description=schema["description"],
                parameters=schema["parameters"],
                func=_make_func(tool_instance)
            )

    try:
        asyncio.create_task(_register_mcp_tools(llm_api))
    except RuntimeError:
        pass
