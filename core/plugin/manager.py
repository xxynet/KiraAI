import importlib
import importlib.util
import inspect
import os
import json
import sys
import types
import httpx
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion
from core.utils.path_utils import get_data_path, get_config_path, resolve_manifest_icon_path
from core.logging_manager import get_logger
from core.config.config_field import BaseConfigField, SectionField, build_fields
from core.provider import BaseProvider, ProviderManager
from core.adapter import AdapterManager
from core.adapter.adapter_utils import IMAdapter, SocialMediaAdapter
from core.adapter.base import BaseAdapter
from core.config import VERSION
from . import registry
from .components import PluginComponents
from .metadata import PluginInfo
from .base import BasePlugin
from .plugin_context import PluginContext
from .handlers import event_handler_reg, EventType
from .plugin_installer import install_requirements

from core.tag import tag_registry, BaseTag


logger = get_logger("plugin_manager", "cyan")

PLUGINS_DIR = get_data_path() / "plugins"
PLUGIN_DATA_DIR = get_data_path() / "plugin_data"
PLUGIN_CONFIG_DIR = get_config_path() / "plugins"
PLUGIN_STATE_FILE = get_config_path() / "plugins.json"
BUILTIN_PLUGINS_DIR = Path(__file__).parent / "builtin_plugins"


def _build_tag_inst(tag_name: str, tag_description: str, func: Callable, tag_parent: Optional[str] = "msg"):
    class TagInst(BaseTag):
        name = tag_name
        description = tag_description
        parent = tag_parent

        async def handle(self, value: str, **kwargs):
            res = await func(value, **kwargs)
            return res

    return TagInst()


def _compare_versions(current: str, latest: str) -> bool:
    """Return True if latest > current. Strips leading 'v'."""
    try:
        return Version(latest.lstrip("v")) > Version(current.lstrip("v"))
    except InvalidVersion:
        return False


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
        self._web_bindings = None

        self._load_plugin_state()

    def _get_web_bindings(self):
        """Load WebUI integration lazily and bind registrations to this app."""
        from webui.plugin_bindings import PluginWebBindings

        if self._web_bindings is None or self._web_bindings.app is not self._web_app:
            self._web_bindings = PluginWebBindings(self, self._web_app)
        return self._web_bindings

    def set_web_app(self, app) -> None:
        """Provide the FastAPI app instance so plugin API routes can be registered.
        Also registers routes for any plugins that were already initialized before this call.
        """
        self._web_app = app
        # Store reference so WS endpoints can access the manager without
        # capturing it in closures (which breaks FastAPI's deepcopy during
        # dependency resolution for WebSocket routes).
        app.state.plugin_manager = self
        for plugin_id in list(self.plugin_instances.keys()):
            self._register_plugin_apis_for(plugin_id)
            self._register_plugin_ws_for(plugin_id)
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
            if plugin_id in self.plugin_instances and plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].status = "ready"
        elif not enabled and previous:
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].status = "disabled"
            try:
                await self.terminate(plugin_id)
            except Exception as e:
                logger.error(f"Failed to terminate plugin {plugin_id} when disabling: {e}")

    def get_registered_plugins(self) -> Dict[str, type[BasePlugin]]:
        return dict(registry._plugin_classes)

    def has_plugin(self, plugin_id: str) -> bool:
        return plugin_id in registry._plugin_infos

    def list_plugins(self) -> List[PluginInfo]:
        return list(registry._plugin_infos.values())

    def get_plugin_info(self, plugin_id: str) -> Optional[PluginInfo]:
        return registry._plugin_infos.get(plugin_id)

    def get_plugin_manifest(self, name: str) -> Dict[str, Any]:
        return registry._plugin_manifests.get(name, {})

    def get_plugin_load_errors(self) -> Dict[str, Dict[str, Any]]:
        return dict(registry._plugin_load_errors)

    def _get_pypi_mirror(self) -> Optional[str]:
        if self.ctx and hasattr(self.ctx, "config"):
            return (self.ctx.config.get("network") or {}).get("pypi_mirror") or None
        return None

    def get_plugin_module_dir(self, name: str) -> str:
        return registry._plugin_module_dirs.get(name, "")

    def get_plugin_module_path(self, name: str) -> Optional[Path]:
        return registry._plugin_module_paths.get(name)

    def is_builtin_plugin(self, plugin_id: str) -> bool:
        path = registry._plugin_module_paths.get(plugin_id)
        if path is None:
            return False
        return path.is_relative_to(BUILTIN_PLUGINS_DIR)

    def is_plugin_hidden(self, plugin_id: str) -> bool:
        if not self.is_builtin_plugin(plugin_id):
            return False
        manifest = registry._plugin_manifests.get(plugin_id, {})
        return bool(manifest.get("hide", False))

    def is_plugin_uninstallable(self, plugin_id: str) -> bool:
        if not self.is_builtin_plugin(plugin_id):
            return True
        manifest = registry._plugin_manifests.get(plugin_id, {})
        return bool(manifest.get("uninstallable", False))

    def get_plugin_id_for_module(self, module_name: str) -> Optional[str]:
        return registry._module_to_plugin.get(module_name)

    def get_plugin_schema(self, name: str) -> List[BaseConfigField]:
        return registry._plugin_schemas.get(name, [])

    def get_plugin_config(self, plugin_name: str) -> Dict[str, Any]:
        plugin_name = str(plugin_name)
        if plugin_name in self.plugin_configs:
            return dict(self.plugin_configs.get(plugin_name, {}))
        schema_fields = registry._plugin_schemas.get(plugin_name, [])
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
        schema_fields = registry._plugin_schemas.get(plugin_name, [])
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
        return dict(registry._plugin_components)

    def get_page_menu_icon_path(self, plugin_id: str, page_route: str) -> Optional[Path]:
        """Resolve a page menu icon that references an SVG file in the plugin.

        ``PageMenu.icon`` accepts either an Element Plus icon name or a path
        to an ``.svg`` file relative to the plugin root (e.g.
        ``"assets/icon.svg"``; a leading slash is tolerated).  Returns the
        resolved file path for SVG file references, or ``None`` when the
        icon is an icon name, missing, not an SVG, or escapes the plugin
        root.
        """
        comp = registry._plugin_components.get(plugin_id)
        if not comp:
            return None
        wanted = "/" + str(page_route).lstrip("/")
        menu = next(
            (page.get("menu") for page in comp.pages
             if page.get("route") == wanted and page.get("menu")),
            None,
        )
        if menu is None or not isinstance(menu.icon, str) or not menu.icon.strip():
            return None
        plugin_root = registry._plugin_module_paths.get(plugin_id)
        if plugin_root is None:
            return None
        # Tolerate a leading slash: authors may mirror the leading-slash
        # route convention, and resolve_manifest_icon_path rejects
        # absolute paths outright.
        return resolve_manifest_icon_path(plugin_root, menu.icon.strip().lstrip("/"),
                                          extensions=frozenset({".svg"}))

    def _resolve_plugin_component_dir(self, plugin_id: str, relative_path: str) -> Path:
        plugin_root = registry._plugin_module_paths.get(plugin_id)
        if plugin_root is None:
            raise ValueError(f"Plugin '{plugin_id}' has no registered root directory")
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise ValueError("Plugin component path must be relative to the plugin root")
        component_dir = (plugin_root / candidate).resolve()
        if not component_dir.is_relative_to(plugin_root.resolve()):
            raise ValueError("Plugin component path must stay inside the plugin root")
        if not component_dir.is_dir():
            raise ValueError(f"Plugin component directory does not exist: {relative_path}")
        return component_dir

    def _load_plugin_component_module(self, plugin_id: str, component_dir: Path, kind: str):
        plugin_root = registry._plugin_module_paths[plugin_id].resolve()
        package_name = f"plugins.{plugin_root.name}"
        package_dir = plugin_root
        for part in component_dir.relative_to(plugin_root).parts:
            package_name = f"{package_name}.{part}"
            package_dir = package_dir / part
            if package_name not in sys.modules:
                package = types.ModuleType(package_name)
                package.__path__ = [str(package_dir)]
                sys.modules[package_name] = package

        script_path = component_dir / f"{kind}.py"
        if not script_path.exists():
            script_path = component_dir / "__init__.py"
        if not script_path.exists():
            raise ValueError(f"No {kind}.py or __init__.py found in {component_dir}")

        module_name = f"{package_name}.__kira_{kind}__"
        module = sys.modules.get(module_name)
        if module is not None:
            return module
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if not spec or not spec.loader:
            raise ValueError(f"Failed to create module spec for {script_path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            sys.modules.pop(module_name, None)
            raise
        registry._module_to_plugin[module_name] = plugin_id
        return module

    @staticmethod
    def _find_component_class(module, base_types: tuple[type, ...], kind: str) -> type:
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                candidate.__module__ == module.__name__
                and issubclass(candidate, base_types)
                and candidate not in base_types
            ):
                return candidate
        names = ", ".join(base_type.__name__ for base_type in base_types)
        raise ValueError(f"No {kind} class inheriting from {names} found in {module.__name__}")

    async def register_plugin_provider(self, plugin_id: str, relative_path: str) -> str:
        if not self.ctx or not self.ctx.provider_mgr:
            raise RuntimeError("Provider manager is not available")
        component_dir = self._resolve_plugin_component_dir(plugin_id, relative_path)
        manifest_path = component_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"Provider manifest not found: {relative_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        provider_format = str(manifest.get("name") or "").strip()
        if not provider_format:
            raise ValueError("Provider manifest must define a name")
        comp = registry._ensure_components(plugin_id)
        existing = comp.providers.get(provider_format)
        if existing:
            if existing["path"] == component_dir:
                return provider_format
            raise ValueError(f"Plugin already registered Provider format '{provider_format}'")
        module = self._load_plugin_component_module(plugin_id, component_dir, "provider")
        provider_cls = self._find_component_class(module, (BaseProvider,), "Provider")
        raw_schema = {}
        schema_path = component_dir / "schema.json"
        if schema_path.exists():
            raw_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        schema = {
            "provider_config": build_fields(raw_schema.get("provider_config") or {}),
            "model_config": {
                model_type: build_fields(fields)
                for model_type, fields in (raw_schema.get("model_config") or {}).items()
                if isinstance(fields, dict)
            },
        }
        self.ctx.provider_mgr.register_provider_type(
            provider_format, provider_cls, manifest, component_dir, schema
        )
        comp.register_provider(provider_format, {"path": component_dir, "class": provider_cls})
        for provider_id, config in (self.ctx.config.get("providers", {}) or {}).items():
            if isinstance(config, dict) and config.get("format") == provider_format:
                self.ctx.provider_mgr.set_provider(provider_id, config)
        logger.info(f"Registered Provider format {provider_format} from plugin {plugin_id}")
        return provider_format

    async def unregister_plugin_provider(self, plugin_id: str, provider_format: str) -> bool:
        if not self.ctx or not self.ctx.provider_mgr:
            raise RuntimeError("Provider manager is not available")
        metadata = registry._ensure_components(plugin_id).unregister_provider(provider_format)
        if metadata is None:
            return False
        self.ctx.provider_mgr.remove_provider_instances_by_format(provider_format)
        removed = self.ctx.provider_mgr.unregister_provider_type(provider_format, metadata["class"])
        logger.info(f"Unregistered Provider format {provider_format} from plugin {plugin_id}")
        return removed

    async def register_plugin_adapter(self, plugin_id: str, relative_path: str) -> str:
        if not self.ctx or not self.ctx.adapter_mgr:
            raise RuntimeError("Adapter manager is not available")
        component_dir = self._resolve_plugin_component_dir(plugin_id, relative_path)
        manifest_path = component_dir / "manifest.json"
        if not manifest_path.exists():
            raise ValueError(f"Adapter manifest not found: {relative_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        platform = str(manifest.get("name") or "").strip()
        if not platform:
            raise ValueError("Adapter manifest must define a name")
        comp = registry._ensure_components(plugin_id)
        existing = comp.adapters.get(platform)
        if existing:
            if existing["path"] == component_dir:
                return platform
            raise ValueError(f"Plugin already registered Adapter platform '{platform}'")
        module = self._load_plugin_component_module(plugin_id, component_dir, "adapter")
        adapter_cls = self._find_component_class(module, (BaseAdapter, IMAdapter, SocialMediaAdapter), "Adapter")
        raw_schema = {}
        schema_path = component_dir / "schema.json"
        if schema_path.exists():
            raw_schema = json.loads(schema_path.read_text(encoding="utf-8"))
        self.ctx.adapter_mgr.register_adapter_type(
            platform, adapter_cls, manifest, component_dir, build_fields(raw_schema)
        )
        comp.register_adapter(platform, {"path": component_dir, "class": adapter_cls})
        for adapter_id in (self.ctx.config.get("adapters", {}) or {}):
            info = self.ctx.adapter_mgr.get_adapter_info(adapter_id)
            if info and info.platform == platform:
                try:
                    await self.ctx.adapter_mgr.register_adapter(info)
                except Exception as e:
                    logger.error(
                        f"Failed to restore adapter {adapter_id} for plugin {plugin_id}: {e}"
                    )
        logger.info(f"Registered Adapter platform {platform} from plugin {plugin_id}")
        return platform

    async def unregister_plugin_adapter(self, plugin_id: str, platform: str) -> bool:
        """Remove a plugin-owned Adapter after its runtime instances stop."""
        if not self.ctx or not self.ctx.adapter_mgr:
            raise RuntimeError("Adapter manager is not available")
        comp = registry._ensure_components(plugin_id)
        metadata = comp.adapters.get(platform)
        if metadata is None:
            return False
        try:
            await self.ctx.adapter_mgr.stop_adapter_instances_by_platform(platform)
        except Exception as e:
            logger.error(
                f"Failed to stop Adapter platform {platform} for plugin {plugin_id}: {e}"
            )
            return False
        removed = self.ctx.adapter_mgr.unregister_adapter_type(platform, metadata["class"])
        if not removed:
            logger.error(
                f"Failed to unregister Adapter platform {platform} for plugin {plugin_id}"
            )
            return False
        comp.unregister_adapter(platform)
        logger.info(f"Unregistered Adapter platform {platform} from plugin {plugin_id}")
        return True

    def get_plugin_tools(self, plugin_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        if plugin_name is None:
            return {pid: dict(comp.tools) for pid, comp in registry._plugin_components.items()}
        comp = registry._plugin_components.get(plugin_name)
        return dict(comp.tools) if comp else {}

    def _register_plugin_tools_for(self, plugin_id: str) -> None:
        comp = registry._plugin_components.get(plugin_id)
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
            self.ctx.tool_mgr.register_tool(
                name=tool_name,
                description=meta.get("description", ""),
                parameters=meta.get("parameters") or {},
                func=bound_func,
            )
            tool_names.append(tool_name)
        if tool_names:
            logger.info(f"Registered {len(tool_names)} tools from {plugin_id}: {tool_names}")

    def _register_plugin_hooks_for(self, plugin_id: str):
        comp = registry._plugin_components.get(plugin_id)
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
        comp = registry._plugin_components.get(plugin_id)
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
                bound_func,
                tag_meta.get("parent", "msg")
            ))
            tag_names.append(tag_name)
        if tag_names:
            logger.info(f"Registered {len(tag_names)} tags from {plugin_id}: {tag_names}")

    def _register_plugin_apis_for(self, plugin_id: str) -> None:
        if self._web_app is not None:
            self._get_web_bindings().register_apis(plugin_id)

    def _register_plugin_ws_for(self, plugin_id: str) -> None:
        if self._web_app is not None:
            self._get_web_bindings().register_ws(plugin_id)

    def _register_plugin_pages_for(self, plugin_id: str) -> None:
        if self._web_app is not None:
            self._get_web_bindings().register_pages(plugin_id)

    def _register_plugin_static_for(self, plugin_id: str) -> None:
        if self._web_app is not None:
            self._get_web_bindings().register_static(plugin_id)

    def register_plugin_tools(self) -> None:
        for plugin_id in registry._plugin_components.keys():
            self._register_plugin_tools_for(plugin_id)

    def _register_plugin_widgets_for(self, plugin_id: str) -> None:
        """Log registered widgets for a plugin. Data is collected lazily."""
        comp = registry._plugin_components.get(plugin_id)
        if not comp or not comp.widgets:
            return
        widget_ids = [w["widget_id"] for w in comp.widgets]
        logger.info(f"Registered {len(widget_ids)} widget(s) from {plugin_id}: {widget_ids}")

    def get_all_widgets(self) -> list:
        return self._get_web_bindings().get_all_widgets()

    def _remove_plugin_routes(self, plugin_id: str) -> None:
        if self._web_app is not None:
            self._get_web_bindings().remove_routes(plugin_id)

    async def _cleanup_plugin_runtime_components(self, plugin_id: str) -> None:
        comp = registry._plugin_components.get(plugin_id)
        if not comp:
            return
        for platform in list(comp.adapters):
            try:
                if not await self.unregister_plugin_adapter(plugin_id, platform):
                    logger.error(
                        f"Adapter platform {platform} was not cleaned up for plugin {plugin_id}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to clean up Adapter platform {platform} for plugin {plugin_id}: {e}"
                )
        for provider_format in list(comp.providers):
            try:
                if not await self.unregister_plugin_provider(plugin_id, provider_format):
                    logger.error(
                        f"Provider format {provider_format} was not cleaned up for plugin {plugin_id}"
                    )
            except Exception as e:
                logger.error(
                    f"Failed to clean up Provider format {provider_format} for plugin {plugin_id}: {e}"
                )

    def _cleanup_plugin_registration(self, plugin_id: str) -> None:
        comp = registry._plugin_components.get(plugin_id)
        if not comp:
            return
        # clean up tool registration
        if self.ctx and getattr(self.ctx, "tool_mgr", None):
            for tool_name in list(comp.tools.keys()):
                try:
                    self.ctx.tool_mgr.unregister_tool(tool_name)
                except Exception as e:
                    logger.error(f"Failed to unregister tool {tool_name} for plugin {plugin_id}: {e}")

        # clean up hook registration
        for hook in comp.hooks:
            event_handler_reg.del_handler(hook)

        # clean up tag registration
        for tag in comp.tags:
            tag_registry.unregister(tag.get("name"))

        # Widget declarations are module-level metadata, just like API and page
        # declarations.  Keep them across disable/enable so init_plugin() can
        # make them available again without re-importing the plugin module.

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
        Initialize plugin manager and load all discovered plugins.

        Uses a two-phase approach: first attempt all loads, then install
        dependencies for plugins that failed with import errors and retry.
        """
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)

        await self._discover_builtin_plugins()
        await self._discover_user_plugins()

        discovered = list(registry._plugin_classes.keys())
        logger.info(f"Discovered plugins: {discovered}")

        # Phase 1: Attempt to initialize all discovered plugins
        for plugin_id in registry._plugin_classes.keys():
            if plugin_id in self.plugin_instances:
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].status = "ready"
                continue
            await self.init_plugin(plugin_id)
            if plugin_id in self.plugin_instances and plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].status = "ready"

        # Phase 2: Recover plugins that failed with import errors.
        # Detect missing-dependency failures reliably: accept any error_type that
        # is an ImportError subclass (covers ModuleNotFoundError and ImportError),
        # and fall back to the error message when error_type was not stored.
        def _is_missing_dep_failure(err_info: Dict[str, Any]) -> bool:
            err_type = err_info.get("error_type")
            return isinstance(err_type, type) and issubclass(err_type, ImportError)

        import_failures = [
            pid for pid, err_info in registry._plugin_load_errors.items()
            if _is_missing_dep_failure(err_info) and pid in registry._plugin_module_paths
        ]
        if import_failures:
            logger.info(f"Plugins with import errors, will attempt dependency install: {import_failures}")

        for plugin_id in import_failures:
            plugin_path = registry._plugin_module_paths.get(plugin_id)
            if not plugin_path:
                continue

            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].status = "installing"

            warnings = await install_requirements(plugin_path, pypi_mirror=self._get_pypi_mirror())
            for w in warnings:
                logger.warning(f"Dependency install warning for {plugin_id}: {w}")

            # Clear old error and retry loading
            registry._plugin_load_errors.pop(plugin_id, None)
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].error = None
                registry._plugin_infos[plugin_id].status = "loading"

            await self.load_plugin_from_dir(plugin_path, auto_install=False)

            if plugin_id in self.plugin_instances:
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].status = "ready"
                logger.info(f"Successfully recovered plugin {plugin_id} after dependency install")
            else:
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].status = "error"
                logger.warning(f"Plugin {plugin_id} still failed after dependency install")

    async def init_plugin(self, plugin_id: Optional[str] = None):
        if plugin_id is None:
            for pid in list(registry._plugin_classes.keys()):
                await self.init_plugin(pid)
            return

        plugin_id = str(plugin_id)
        plugin_cls = registry._plugin_classes.get(plugin_id)
        if not plugin_cls:
            logger.warning(f"No plugin class found for {plugin_id}, cannot initialize")
            return

        if not self.is_plugin_enabled(plugin_id):
            logger.debug(f"Plugin {plugin_id} is disabled, skipping initialization")
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].status = "disabled"
            return

        existing = self.plugin_instances.get(plugin_id)
        if existing is not None:
            try:
                await self.terminate(plugin_id)
            except Exception as e:
                logger.error(f"Error terminating plugin {plugin_id} before reinitialization: {e}")

        schema_fields = registry._plugin_schemas.get(plugin_id, [])
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
            self.plugin_instances.pop(plugin_id, None)
        if initialized:
            self._register_plugin_tools_for(plugin_id)
            self._register_plugin_hooks_for(plugin_id)
            self._register_plugin_tags_for(plugin_id)
            self._register_plugin_apis_for(plugin_id)
            self._register_plugin_ws_for(plugin_id)
            self._register_plugin_pages_for(plugin_id)
            self._register_plugin_static_for(plugin_id)
            self._register_plugin_widgets_for(plugin_id)

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
            await self._cleanup_plugin_runtime_components(plugin_id)
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
        for name in list(registry._plugin_components.keys()):
            await self._cleanup_plugin_runtime_components(name)
            self._cleanup_plugin_registration(name)

    async def uninstall_plugin(self, plugin_id: str) -> None:
        """
        Terminate a plugin and remove all its registrations from memory.
        The caller is responsible for deleting the plugin directory afterwards.
        """
        # Allow uninstalling failed plugins that never fully loaded
        if plugin_id in registry._plugin_load_errors:
            registry._plugin_load_errors.pop(plugin_id, None)
            registry._plugin_manifests.pop(plugin_id, None)
            registry._plugin_infos.pop(plugin_id, None)
            self.plugin_enabled.pop(plugin_id, None)
            self._save_plugin_state()
            logger.info(f"Failed plugin '{plugin_id}' removed from records")
            return

        if plugin_id not in registry._plugin_classes:
            raise ValueError(f"Plugin '{plugin_id}' is not registered")

        # Stop the running instance and unregister tools / hooks / tags
        await self.terminate(plugin_id)

        # Remove module-to-plugin mappings and evict from sys.modules
        self._cleanup_plugin_modules(plugin_id)

        # Remove from global registries
        registry._plugin_classes.pop(plugin_id, None)
        registry._plugin_manifests.pop(plugin_id, None)
        registry._plugin_module_dirs.pop(plugin_id, None)
        registry._plugin_module_paths.pop(plugin_id, None)
        registry._plugin_schemas.pop(plugin_id, None)
        registry._plugin_components.pop(plugin_id, None)
        registry._plugin_load_errors.pop(plugin_id, None)
        registry._plugin_infos.pop(plugin_id, None)

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
        plugin_dir = registry._plugin_module_paths.get(plugin_id)
        cleaned = 0

        for name, mod in list(sys.modules.items()):
            matched = False

            # 1) Direct mapping from _register_plugin_class
            if registry._module_to_plugin.get(name) == plugin_id:
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
                registry._module_to_plugin.pop(name, None)
                cleaned += 1

        if cleaned:
            logger.debug(f"Cleaned {cleaned} module(s) for plugin {plugin_id}")

    async def prepare_plugin_reload(self, plugin_id: str) -> None:
        """Stop a plugin and clear its runtime state before re-importing it."""
        # 1. Terminate the running instance

        plugin_id = str(plugin_id)
        await self.terminate(plugin_id)
        # 2. Remove class / schema / error registrations

        registry._plugin_classes.pop(plugin_id, None)
        registry._plugin_schemas.pop(plugin_id, None)
        registry._plugin_load_errors.pop(plugin_id, None)
        # 3. Purge the plugin's own modules from sys.modules

        self._cleanup_plugin_modules(plugin_id)

    async def reload(self, plugin_id: Optional[str] = None):
        """
        Reload all plugins or reload a specific user plugin.
        Builtin plugins are not supported for single-plugin reload.
        """
        if plugin_id:
            plugin_id = str(plugin_id)
            logger.info(f"Reloading plugin {plugin_id}...")

            await self.prepare_plugin_reload(plugin_id)
            # 4. Re-import from disk
            plugin_dir = registry._plugin_module_paths.get(plugin_id)
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
            spec = SpecifierSet(core_version_spec, prereleases=True)
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
    def _build_plugin_info(plugin_id: str, manifest: dict, error: Optional[str] = None, status: str = "pending") -> PluginInfo:
        if status == "pending" and error:
            status = "error"
        path = registry._plugin_module_paths.get(plugin_id)
        is_builtin = path is not None and path.is_relative_to(BUILTIN_PLUGINS_DIR)
        hidden = bool(manifest.get("hide", False)) if is_builtin else False
        if is_builtin:
            uninstallable = bool(manifest.get("uninstallable", False))
        else:
            uninstallable = True
        icon = resolve_manifest_icon_path(path, manifest.get("icon")) if path else None
        icon_dark = resolve_manifest_icon_path(path, manifest.get("icon-dark")) if path else None

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
            icon=icon,
            icon_dark=icon_dark,
            builtin=is_builtin,
            uninstallable=uninstallable,
            hidden=hidden,
            error=error,
            status=status,
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
        registry._plugin_module_dirs[plugin_id] = plugin_root.name
        registry._plugin_module_paths[plugin_id] = plugin_root

        if manifest:
            registry._plugin_manifests[plugin_id] = manifest

        # Build PluginInfo early — even if class loading later fails, we have metadata
        registry._plugin_infos[plugin_id] = self._build_plugin_info(plugin_id, manifest)

        # Check core_version compatibility
        core_version_spec = manifest.get("core_version")
        if core_version_spec:
            error = self._check_core_version(str(core_version_spec))
            if error:
                registry._plugin_load_errors[plugin_id] = {
                    "manifest": manifest,
                    "error": error,
                }
                registry._plugin_infos[plugin_id].error = error
                registry._plugin_infos[plugin_id].status = "error"
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
            registry._plugin_schemas[plugin_id] = schema_fields
            self._ensure_plugin_config(plugin_id, schema_fields)

        return plugin_id

    @staticmethod
    def _register_plugin_class(plugin_id: str, module, fallback_path: Path):
        for _, attr_value in inspect.getmembers(module, inspect.isclass):
            if issubclass(attr_value, BasePlugin) and attr_value is not BasePlugin:
                registry._plugin_classes[plugin_id] = attr_value

                module_file = Path(
                    getattr(module, "__file__", fallback_path)
                ).resolve()

                module_dir = module_file.parent

                registry._plugin_module_dirs[plugin_id] = module_dir.name
                registry._plugin_module_paths[plugin_id] = module_dir
                registry._module_to_plugin[module.__name__] = plugin_id
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
            registry._plugin_load_errors.pop(plugin_id, None)

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
                registry._plugin_load_errors.setdefault(plugin_id, {
                    "manifest": registry._plugin_manifests.get(plugin_id, {}),
                    "error": "No module found",
                })
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].error = "No module found"
                    registry._plugin_infos[plugin_id].status = "error"
                continue

            self._register_plugin_class(plugin_id, module, plugin_dir)

    async def load_plugin_from_dir(self, plugin_root: Path, auto_install: bool = True) -> Optional[str]:
        """
        Dynamically load and initialize a single plugin from the given directory.

        Safe to call at runtime (e.g. after installing a new plugin). If the
        plugin was already loaded, it is terminated and reloaded cleanly.
        Returns the plugin_id on success, or None if loading failed.

        When *auto_install* is True and the import fails with ModuleNotFoundError,
        the plugin's requirements.txt is installed and the import is retried once.
        """
        entry = plugin_root.name
        if entry.startswith("_") or not plugin_root.is_dir():
            return None

        plugin_id = self._load_plugin_meta(plugin_root, entry)
        if plugin_id is None:
            return None

        # Clear any previous load error (e.g. plugin was fixed since last attempt)
        registry._plugin_load_errors.pop(plugin_id, None)

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
            registry._plugin_load_errors[plugin_id] = {
                "manifest": registry._plugin_manifests.get(plugin_id, {}),
                "error": "No entry script found (main.py / plugin.py / __init__.py)",
            }
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].error = "No entry script found (main.py / plugin.py / __init__.py)"
                registry._plugin_infos[plugin_id].status = "error"
            return None

        # Clear decorator-registered components so re-import starts fresh
        if plugin_id in registry._plugin_components:
            registry._plugin_components[plugin_id] = PluginComponents()

        # Remove stale module from cache so exec_module re-runs the file
        sys.modules.pop(module_name, None)

        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if not spec or not spec.loader:
            logger.warning(f"Failed to create module spec for: {plugin_root}")
            registry._plugin_load_errors[plugin_id] = {
                "manifest": registry._plugin_manifests.get(plugin_id, {}),
                "error": "Failed to create module spec",
            }
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].error = "Failed to create module spec"
                registry._plugin_infos[plugin_id].status = "error"
            return None

        if plugin_id in registry._plugin_infos:
            registry._plugin_infos[plugin_id].status = "loading"

        try:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except Exception as e:
            if auto_install and isinstance(e, ModuleNotFoundError):
                logger.info(f"ModuleNotFoundError in {plugin_root}, attempting dependency install: {e}")
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].status = "installing"
                    registry._plugin_infos[plugin_id].error = None

                warnings = await install_requirements(plugin_root, pypi_mirror=self._get_pypi_mirror())
                for w in warnings:
                    logger.warning(f"Dependency install warning for {plugin_id}: {w}")

                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].status = "loading"

                # Clean up and retry (once)
                sys.modules.pop(module_name, None)
                registry._plugin_load_errors.pop(plugin_id, None)
                try:
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                except Exception as retry_e:
                    logger.error(f"Retry after dep install also failed for {plugin_root}: {retry_e}")
                    sys.modules.pop(module_name, None)
                    registry._plugin_load_errors[plugin_id] = {
                        "manifest": registry._plugin_manifests.get(plugin_id, {}),
                        "error": f"Import error (after retry): {retry_e}",
                        "error_type": type(retry_e),
                    }
                    if plugin_id in registry._plugin_infos:
                        registry._plugin_infos[plugin_id].error = f"Import error (after retry): {retry_e}"
                        registry._plugin_infos[plugin_id].status = "error"
                    return None
            else:
                logger.error(f"Error loading plugin from {plugin_root}: {e}")
                sys.modules.pop(module_name, None)
                registry._plugin_load_errors[plugin_id] = {
                    "manifest": registry._plugin_manifests.get(plugin_id, {}),
                    "error": f"Import error: {e}",
                    "error_type": type(e),
                }
                if plugin_id in registry._plugin_infos:
                    registry._plugin_infos[plugin_id].error = f"Import error: {e}"
                    registry._plugin_infos[plugin_id].status = "error"
                return None

        registered = self._register_plugin_class(plugin_id, module, plugin_root)
        if not registered:
            logger.warning(f"No BasePlugin subclass found in {plugin_root}")
            registry._plugin_load_errors[plugin_id] = {
                "manifest": registry._plugin_manifests.get(plugin_id, {}),
                "error": "No BasePlugin subclass found",
            }
            if plugin_id in registry._plugin_infos:
                registry._plugin_infos[plugin_id].error = "No BasePlugin subclass found"
                registry._plugin_infos[plugin_id].status = "error"
            return None

        await self.init_plugin(plugin_id)
        if plugin_id in self.plugin_instances and plugin_id in registry._plugin_infos:
            registry._plugin_infos[plugin_id].status = "ready"
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
            await self.load_plugin_from_dir(plugin_root, auto_install=False)

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
