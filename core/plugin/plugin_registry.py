import importlib
import importlib.util
import inspect
import os
import json
import sys
import types
import httpx
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Union
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
from core.utils.path_utils import get_data_path, get_config_path
from core.logging_manager import get_logger
from core.config.config_field import BaseConfigField, SectionField, build_fields
from core.config import VERSION
from .plugin import BasePlugin
from .plugin_context import PluginContext
from .plugin_handlers import Priority, event_handler_reg, EventHandler, EventType

from core.tag import tag_registry, BaseTag


@dataclass
class PluginInfo:
    plugin_id: str
    display_name: str
    version: str = ""
    author: str = ""
    description: str = ""
    repo: Optional[str] = None
    locales: Dict[str, Dict[str, str]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    core_version: Optional[str] = None
    builtin: bool = False
    uninstallable: bool = False
    hidden: bool = False
    error: Optional[str] = None


logger = get_logger("plugin_manager", "cyan")

PLUGINS_DIR = get_data_path() / "plugins"
PLUGIN_DATA_DIR = get_data_path() / "plugin_data"
PLUGIN_CONFIG_DIR = get_config_path() / "plugins"
PLUGIN_STATE_FILE = get_config_path() / "plugins.json"
BUILTIN_PLUGINS_DIR = Path(__file__).parent / "builtin_plugins"

_plugin_classes: Dict[str, type[BasePlugin]] = {}
_plugin_manifests: Dict[str, Dict[str, Any]] = {}
_plugin_module_dirs: Dict[str, str] = {}
_plugin_module_paths: Dict[str, Path] = {}

"""key: module name, value: plugin id"""
_module_to_plugin: Dict[str, str] = {}
_plugin_schemas: Dict[str, List[BaseConfigField]] = {}


@dataclass
class PluginComponents:
    """Typed container for all components registered by a single plugin."""
    tools: Dict[str, dict] = field(default_factory=dict)
    tool_funcs: Dict[str, Callable] = field(default_factory=dict)
    tags: List[dict] = field(default_factory=list)
    tag_funcs: Dict[str, Callable] = field(default_factory=dict)
    hooks: List[EventHandler] = field(default_factory=list)
    pages: List[dict] = field(default_factory=list)
    page_funcs: Dict[str, Callable] = field(default_factory=dict)
    api_routes: List[dict] = field(default_factory=list)
    api_route_funcs: Dict[str, Callable] = field(default_factory=dict)
    static_dirs: List[dict] = field(default_factory=list)

    def has_any(self) -> bool:
        return bool(self.tools or self.tags or self.hooks or self.pages
                    or self.api_routes or self.static_dirs)


_plugin_components: Dict[str, PluginComponents] = {}

"""Plugins that failed to load: {plugin_id: {"manifest": {...}, "error": "..."}}"""
_plugin_load_errors: Dict[str, Dict[str, Any]] = {}

"""plugin_ids whose API routes have already been added to FastAPI."""
_plugin_api_registered: set[str] = set()

"""Discovered plugin metadata: {plugin_id: PluginInfo}"""
_plugin_infos: Dict[str, PluginInfo] = {}


def get_obj_plugin_id(obj: Any):
    module = inspect.getmodule(obj)
    module_name = module.__name__ if module else ""
    plugin_id = _module_to_plugin.get(module_name, "")

    if not plugin_id and module and getattr(module, "__file__", None):
        module_path = Path(module.__file__).resolve()
        plugin_root = module_path.parent
        manifest_path = plugin_root / "manifest.json"
        if manifest_path.exists():
            try:
                with manifest_path.open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
                plugin_id = manifest.get("plugin_id") or plugin_root.name
                _plugin_manifests.setdefault(plugin_id, manifest)
                _plugin_module_dirs.setdefault(plugin_id, plugin_root.name)
                _plugin_module_paths.setdefault(plugin_id, plugin_root)
                _module_to_plugin[module_name] = plugin_id
            except Exception:
                plugin_id = plugin_root.name
    return plugin_id


class RegisterDeco:

    @staticmethod
    def tool(name: str, description: str, params: dict):
        def decorator(func: Callable):
            plugin_id = get_obj_plugin_id(func)
            comp = _plugin_components.setdefault(plugin_id, PluginComponents())
            comp.tools[name] = {
                "name": name,
                "description": description,
                "parameters": params,
                "func": func,
            }
            comp.tool_funcs[name] = func

            return func

        return decorator

    @staticmethod
    def tag(name: str, description: str):
        def decorator(func: Callable):
            plugin_id = get_obj_plugin_id(func)
            comp = _plugin_components.setdefault(plugin_id, PluginComponents())
            comp.tags.append({
                "name": name,
                "description": description
            })
            comp.tag_funcs[name] = func
            return func
        return decorator

    @staticmethod
    def page(route: str, auth: bool = True, menu: Optional[dict] = None):
        """Register a plugin page endpoint.

        route: URL path relative to plugin prefix, e.g., "/dashboard"
               Final route: /page/plugin/{plugin_id}{route}
        auth:  Require JWT auth (default True)
        menu:  Optional menu configuration for sidebar integration
        """
        def decorator(func: Callable):
            plugin_id = get_obj_plugin_id(func)
            comp = _plugin_components.setdefault(plugin_id, PluginComponents())
            comp.pages.append({
                "route": route,
                "func": func,
                "auth": auth,
                "menu": menu,
            })
            comp.page_funcs[func.__name__] = func
            return func
        return decorator

    @staticmethod
    def static(path: str, directory: str, html: bool = False):
        """Register a static file directory.

        path:      URL path prefix relative to plugin, e.g., "/static"
                   Final URL: /page/plugin/{plugin_id}{path}
        directory: Local directory path relative to plugin root
        html:      Try to serve index.html for directory requests
        """
        def decorator(func: Callable):
            plugin_id = get_obj_plugin_id(func)
            comp = _plugin_components.setdefault(plugin_id, PluginComponents())
            comp.static_dirs.append({
                "path": path,
                "directory": directory,
                "html": html,
            })
            return func
        return decorator

    @staticmethod
    def api(method: str, path: str, auth: bool = True, **kwargs):
        """Register a plugin API endpoint.

        method: HTTP method, e.g. "GET", "POST"
        path:   Path relative to the plugin prefix, e.g. "/status"
                Final route: /api/plugin/{plugin_id}{path}
        auth:   Require JWT auth (default True)
        kwargs: Forwarded to FastAPI add_api_route (response_model, summary, …)
        """
        def decorator(func: Callable):
            plugin_id = get_obj_plugin_id(func)
            comp = _plugin_components.setdefault(plugin_id, PluginComponents())
            comp.api_routes.append({
                "method": method.upper(),
                "path":   path,
                "func":   func,
                "auth":   auth,
                "kwargs": kwargs,
            })
            comp.api_route_funcs[func.__name__] = func
            return func
        return decorator


class OnEventDeco:

    @staticmethod
    def _register_hook(func: Callable, priority: Union[Priority, int], event_type: EventType):
        plugin_id = get_obj_plugin_id(func)
        eh = EventHandler(
            event_type=event_type,
            priority=priority,
            handler=func,
            desc=func.__doc__
        )

        comp = _plugin_components.setdefault(plugin_id, PluginComponents())
        comp.hooks.append(eh)

    def im_message(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_IM_MESSAGE)
            return func
        return decorator

    def message_buffered(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_MESSAGE_BUFFERED)
            return func
        return decorator

    def im_batch_message(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_IM_BATCH_MESSAGE)
            return func
        return decorator

    def llm_request(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_LLM_REQUEST)
            return func
        return decorator

    def llm_response(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_LLM_RESPONSE)
            return func
        return decorator

    def tool_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_TOOL_RESULT)
            return func
        return decorator

    def after_xml_parse(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.AFTER_XML_PARSE)
            return func
        return decorator

    def step_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_STEP_RESULT)
            return func
        return decorator

    def final_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_FINAL_RESULT)
            return func
        return decorator

    def exception(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_EXCEPTION)
            return func
        return decorator


register = RegisterDeco()
on = OnEventDeco()

register_tool = register.tool


def _build_tag_inst(tag_name: str, tag_description: str, func: Callable):
    class TagInst(BaseTag):
        name = tag_name
        description = tag_description

        async def handle(self, value: str, **kwargs):
            res = await func(value, **kwargs)
            return res

    return TagInst()


class PluginManager:
    """
    Plugin manager for KiraAI, detecting plugins automatically
    """

    def __init__(self, ctx: Optional[PluginContext] = None):
        self.plugins: List[BasePlugin] = []
        self.plugin_dir = Path(PLUGINS_DIR)
        self.plugin_data_dir = Path(PLUGIN_DATA_DIR)
        self.ctx = ctx
        self.plugin_instances: Dict[str, BasePlugin] = {}
        self.plugin_configs: Dict[str, Dict[str, Any]] = {}
        self.plugin_enabled: Dict[str, bool] = {}
        self._web_app = None

        self._load_plugin_state()

    def set_web_app(self, app) -> None:
        """Provide the FastAPI app instance so plugin API routes can be registered.
        Also registers routes for any plugins that were already initialized before this call.
        """
        self._web_app = app
        for plugin_id in list(self.plugin_instances.keys()):
            self._register_plugin_apis_for(plugin_id)
            self._register_plugin_pages_for(plugin_id)
            self._register_plugin_static_for(plugin_id)

    def get_plugin_inst(self, plugin_id: str):
        return self.plugin_instances.get(plugin_id)

    def _load_plugin_state(self) -> None:
        try:
            config_dir = PLUGIN_STATE_FILE.parent
            config_dir.mkdir(parents=True, exist_ok=True)
            if PLUGIN_STATE_FILE.exists():
                with PLUGIN_STATE_FILE.open("r", encoding="utf-8") as f:
                    data = f.read()
                if data.strip():
                    raw = json.loads(data)
                    if isinstance(raw, dict):
                        self.plugin_enabled = {
                            str(k): bool(v) for k, v in raw.items()
                        }
        except Exception as e:
            logger.error(f"Failed to load plugin state from {PLUGIN_STATE_FILE}: {e}")
            self.plugin_enabled = {}

    def _save_plugin_state(self) -> None:
        try:
            config_dir = PLUGIN_STATE_FILE.parent
            config_dir.mkdir(parents=True, exist_ok=True)
            with PLUGIN_STATE_FILE.open("w", encoding="utf-8") as f:
                json.dump(self.plugin_enabled, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save plugin state to {PLUGIN_STATE_FILE}: {e}")

    def is_plugin_enabled(self, plugin_id: str) -> bool:
        if not plugin_id:
            return False
        return self.plugin_enabled.get(plugin_id, True)

    async def set_plugin_enabled(self, plugin_id: str, enabled: bool) -> None:
        if not plugin_id:
            return
        plugin_id = str(plugin_id)
        previous = self.plugin_enabled.get(plugin_id, True)
        self.plugin_enabled[plugin_id] = bool(enabled)
        self._save_plugin_state()

        if enabled and not previous:
            # Toggle: plugin code unchanged, just re-initialize from existing class
            await self.init_plugin(plugin_id)
        elif not enabled and previous:
            try:
                await self.terminate(plugin_id)
            except Exception as e:
                logger.error(f"Failed to terminate plugin {plugin_id} when disabling: {e}")

    def get_registered_plugins(self) -> Dict[str, type[BasePlugin]]:
        return dict(_plugin_classes)

    def has_plugin(self, plugin_id: str) -> bool:
        return plugin_id in _plugin_infos

    def list_plugins(self) -> List[PluginInfo]:
        return list(_plugin_infos.values())

    def get_plugin_manifest(self, name: str) -> Dict[str, Any]:
        return _plugin_manifests.get(name, {})

    def get_plugin_load_errors(self) -> Dict[str, Dict[str, Any]]:
        return dict(_plugin_load_errors)

    def get_plugin_module_dir(self, name: str) -> str:
        return _plugin_module_dirs.get(name, "")

    def get_plugin_module_path(self, name: str) -> Optional[Path]:
        return _plugin_module_paths.get(name)

    def is_builtin_plugin(self, plugin_id: str) -> bool:
        path = _plugin_module_paths.get(plugin_id)
        if path is None:
            return False
        return path.is_relative_to(BUILTIN_PLUGINS_DIR)

    def is_plugin_hidden(self, plugin_id: str) -> bool:
        if not self.is_builtin_plugin(plugin_id):
            return False
        manifest = _plugin_manifests.get(plugin_id, {})
        return bool(manifest.get("hide", False))

    def is_plugin_uninstallable(self, plugin_id: str) -> bool:
        if not self.is_builtin_plugin(plugin_id):
            return True
        manifest = _plugin_manifests.get(plugin_id, {})
        return bool(manifest.get("uninstallable", False))

    def get_plugin_id_for_module(self, module_name: str) -> Optional[str]:
        return _module_to_plugin.get(module_name)

    def get_plugin_schema(self, name: str) -> List[BaseConfigField]:
        return _plugin_schemas.get(name, [])

    def get_plugin_config(self, plugin_name: str) -> Dict[str, Any]:
        plugin_name = str(plugin_name)
        if plugin_name in self.plugin_configs:
            return dict(self.plugin_configs.get(plugin_name, {}))
        schema_fields = _plugin_schemas.get(plugin_name, [])
        if schema_fields:
            self._ensure_plugin_config(plugin_name, schema_fields)
            return dict(self.plugin_configs.get(plugin_name, {}))
        cfg = self._load_plugin_config_from_file(plugin_name)
        self.plugin_configs[plugin_name] = cfg
        return dict(cfg)

    async def update_plugin_config(self, plugin_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        plugin_name = str(plugin_name)
        if not isinstance(config, dict):
            config = {}
        schema_fields = _plugin_schemas.get(plugin_name, [])
        if schema_fields:
            self._ensure_plugin_config(plugin_name, schema_fields)
        current_cfg = self.plugin_configs.get(plugin_name)
        if current_cfg is None:
            current_cfg = self._load_plugin_config_from_file(plugin_name)
            self.plugin_configs[plugin_name] = current_cfg
        for key, value in config.items():
            current_cfg[key] = value
        PLUGIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_path = PLUGIN_CONFIG_DIR / f"{plugin_name}.json"
        try:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(current_cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save plugin config for {plugin_name}: {e}")
        self.plugin_configs[plugin_name] = current_cfg
        if plugin_name in self.plugin_instances:
            await self.init_plugin(plugin_name)
        return dict(current_cfg)

    def get_plugin_components(self) -> Dict[str, PluginComponents]:
        return dict(_plugin_components)

    def get_plugin_tools(self, plugin_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        if plugin_name is None:
            return {pid: dict(comp.tools) for pid, comp in _plugin_components.items()}
        comp = _plugin_components.get(plugin_name)
        return dict(comp.tools) if comp else {}

    def _register_plugin_tools_for(self, plugin_id: str) -> None:
        comp = _plugin_components.get(plugin_id)
        if not comp:
            return
        plugin_instance = self.plugin_instances.get(plugin_id)
        tool_names: list[str] = []
        for tool_name, meta in comp.tools.items():
            func = comp.tool_funcs.get(tool_name)
            if not func:
                continue
            bound_func = func
            if plugin_instance is not None and hasattr(plugin_instance, func.__name__):
                bound_func = getattr(plugin_instance, func.__name__)
            self.ctx.llm_api.register_tool(
                name=tool_name,
                description=meta.get("description", ""),
                parameters=meta.get("parameters") or {},
                func=bound_func,
            )
            tool_names.append(tool_name)
        if tool_names:
            logger.info(f"Registered {len(tool_names)} tools from {plugin_id}: {tool_names}")

    def _register_plugin_hooks_for(self, plugin_id: str):
        comp = _plugin_components.get(plugin_id)
        if not comp:
            return
        plugin_instance = self.plugin_instances.get(plugin_id)
        for hook in comp.hooks:
            bound_handler = hook.handler
            if plugin_instance is not None and bound_handler is not None and hasattr(
                plugin_instance, bound_handler.__name__
            ):
                candidate = getattr(plugin_instance, bound_handler.__name__)
                if candidate is not None:
                    bound_handler = candidate
            hook.handler = bound_handler
            event_handler_reg.register(hook)
        if comp.hooks:
            logger.info(f"Registered {len(comp.hooks)} hooks from {plugin_id}")

    def _register_plugin_tags_for(self, plugin_id: str):
        comp = _plugin_components.get(plugin_id)
        if not comp:
            return
        plugin_instance = self.plugin_instances.get(plugin_id)
        tag_names: list[str] = []
        for tag_meta in comp.tags:
            tag_name = tag_meta["name"]
            func = comp.tag_funcs.get(tag_name)
            if not func:
                continue
            bound_func = func
            if plugin_instance is not None and hasattr(plugin_instance, func.__name__):
                bound_func = getattr(plugin_instance, func.__name__)
            tag_registry.register(_build_tag_inst(
                tag_name,
                tag_meta["description"],
                bound_func
            ))
            tag_names.append(tag_name)
        if tag_names:
            logger.info(f"Registered {len(tag_names)} tags from {plugin_id}: {tag_names}")

    def _register_plugin_apis_for(self, plugin_id: str) -> None:
        if self._web_app is None:
            return
        comp = _plugin_components.get(plugin_id)
        if not comp or not comp.api_routes:
            return
            return

        # Routes already in FastAPI: the dynamic_endpoint always looks up the
        # current instance at call time, so re-init requires no action here.
        if plugin_id in _plugin_api_registered:
            return

        import typing
        from fastapi import Depends, HTTPException
        from webui.routes.auth import require_auth

        _plugin_api_registered.add(plugin_id)
        mgr = self

        def _make_plugin_check(pid: str):
            async def check():
                if not mgr.is_plugin_enabled(pid):
                    raise HTTPException(status_code=404, detail="Plugin disabled")
            return check

        registered: List[str] = []

        for route in comp.api_routes:
            func = route["func"]
            func_name = func.__name__
            full_path = f"/api/plugin/{plugin_id}/{route['path'].lstrip('/')}"

            # Resolve annotations eagerly using the plugin module's own globals,
            # so `from __future__ import annotations` in plugins is handled correctly.
            try:
                resolved_hints = typing.get_type_hints(func, globalns=func.__globals__)
            except Exception:
                resolved_hints = {}

            params = [
                p.replace(annotation=resolved_hints.get(name, p.annotation))
                for name, p in inspect.signature(func).parameters.items()
                if name != "self"
            ]

            # Capture loop variables via default args to avoid closure issues.
            async def dynamic_endpoint(
                _pid=plugin_id, _fname=func_name, _mgr=mgr, **kwargs
            ):
                inst = _mgr.plugin_instances.get(_pid)
                if inst is None:
                    raise HTTPException(status_code=503, detail="Plugin not available")
                return await getattr(inst, _fname)(**kwargs)

            dynamic_endpoint.__signature__ = inspect.Signature(params)

            dependencies = [Depends(_make_plugin_check(plugin_id))]
            if route["auth"]:
                dependencies.append(Depends(require_auth))

            self._web_app.add_api_route(
                path=full_path,
                endpoint=dynamic_endpoint,
                methods=[route["method"]],
                dependencies=dependencies,
                tags=[f"plugin:{plugin_id}"],
                **route["kwargs"],
            )
            registered.append(full_path)

        if registered:
            logger.info(f"Registered {len(registered)} API routes from {plugin_id}: {registered}")

    def _register_plugin_pages_for(self, plugin_id: str) -> None:
        """Register plugin page routes for URL access."""
        if self._web_app is None:
            return

        comp = _plugin_components.get(plugin_id)
        if not comp or not comp.pages:
            return
            return

        # Track registered pages to avoid duplicates
        if plugin_id in getattr(self, '_plugin_pages_registered', set()):
            return

        if not hasattr(self, '_plugin_pages_registered'):
            self._plugin_pages_registered = set()
        self._plugin_pages_registered.add(plugin_id)

        import typing
        from fastapi import Depends, HTTPException
        from webui.routes.auth import require_auth

        mgr = self
        registered: List[str] = []

        for page in comp.pages:
            func = page["func"]
            func_name = func.__name__
            route_path = page["route"].lstrip('/')
            full_path = f"/page/plugin/{plugin_id}/{route_path}"

            # Handle catch-all routes (e.g., /{path:path})
            if '{' in route_path and ':path}' in route_path:
                full_path = f"/page/plugin/{plugin_id}/" + "{path:path}"

            # Resolve annotations eagerly using the plugin module's own globals
            try:
                resolved_hints = typing.get_type_hints(func, globalns=func.__globals__)
            except Exception:
                resolved_hints = {}

            params = [
                p.replace(annotation=resolved_hints.get(name, p.annotation))
                for name, p in inspect.signature(func).parameters.items()
                if name != "self"
            ]

            # Capture loop variables via default args to avoid closure issues
            async def dynamic_page_endpoint(
                _pid=plugin_id, _fname=func_name, _mgr=mgr, **kwargs
            ):
                inst = _mgr.plugin_instances.get(_pid)
                if inst is None:
                    raise HTTPException(status_code=503, detail="Plugin not available")
                return await getattr(inst, _fname)(**kwargs)

            dynamic_page_endpoint.__signature__ = inspect.Signature(params)

            dependencies = []
            if page["auth"]:
                dependencies.append(Depends(require_auth))

            self._web_app.add_api_route(
                path=full_path,
                endpoint=dynamic_page_endpoint,
                methods=["GET"],
                dependencies=dependencies,
                tags=[f"plugin:{plugin_id}"],
            )
            registered.append(full_path)

        if registered:
            logger.info(f"Registered {len(registered)} page routes from {plugin_id}: {registered}")
    
    def _register_plugin_static_for(self, plugin_id: str) -> None:
        """Register static file routes for a plugin with plugin state check."""
        if self._web_app is None:
            return

        comp = _plugin_components.get(plugin_id)
        if not comp or not comp.static_dirs:
            return
            return

        # Track registered static dirs to avoid duplicates
        if plugin_id in getattr(self, '_plugin_static_registered', set()):
            return

        if not hasattr(self, '_plugin_static_registered'):
            self._plugin_static_registered = set()
        self._plugin_static_registered.add(plugin_id)

        from fastapi import Depends, HTTPException
        from fastapi.responses import FileResponse
        from fastapi.staticfiles import StaticFiles
        from starlette.routing import Route
        import mimetypes

        mgr = self
        plugin_root = _plugin_module_paths.get(plugin_id)
        if not plugin_root:
            return

        def _make_plugin_check(pid: str):
            async def check():
                if not mgr.is_plugin_enabled(pid):
                    raise HTTPException(status_code=404, detail="Plugin disabled")
            return check

        registered: List[str] = []

        for static in comp.static_dirs:
            path_prefix = static["path"].lstrip('/')
            full_path = f"/page/plugin/{plugin_id}/{path_prefix}"
            dir_path = plugin_root / static["directory"]

            if not dir_path.exists() or not dir_path.is_dir():
                continue

            # Create a custom StaticFiles class that checks plugin state
            class PluginStaticFiles(StaticFiles):
                def __init__(self, directory: str, check_func, html: bool = False):
                    super().__init__(directory=directory, html=html)
                    self._check_func = check_func

                async def __call__(self, scope, receive, send):
                    # Check plugin state before serving files
                    await self._check_func()
                    await super().__call__(scope, receive, send)

            try:
                self._web_app.mount(
                    full_path,
                    PluginStaticFiles(
                        directory=str(dir_path),
                        check_func=_make_plugin_check(plugin_id),
                        html=static.get("html", False)
                    ),
                    name=f"plugin_{plugin_id}_static_{path_prefix}"
                )
                registered.append(full_path)
            except Exception as e:
                logger.error(f"Failed to mount static dir {dir_path} for plugin {plugin_id}: {e}")

        if registered:
            logger.info(f"Registered {len(registered)} static directories from {plugin_id}: {registered}")

    def register_plugin_tools(self) -> None:
        for plugin_id in _plugin_components.keys():
            self._register_plugin_tools_for(plugin_id)

    def _remove_plugin_routes(self, plugin_id: str) -> None:
        """Remove all FastAPI routes and mounts registered by a plugin.

        Cleans up API routes, page routes, and static file mounts from
        the web app, and resets the tracking sets so re-registration works.
        """
        # Reset tracking sets so init_plugin can re-register
        _plugin_api_registered.discard(plugin_id)
        if hasattr(self, '_plugin_pages_registered'):
            self._plugin_pages_registered.discard(plugin_id)
        if hasattr(self, '_plugin_static_registered'):
            self._plugin_static_registered.discard(plugin_id)

        if self._web_app is None:
            return

        tag_prefix = f"plugin:{plugin_id}"
        page_prefix = f"/page/plugin/{plugin_id}/"
        static_prefix = f"/static/plugin/{plugin_id}/"

        routes = self._web_app.routes
        filtered_routes = []
        removed = 0
        for route in routes:
            should_remove = False

            # API / page routes registered via add_api_route
            if hasattr(route, 'tags') and tag_prefix in (route.tags or []):
                should_remove = True
            # Page catch-all routes or static mounts
            elif hasattr(route, 'path') and (
                route.path.startswith(page_prefix) or route.path.startswith(static_prefix)
            ):
                should_remove = True

            if should_remove:
                removed += 1
            else:
                filtered_routes.append(route)

        if removed:
            routes.clear()
            routes.extend(filtered_routes)
            # Invalidate the OpenAPI schema cache so it gets regenerated
            self._web_app.openapi_schema = None
            logger.debug(f"Removed {removed} route(s) for plugin {plugin_id}")

    def _cleanup_plugin_registration(self, plugin_id: str) -> None:
        comp = _plugin_components.get(plugin_id)
        if not comp:
            return

        # clean up tool registration
        if self.ctx and getattr(self.ctx, "llm_api", None):
            for tool_name in list(comp.tools.keys()):
                try:
                    self.ctx.llm_api.unregister_tool(tool_name)
                except Exception as e:
                    logger.error(f"Failed to unregister tool {tool_name} for plugin {plugin_id}: {e}")

        # clean up hook registration
        for hook in comp.hooks:
            event_handler_reg.del_handler(hook)

        # clean up tag registration
        for tag in comp.tags:
            tag_registry.unregister(tag.get("name"))

        # clean up FastAPI routes (API routes, page routes, static mounts)
        self._remove_plugin_routes(plugin_id)

    def _load_plugin_config_from_file(self, plugin_id: str) -> Dict[str, Any]:
        PLUGIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_path = PLUGIN_CONFIG_DIR / f"{plugin_id}.json"
        cfg: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg = loaded
            except Exception as e:
                logger.error(f"Failed to load plugin config from {config_path}: {e}")
        return cfg

    def _ensure_plugin_config(self, plugin_name: str, schema_fields: List[BaseConfigField]) -> None:
        if not schema_fields:
            return
        PLUGIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_path = PLUGIN_CONFIG_DIR / f"{plugin_name}.json"
        cfg: Dict[str, Any] = self._load_plugin_config_from_file(plugin_name)
        for field in schema_fields:
            if isinstance(field, SectionField):
                section_cfg = cfg.get(field.key)
                if not isinstance(section_cfg, dict):
                    section_cfg = {}
                for child in field.fields:
                    if isinstance(child, BaseConfigField) and child.key not in section_cfg:
                        section_cfg[child.key] = child.default
                cfg[field.key] = section_cfg
            elif isinstance(field, BaseConfigField) and field.key not in cfg:
                cfg[field.key] = field.default
        try:
            with config_path.open("w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save plugin config for {plugin_name}: {e}")
        self.plugin_configs[plugin_name] = cfg

    async def init(self):
        """
        Initialize plugin manager and load all discovered plugins
        """
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)

        await self._discover_builtin_plugins()
        await self._discover_user_plugins()

        discovered = list(_plugin_classes.keys())
        logger.info(f"Discovered plugins: {discovered}")

        for plugin_id in _plugin_classes.keys():
            if plugin_id in self.plugin_instances:
                continue
            await self.init_plugin(plugin_id)

    async def init_plugin(self, plugin_id: Optional[str] = None):
        if plugin_id is None:
            for pid in list(_plugin_classes.keys()):
                await self.init_plugin(pid)
            return

        plugin_id = str(plugin_id)
        plugin_cls = _plugin_classes.get(plugin_id)
        if not plugin_cls:
            logger.warning(f"No plugin class found for {plugin_id}, cannot initialize")
            return

        if not self.is_plugin_enabled(plugin_id):
            logger.debug(f"Plugin {plugin_id} is disabled, skipping initialization")
            return

        existing = self.plugin_instances.get(plugin_id)
        if existing is not None:
            try:
                await self.terminate(plugin_id)
            except Exception as e:
                logger.error(f"Error terminating plugin {plugin_id} before reinitialization: {e}")

        schema_fields = _plugin_schemas.get(plugin_id, [])
        if schema_fields:
            self._ensure_plugin_config(plugin_id, schema_fields)
            cfg = self.plugin_configs.get(plugin_id) or {}
        else:
            cfg: Dict[str, Any] = self._load_plugin_config_from_file(plugin_id)
            self.plugin_configs[plugin_id] = cfg

        try:
            instance = plugin_cls(self.ctx, cfg)
        except Exception as e:
            logger.error(f"Failed to instantiate plugin {plugin_id}: {e}")
            return
        self.plugin_instances[plugin_id] = instance
        initialized = False
        try:
            await instance.initialize()
            initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize plugin {plugin_id}: {e}")
        if initialized:
            self._register_plugin_tools_for(plugin_id)
            self._register_plugin_hooks_for(plugin_id)
            self._register_plugin_tags_for(plugin_id)
            self._register_plugin_apis_for(plugin_id)
            self._register_plugin_pages_for(plugin_id)
            self._register_plugin_static_for(plugin_id)

    async def terminate(self, plugin_id: Optional[str] = None):
        """Terminate a specific plugin if plugin_id is given, terminate all if not given"""
        if plugin_id:
            try:
                plugin_instance = self.plugin_instances.get(plugin_id)
                if plugin_instance:
                    await plugin_instance.terminate()
                self.plugin_instances.pop(plugin_id, None)
                self.plugin_configs.pop(plugin_id, None)
                logger.info(f"Terminated plugin {plugin_id}")
            except Exception as e:
                logger.error(f"Error terminating plugin {plugin_id}: {e}")
            self._cleanup_plugin_registration(plugin_id)
            return

        for plug_id, plugin_instance in list(self.plugin_instances.items()):
            try:
                await plugin_instance.terminate()
            except Exception as e:
                logger.error(f"Error terminating plugin {plug_id}: {e}")

        # Clear registries
        self.plugin_instances.clear()
        self.plugin_configs.clear()
        for name in list(_plugin_components.keys()):
            self._cleanup_plugin_registration(name)

    async def uninstall_plugin(self, plugin_id: str) -> None:
        """
        Terminate a plugin and remove all its registrations from memory.
        The caller is responsible for deleting the plugin directory afterwards.
        """
        # Allow uninstalling failed plugins that never fully loaded
        if plugin_id in _plugin_load_errors:
            _plugin_load_errors.pop(plugin_id, None)
            _plugin_manifests.pop(plugin_id, None)
            _plugin_infos.pop(plugin_id, None)
            self.plugin_enabled.pop(plugin_id, None)
            self._save_plugin_state()
            logger.info(f"Failed plugin '{plugin_id}' removed from records")
            return

        if plugin_id not in _plugin_classes:
            raise ValueError(f"Plugin '{plugin_id}' is not registered")

        # Stop the running instance and unregister tools / hooks / tags
        await self.terminate(plugin_id)

        # Remove module-to-plugin mappings and evict from sys.modules
        self._cleanup_plugin_modules(plugin_id)

        # Remove from global registries
        _plugin_classes.pop(plugin_id, None)
        _plugin_manifests.pop(plugin_id, None)
        _plugin_module_dirs.pop(plugin_id, None)
        _plugin_module_paths.pop(plugin_id, None)
        _plugin_schemas.pop(plugin_id, None)
        _plugin_components.pop(plugin_id, None)
        _plugin_load_errors.pop(plugin_id, None)
        _plugin_infos.pop(plugin_id, None)

        # Remove enabled state and persist
        self.plugin_enabled.pop(plugin_id, None)
        self._save_plugin_state()

        logger.info(f"Plugin '{plugin_id}' uninstalled from memory")

    def _cleanup_plugin_modules(self, plugin_id: str) -> None:
        """Remove a plugin's own modules from sys.modules.

        Uses both the module-name→plugin-id mapping and file-path matching
        to find all modules that belong to this plugin.  Third-party modules
        imported by the plugin are left untouched (they may be shared).
        """
        plugin_dir = _plugin_module_paths.get(plugin_id)
        cleaned = 0

        for name, mod in list(sys.modules.items()):
            matched = False

            # 1) Direct mapping from _register_plugin_class
            if _module_to_plugin.get(name) == plugin_id:
                matched = True

            # 2) Path-based: module file lives inside the plugin directory
            elif plugin_dir:
                mod_file = getattr(mod, "__file__", None)
                if mod_file:
                    try:
                        matched = Path(mod_file).resolve().is_relative_to(plugin_dir)
                    except (ValueError, OSError):
                        pass

            if matched:
                sys.modules.pop(name, None)
                _module_to_plugin.pop(name, None)
                cleaned += 1

        if cleaned:
            logger.debug(f"Cleaned {cleaned} module(s) for plugin {plugin_id}")

    async def reload(self, plugin_id: Optional[str] = None):
        """
        Reload all plugins or reload a specific user plugin.
        Builtin plugins are not supported for single-plugin reload.
        """
        if plugin_id:
            plugin_id = str(plugin_id)
            logger.info(f"Reloading plugin {plugin_id}...")

            # 1. Terminate the running instance
            await self.terminate(plugin_id)

            # 2. Remove class / schema / error registrations
            _plugin_classes.pop(plugin_id, None)
            _plugin_schemas.pop(plugin_id, None)
            _plugin_load_errors.pop(plugin_id, None)

            # 3. Purge the plugin's own modules from sys.modules
            self._cleanup_plugin_modules(plugin_id)

            # 4. Re-import from disk
            plugin_dir = _plugin_module_paths.get(plugin_id)
            if plugin_dir and plugin_dir.exists():
                await self.load_plugin_from_dir(plugin_dir)
            else:
                logger.warning(f"Plugin directory not found for {plugin_id}, cannot reload")
            return

        logger.info("Reloading all plugins...")
        await self.terminate()
        await self.init()

    @staticmethod
    def _check_core_version(core_version_spec: str) -> Optional[str]:
        """Check if the current KiraAI version satisfies the given specifier string.

        Returns None if compatible, or an error message string if not.
        """
        try:
            spec = SpecifierSet(core_version_spec)
        except InvalidSpecifier:
            return f"Invalid core_version specifier: {core_version_spec}"

        current = VERSION.lstrip("v")
        try:
            ver = Version(current)
        except InvalidVersion:
            return f"Cannot parse current KiraAI version: {VERSION}"

        if ver not in spec:
            return (
                f"Requires KiraAI {core_version_spec}, "
                f"but current version is {VERSION}"
            )
        return None

    @staticmethod
    def _build_plugin_info(plugin_id: str, manifest: dict, error: Optional[str] = None) -> PluginInfo:
        path = _plugin_module_paths.get(plugin_id)
        is_builtin = path is not None and path.is_relative_to(BUILTIN_PLUGINS_DIR)
        hidden = bool(manifest.get("hide", False)) if is_builtin else False
        if is_builtin:
            uninstallable = bool(manifest.get("uninstallable", False))
        else:
            uninstallable = True

        return PluginInfo(
            plugin_id=plugin_id,
            display_name=manifest.get("display_name") or plugin_id,
            version=str(manifest.get("version") or ""),
            author=str(manifest.get("author") or ""),
            description=str(manifest.get("description") or ""),
            repo=manifest.get("repo") if isinstance(manifest.get("repo"), str) and manifest.get("repo") else None,
            locales=manifest.get("locales") or {},
            tags=[str(t) for t in (manifest.get("tags") or []) if t],
            core_version=str(manifest["core_version"]) if manifest.get("core_version") else None,
            builtin=is_builtin,
            uninstallable=uninstallable,
            hidden=hidden,
            error=error,
        )

    def _load_plugin_meta(self, plugin_root: Path, entry: str):
        manifest = {}
        manifest_path = plugin_root / "manifest.json"
        schema_path = plugin_root / "schema.json"

        if manifest_path.exists():
            try:
                with manifest_path.open("r", encoding="utf-8") as f:
                    manifest = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load manifest for plugin {entry}: {e}")

        plugin_id = manifest.get("plugin_id") or entry

        # Persist directory info early so failed plugins can be found for retry
        _plugin_module_dirs[plugin_id] = plugin_root.name
        _plugin_module_paths[plugin_id] = plugin_root

        if manifest:
            _plugin_manifests[plugin_id] = manifest

        # Build PluginInfo early — even if class loading later fails, we have metadata
        _plugin_infos[plugin_id] = self._build_plugin_info(plugin_id, manifest)

        # Check core_version compatibility
        core_version_spec = manifest.get("core_version")
        if core_version_spec:
            error = self._check_core_version(str(core_version_spec))
            if error:
                _plugin_load_errors[plugin_id] = {
                    "manifest": manifest,
                    "error": error,
                }
                _plugin_infos[plugin_id].error = error
                logger.warning(f"Plugin {plugin_id} skipped: {error}")
                return None

        schema_fields: List[BaseConfigField] = []
        if schema_path.exists():
            try:
                with schema_path.open("r", encoding="utf-8") as f:
                    raw_schema = json.load(f)
                if isinstance(raw_schema, dict):
                    schema_fields = build_fields(raw_schema)
            except Exception as e:
                logger.warning(f"Failed to load schema for plugin {plugin_id}: {e}")

        if schema_fields:
            _plugin_schemas[plugin_id] = schema_fields
            self._ensure_plugin_config(plugin_id, schema_fields)

        return plugin_id

    @staticmethod
    def _register_plugin_class(plugin_id: str, module, fallback_path: Path):
        for _, attr_value in inspect.getmembers(module, inspect.isclass):
            if issubclass(attr_value, BasePlugin) and attr_value is not BasePlugin:
                _plugin_classes[plugin_id] = attr_value

                module_file = Path(
                    getattr(module, "__file__", fallback_path)
                ).resolve()

                module_dir = module_file.parent

                _plugin_module_dirs[plugin_id] = module_dir.name
                _plugin_module_paths[plugin_id] = module_dir
                _module_to_plugin[module.__name__] = plugin_id
                return True

        return False

    async def _discover_builtin_plugins(self):
        if not BUILTIN_PLUGINS_DIR.exists():
            return

        for entry in os.listdir(BUILTIN_PLUGINS_DIR):
            if entry.startswith("_"):
                continue
            plugin_dir = BUILTIN_PLUGINS_DIR / entry
            if not plugin_dir.is_dir():
                continue

            plugin_id = self._load_plugin_meta(plugin_dir, entry)
            if plugin_id is None:
                continue

            # Clear any previous load error
            _plugin_load_errors.pop(plugin_id, None)

            module = None
            candidate_modules = [
                f"core.plugin.builtin_plugins.{entry}.main",
                f"core.plugin.builtin_plugins.{entry}",
            ]

            for module_name in candidate_modules:
                try:
                    module = importlib.import_module(module_name)
                    break
                except ModuleNotFoundError:
                    continue
                except Exception as e:
                    logger.error(f"Failed to import builtin plugin module {module_name}: {e}")
                    module = None
                    break

            if module is None:
                logger.warning(f"No module found for builtin plugin {entry}")
                _plugin_load_errors.setdefault(plugin_id, {
                    "manifest": _plugin_manifests.get(plugin_id, {}),
                    "error": "No module found",
                })
                if plugin_id in _plugin_infos:
                    _plugin_infos[plugin_id].error = "No module found"
                continue

            self._register_plugin_class(plugin_id, module, plugin_dir)

    async def load_plugin_from_dir(self, plugin_root: Path) -> Optional[str]:
        """
        Dynamically load and initialize a single plugin from the given directory.

        Safe to call at runtime (e.g. after installing a new plugin). If the
        plugin was already loaded, it is terminated and reloaded cleanly.
        Returns the plugin_id on success, or None if loading failed.
        """
        entry = plugin_root.name
        if entry.startswith("_") or not plugin_root.is_dir():
            return None

        plugin_id = self._load_plugin_meta(plugin_root, entry)
        if plugin_id is None:
            return None

        # Clear any previous load error (e.g. plugin was fixed since last attempt)
        _plugin_load_errors.pop(plugin_id, None)

        # Ensure the top-level "plugins" package is registered in sys.modules
        base_package = "plugins"
        if base_package not in sys.modules:
            pkg = types.ModuleType(base_package)
            pkg.__path__ = [str(self.plugin_dir)]
            sys.modules[base_package] = pkg

        # (Re-)create the sub-package entry so stale cached modules are replaced
        package_name = f"{base_package}.{entry}"
        sub_pkg = types.ModuleType(package_name)
        sub_pkg.__path__ = [str(plugin_root)]
        sys.modules[package_name] = sub_pkg

        # Locate the entry-point script
        script_path: Optional[Path] = None
        module_name: Optional[str] = None
        for filename, suffix in [("main.py", "main"), ("plugin.py", "plugin")]:
            candidate = plugin_root / filename
            if candidate.exists():
                script_path = candidate
                module_name = f"{package_name}.{suffix}"
                break
        if not script_path:
            init_path = plugin_root / "__init__.py"
            if init_path.exists():
                script_path = init_path
                module_name = package_name

        if not script_path or not module_name:
            logger.warning(f"No entry script found in plugin directory: {plugin_root}")
            _plugin_load_errors[plugin_id] = {
                "manifest": _plugin_manifests.get(plugin_id, {}),
                "error": "No entry script found (main.py / plugin.py / __init__.py)",
            }
            if plugin_id in _plugin_infos:
                _plugin_infos[plugin_id].error = "No entry script found (main.py / plugin.py / __init__.py)"
            return None

        # Clear decorator-registered components so re-import starts fresh
        if plugin_id in _plugin_components:
            _plugin_components[plugin_id] = PluginComponents()

        # Remove stale module from cache so exec_module re-runs the file
        sys.modules.pop(module_name, None)

        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if not spec or not spec.loader:
            logger.warning(f"Failed to create module spec for: {plugin_root}")
            _plugin_load_errors[plugin_id] = {
                "manifest": _plugin_manifests.get(plugin_id, {}),
                "error": "Failed to create module spec",
            }
            if plugin_id in _plugin_infos:
                _plugin_infos[plugin_id].error = "Failed to create module spec"
            return None

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            logger.error(f"Error loading plugin from {plugin_root}: {e}")
            sys.modules.pop(module_name, None)
            _plugin_load_errors[plugin_id] = {
                "manifest": _plugin_manifests.get(plugin_id, {}),
                "error": f"Import error: {e}",
            }
            if plugin_id in _plugin_infos:
                _plugin_infos[plugin_id].error = f"Import error: {e}"
            return None

        registered = self._register_plugin_class(plugin_id, module, plugin_root)
        if not registered:
            logger.warning(f"No BasePlugin subclass found in {plugin_root}")
            _plugin_load_errors[plugin_id] = {
                "manifest": _plugin_manifests.get(plugin_id, {}),
                "error": "No BasePlugin subclass found",
            }
            if plugin_id in _plugin_infos:
                _plugin_infos[plugin_id].error = "No BasePlugin subclass found"
            return None

        await self.init_plugin(plugin_id)
        return plugin_id

    async def _discover_user_plugins(self):
        if not self.plugin_dir.exists():
            return

        base_package = "plugins"
        if base_package not in sys.modules:
            pkg = types.ModuleType(base_package)
            pkg.__path__ = [str(self.plugin_dir)]
            sys.modules[base_package] = pkg

        for entry in os.listdir(self.plugin_dir):
            if entry.startswith("_"):
                continue
            plugin_root = self.plugin_dir / entry
            if not plugin_root.is_dir():
                continue
            await self.load_plugin_from_dir(plugin_root)

    @staticmethod
    async def fetch_plugin_store_data(url: str) -> Any:
        """
        Fetch the raw JSON data from a plugin store source URL.

        Returns the complete original JSON (including ``meta``, ``plugins``, etc.).
        Callers should extract the ``plugins`` collection themselves.
        """
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.json()
