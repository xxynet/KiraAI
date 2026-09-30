"""Shared plugin registration state and plugin ownership resolution."""

import inspect
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from core.config.config_field import BaseConfigField
from .base import BasePlugin
from .components import PluginComponents
from .metadata import PluginInfo


_plugin_classes: Dict[str, type[BasePlugin]] = {}
_plugin_manifests: Dict[str, Dict[str, Any]] = {}
_plugin_module_dirs: Dict[str, str] = {}
_plugin_module_paths: Dict[str, Path] = {}

"""key: module name, value: plugin id"""
_module_to_plugin: Dict[str, str] = {}
_plugin_schemas: Dict[str, List[BaseConfigField]] = {}


_plugin_components: Dict[str, PluginComponents] = {}


def _ensure_components(plugin_id: str) -> PluginComponents:
    return _plugin_components.setdefault(plugin_id, PluginComponents())

"""Plugins that failed to load: {plugin_id: {"manifest": {...}, "error": "..."}}"""
_plugin_load_errors: Dict[str, Dict[str, Any]] = {}

"""Discovered plugin metadata: {plugin_id: PluginInfo}"""
_plugin_infos: Dict[str, PluginInfo] = {}


def get_obj_plugin_id(obj: Any):
    # 1. Try the module where obj is defined (works for functions/classes)
    module = inspect.getmodule(obj)
    module_name = module.__name__ if module else ""
    plugin_id = _module_to_plugin.get(module_name, "")

    # 2. Try manifest.json next to the module file
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

    # 3. Walk the call stack to find the caller's module.
    #    Needed when obj is an instance of a framework class (e.g. PluginPage)
    #    whose __module__ points to the framework, not the plugin.
    if not plugin_id:
        for depth in range(1, 10):
            frame = inspect.currentframe()
            for _ in range(depth):
                if frame is None:
                    break
                frame = frame.f_back
            if frame is None:
                break
            caller_module = inspect.getmodule(frame)
            if caller_module is None:
                continue
            caller_name = caller_module.__name__
            if caller_name in _module_to_plugin:
                plugin_id = _module_to_plugin[caller_name]
                break
            if getattr(caller_module, "__file__", None) and caller_module is not sys.modules[__name__]:
                caller_path = Path(caller_module.__file__).resolve()
                caller_root = caller_path.parent
                manifest_path = caller_root / "manifest.json"
                if manifest_path.exists():
                    try:
                        with manifest_path.open("r", encoding="utf-8") as f:
                            manifest = json.load(f)
                        plugin_id = manifest.get("plugin_id") or caller_root.name
                        _plugin_manifests.setdefault(plugin_id, manifest)
                        _plugin_module_dirs.setdefault(plugin_id, caller_root.name)
                        _plugin_module_paths.setdefault(plugin_id, caller_root)
                        _module_to_plugin[caller_name] = plugin_id
                        break
                    except Exception:
                        pass

    return plugin_id
