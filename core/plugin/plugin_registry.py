import asyncio
import importlib
import importlib.util
import inspect
import os
import json
import sys
import types
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
from core.utils.path_utils import get_data_path, get_config_path
from core.logging_manager import get_logger
from core.config.config_field import BaseConfigField, build_fields
from .plugin import BasePlugin
from .plugin_context import PluginContext
from core.event_bus import EventBus, EventType

logger = get_logger("plugin_manager", "cyan")

PLUGINS_DIR = get_data_path() / "plugins"
PLUGIN_DATA_DIR = get_data_path() / "plugin_data"
PLUGIN_CONFIG_DIR = get_config_path() / "plugins"
BUILTIN_PLUGINS_DIR = Path(__file__).parent / "builtin_plugins"

_plugin_classes: Dict[str, type[BasePlugin]] = {}
_plugin_manifests: Dict[str, Dict[str, Any]] = {}
_plugin_module_dirs: Dict[str, str] = {}
_plugin_module_paths: Dict[str, Path] = {}
_module_to_plugin: Dict[str, str] = {}
_plugin_schemas: Dict[str, List[BaseConfigField]] = {}


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

    def get_registered_plugins(self) -> Dict[str, type[BasePlugin]]:
        return dict(_plugin_classes)

    def get_plugin_manifest(self, name: str) -> Dict[str, Any]:
        return _plugin_manifests.get(name, {})

    def get_plugin_module_dir(self, name: str) -> str:
        return _plugin_module_dirs.get(name, "")

    def get_plugin_module_path(self, name: str) -> Optional[Path]:
        return _plugin_module_paths.get(name)

    def get_plugin_name_for_module(self, module_name: str) -> Optional[str]:
        return _module_to_plugin.get(module_name)

    def get_plugin_schema(self, name: str) -> List[BaseConfigField]:
        return _plugin_schemas.get(name, [])

    def _ensure_plugin_config(self, plugin_name: str, schema_fields: List[BaseConfigField]) -> None:
        if not schema_fields:
            return
        PLUGIN_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        config_path = PLUGIN_CONFIG_DIR / f"{plugin_name}.json"
        cfg: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with config_path.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    cfg = loaded
            except Exception as e:
                logger.error(f"Failed to load plugin config from {config_path}: {e}")
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

        for plugin_name, plugin_cls in _plugin_classes.items():
            if plugin_name in self.plugin_instances:
                continue
            cfg = self.plugin_configs.get(plugin_name) or {}
            try:
                instance = plugin_cls(self.ctx, cfg)
            except Exception as e:
                logger.error(f"Failed to instantiate plugin {plugin_name}: {e}")
                continue
            self.plugin_instances[plugin_name] = instance
            try:
                await instance.initialize()
            except Exception as e:
                logger.error(f"Failed to initialize plugin {plugin_name}: {e}")

    async def reload(self):
        """
        Reload all plugins by terminating existing ones and reinitializing
        """
        logger.info("Reloading all plugins...")
        
        # Terminate all existing plugins
        for plugin_name, plugin_instance in self.plugin_instances.items():
            try:
                await plugin_instance.terminate()
            except Exception as e:
                logger.error(f"Error terminating plugin {plugin_name}: {e}")

        # Clear registries
        self.plugin_instances.clear()
        self.plugin_configs.clear()

        # Reinitialize
        await self.init()

    async def _discover_builtin_plugins(self):
        if not BUILTIN_PLUGINS_DIR.exists():
            return

        for entry in os.listdir(BUILTIN_PLUGINS_DIR):
            if entry.startswith("_"):
                continue
            plugin_dir = BUILTIN_PLUGINS_DIR / entry
            if not plugin_dir.is_dir():
                continue

            manifest_path = plugin_dir / "manifest.json"
            schema_path = plugin_dir / "schema.json"

            manifest: Dict[str, Any] = {}
            if manifest_path.exists():
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load manifest for builtin plugin {entry}: {e}")
            plugin_name = manifest.get("name") or entry
            if manifest:
                _plugin_manifests[plugin_name] = manifest

            schema_fields: List[BaseConfigField] = []
            if schema_path.exists():
                try:
                    with schema_path.open("r", encoding="utf-8") as f:
                        raw_schema = json.load(f)
                    if isinstance(raw_schema, dict):
                        schema_fields = build_fields(raw_schema)
                except Exception as e:
                    logger.warning(f"Failed to load schema for builtin plugin {plugin_name}: {e}")
            if schema_fields:
                _plugin_schemas[plugin_name] = schema_fields
                self._ensure_plugin_config(plugin_name, schema_fields)

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

            for attr_name, attr_value in inspect.getmembers(module, inspect.isclass):
                if issubclass(attr_value, BasePlugin) and attr_value is not BasePlugin:
                    _plugin_classes[plugin_name] = attr_value
                    module_file = Path(getattr(module, "__file__", plugin_dir / "__init__.py")).resolve()
                    module_dir = module_file.parent
                    _plugin_module_dirs[plugin_name] = module_dir.name
                    _plugin_module_paths[plugin_name] = module_dir
                    _module_to_plugin[module.__name__] = plugin_name
                    break

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

            manifest_path = plugin_root / "manifest.json"
            schema_path = plugin_root / "schema.json"

            manifest: Dict[str, Any] = {}
            if manifest_path.exists():
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load manifest for plugin {entry}: {e}")
            plugin_name = manifest.get("name") or entry
            if manifest:
                _plugin_manifests[plugin_name] = manifest

            schema_fields: List[BaseConfigField] = []
            if schema_path.exists():
                try:
                    with schema_path.open("r", encoding="utf-8") as f:
                        raw_schema = json.load(f)
                    if isinstance(raw_schema, dict):
                        schema_fields = build_fields(raw_schema)
                except Exception as e:
                    logger.warning(f"Failed to load schema for plugin {plugin_name}: {e}")
            if schema_fields:
                _plugin_schemas[plugin_name] = schema_fields
                self._ensure_plugin_config(plugin_name, schema_fields)

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

            for attr_name, attr_value in inspect.getmembers(module, inspect.isclass):
                if issubclass(attr_value, BasePlugin) and attr_value is not BasePlugin:
                    _plugin_classes[plugin_name] = attr_value
                    module_file = Path(getattr(module, "__file__", script_path)).resolve()
                    module_dir = module_file.parent
                    _plugin_module_dirs[plugin_name] = module_dir.name
                    _plugin_module_paths[plugin_name] = module_dir
                    _module_to_plugin[module.__name__] = plugin_name
                    break
