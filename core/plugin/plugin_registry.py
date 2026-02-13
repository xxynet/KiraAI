import asyncio
import importlib
import importlib.util
import inspect
import os
import json
import sys
import types
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable, Union, Awaitable
from core.utils.path_utils import get_data_path, get_config_path
from core.logging_manager import get_logger
from core.config.config_field import BaseConfigField, build_fields
from .plugin import BasePlugin
from .plugin_context import PluginContext
from .plugin_handlers import Priority, event_handler_reg, EventHandler, EventType

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
_plugin_components: Dict[str, dict] = {}


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


def register_tool(name: str, description: str, params: dict):
    def decorator(func: Callable):
        plugin_id = get_obj_plugin_id(func)
        plugin_entry = _plugin_components.setdefault(plugin_id, {})
        tools = plugin_entry.setdefault("tools", {})
        tool_funcs = plugin_entry.setdefault("tool_funcs", {})
        tools[name] = {
            "name": name,
            "description": description,
            "parameters": params,
            "func": func,
        }
        tool_funcs[name] = func

        return func

    return decorator


def on_im_message(priority: Union[Priority, int] = Priority.MEDIUM):
    def decorator(func: Callable):
        plugin_id = get_obj_plugin_id(func)
        eh = EventHandler(
            EventType.IMMessage,
            priority=priority,
            handler=func,
            desc=func.__doc__
        )

        plugin_entry = _plugin_components.setdefault(plugin_id, {})
        hooks = plugin_entry.setdefault("hooks", [])
        hooks.append(eh)
        return func

    return decorator


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

        self._load_plugin_state()

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
            await self.init_plugin(plugin_id)
        elif not enabled and previous:
            try:
                await self.terminate(plugin_id)
            except Exception as e:
                logger.error(f"Failed to terminate plugin {plugin_id} when disabling: {e}")

    def get_registered_plugins(self) -> Dict[str, type[BasePlugin]]:
        return dict(_plugin_classes)

    def get_plugin_manifest(self, name: str) -> Dict[str, Any]:
        return _plugin_manifests.get(name, {})

    def get_plugin_module_dir(self, name: str) -> str:
        return _plugin_module_dirs.get(name, "")

    def get_plugin_module_path(self, name: str) -> Optional[Path]:
        return _plugin_module_paths.get(name)

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

    def get_plugin_components(self) -> Dict[str, dict]:
        return dict(_plugin_components)

    def get_plugin_tools(self, plugin_name: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
        if plugin_name is None:
            return {name: comp.get("tools", {}) for name, comp in _plugin_components.items()}
        entry = _plugin_components.get(plugin_name, {})
        return entry.get("tools", {})

    def _register_plugin_tools_for(self, plugin_id: str) -> None:
        comp = _plugin_components.get(plugin_id, {})
        if not comp:
            return
        tools = comp.get("tools", {})
        tool_funcs = comp.get("tool_funcs", {})
        plugin_instance = self.plugin_instances.get(plugin_id)
        tool_names: list[str] = []
        for tool_name, meta in tools.items():
            func = tool_funcs.get(tool_name)
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
        comp = _plugin_components.get(plugin_id, {})
        if not comp:
            return
        hooks = comp.get("hooks", [])
        plugin_instance = self.plugin_instances.get(plugin_id)
        for hook in hooks:
            bound_handler = hook.handler
            if plugin_instance is not None and bound_handler is not None and hasattr(
                plugin_instance, bound_handler.__name__
            ):
                candidate = getattr(plugin_instance, bound_handler.__name__)
                if candidate is not None:
                    bound_handler = candidate
            hook.handler = bound_handler
            event_handler_reg.register(hook)
        if hooks:
            logger.info(f"Registered {len(hooks)} hooks from {plugin_id}")

    def register_plugin_tools(self) -> None:
        for plugin_id in _plugin_components.keys():
            self._register_plugin_tools_for(plugin_id)

    def _cleanup_plugin_registration(self, plugin_id: str) -> None:
        comp = _plugin_components.get(plugin_id)
        if not comp:
            return

        # clean up tool registration
        tools = comp.get("tools", {})
        if self.ctx and getattr(self.ctx, "llm_api", None):
            for tool_name in list(tools.keys()):
                try:
                    self.ctx.llm_api.unregister_tool(tool_name)
                except Exception as e:
                    logger.error(f"Failed to unregister tool {tool_name} for plugin {plugin_id}: {e}")

        # clean up hook registration
        hooks = comp.get("hooks", [])
        for hook in hooks:
            event_handler_reg.del_handler(hook)

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
            if isinstance(field, BaseConfigField) and field.key not in cfg:
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
            logger.info(f"Plugin {plugin_id} is disabled, skipping initialization")
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

    async def reload(self, plugin_id: Optional[str]):
        """
        Reload all plugins or reload a specific plugin
        """
        if plugin_id:
            logger.info(f"Reloading plugin {plugin_id}...")
            await self.init_plugin(plugin_id)
            return

        logger.info("Reloading all plugins...")
        await self.terminate()
        await self.init()

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

        if manifest:
            _plugin_manifests[plugin_id] = manifest

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
                continue

            self._register_plugin_class(plugin_id, module, plugin_dir)

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

            plugin_id = self._load_plugin_meta(plugin_root, entry)

            package_name = f"{base_package}.{entry}"
            if package_name not in sys.modules:
                sub_pkg = types.ModuleType(package_name)
                sub_pkg.__path__ = [str(plugin_root)]
                sys.modules[package_name] = sub_pkg

            script_path = None
            module_name = None
            main_path = plugin_root / "main.py"
            plugin_path = plugin_root / "plugin.py"
            init_path = plugin_root / "__init__.py"

            if main_path.exists():
                script_path = main_path
                module_name = f"{package_name}.main"
            elif plugin_path.exists():
                script_path = plugin_path
                module_name = f"{package_name}.plugin"
            elif init_path.exists():
                script_path = init_path
                module_name = package_name

            if not script_path or not module_name:
                continue

            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if not spec or not spec.loader:
                logger.warning(f"Failed to create spec for plugin module in {plugin_root}")
                continue

            try:
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"Error loading plugin from {plugin_root}: {e}")
                continue

            self._register_plugin_class(plugin_id, module, plugin_root)
