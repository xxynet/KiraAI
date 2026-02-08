import asyncio
import json
import os
import importlib.util
import inspect
import uuid
import sys
import types
from typing import Union, Optional, Dict, Type

from core.logging_manager import get_logger
from core.config import KiraConfig
from core.config.config_field import BaseConfigField, build_fields
from .adapter_info import AdapterInfo
from .adapter_utils import IMAdapter, SocialMediaAdapter


logger = get_logger("adapter", "blue")


class AdapterManager:
    _registry: Dict[str, Type[Union[IMAdapter, SocialMediaAdapter]]] = {}
    _manifests: Dict[str, dict] = {}
    _schemas: Dict[str, list[BaseConfigField]] = {}

    def __init__(self, kira_config: KiraConfig, loop: asyncio.AbstractEventLoop, event_queue: asyncio.Queue, llm_api):
        self.kira_config = kira_config
        self._adapters: dict[str, Union[IMAdapter, SocialMediaAdapter]] = {}
        self.adas_config: dict = kira_config.get("adapters", {}) or {}
        self.loop = loop
        self.event_queue = event_queue
        self.llm_api = llm_api

        src_dir = os.path.join(os.path.dirname(__file__), "src")
        self.scan_adapters(src_dir)

    @classmethod
    def get_adapter_class(cls, platform: str) -> Optional[Type[Union[IMAdapter, SocialMediaAdapter]]]:
        return cls._registry.get(platform)

    @classmethod
    def get_adapter_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def get_schema(cls, platform: str) -> list[BaseConfigField]:
        return cls._schemas.get(platform, [])

    def get_adapter_info(self, adapter_id: str) -> Optional[AdapterInfo]:
        adapters_config = self.kira_config.get("adapters", {})
        config_entry = adapters_config.get(adapter_id)
        if not isinstance(config_entry, dict):
            return None

        enabled = bool(config_entry.get("enabled", False))
        name = (
            config_entry.get("name")
            or adapter_id
        )
        platform = config_entry.get("platform") or ""
        description = config_entry.get("desc") or ""
        config = config_entry.get("config") or {}

        return AdapterInfo(
            adapter_id=adapter_id,
            enabled=enabled,
            name=name,
            platform=platform,
            description=description,
            config=config,
        )

    def get_adapter_infos(self) -> list[AdapterInfo]:
        adapters_config = self.kira_config.get("adapters", {})
        if not isinstance(adapters_config, dict):
            return []

        infos: list[AdapterInfo] = []
        for adapter_id, config_entry in adapters_config.items():
            if not isinstance(config_entry, dict):
                continue

            enabled = bool(config_entry.get("enabled", False))
            name = config_entry.get("name") or adapter_id
            platform = config_entry.get("platform") or ""
            description = config_entry.get("desc") or ""
            config = config_entry.get("config") or {}

            infos.append(
                AdapterInfo(
                    adapter_id=adapter_id,
                    enabled=enabled,
                    name=name,
                    platform=platform,
                    description=description,
                    config=config,
                )
            )

        return infos

    @classmethod
    def scan_adapters(cls, src_dir: str):
        if not os.path.exists(src_dir):
            logger.error(f"Adapter source directory not found: {src_dir}")
            return

        base_package = "core.adapter.src"
        if base_package not in sys.modules:
            pkg = types.ModuleType(base_package)
            pkg.__path__ = [src_dir]
            sys.modules[base_package] = pkg

        for entry in os.listdir(src_dir):
            if entry.startswith("__"):
                continue

            adapter_dir = os.path.join(src_dir, entry)
            if not os.path.isdir(adapter_dir):
                continue

            manifest = {}
            manifest_path = os.path.join(adapter_dir, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception as e:
                    logger.warning(f"Failed to load manifest from {manifest_path}: {e}")

            platform_name = manifest.get("name") if isinstance(manifest, dict) else None

            schema_fields: list[BaseConfigField] = []
            schema_path = os.path.join(adapter_dir, "schema.json")
            if os.path.exists(schema_path):
                try:
                    with open(schema_path, "r", encoding="utf-8") as f:
                        raw_schema = json.load(f)
                    if isinstance(raw_schema, dict):
                        schema_fields = build_fields(raw_schema)
                except Exception as e:
                    logger.warning(f"Failed to load schema for {platform_name}: {e}")

            script_path = None
            candidates = [
                os.path.join(adapter_dir, f"{entry}.py"),
                os.path.join(adapter_dir, "adapter.py"),
                os.path.join(adapter_dir, "__init__.py"),
            ]
            for candidate in candidates:
                if os.path.exists(candidate):
                    script_path = candidate
                    break

            if not script_path:
                logger.warning(f"No adapter module found in {adapter_dir}")
                continue

            package_name = f"{base_package}.{entry}"
            if package_name not in sys.modules:
                sub_pkg = types.ModuleType(package_name)
                sub_pkg.__path__ = [adapter_dir]
                sys.modules[package_name] = sub_pkg

            module_name = f"{package_name}.{entry}"
            spec = importlib.util.spec_from_file_location(module_name, script_path)
            if not spec or not spec.loader:
                logger.warning(f"Failed to create spec for adapter module in {adapter_dir}")
                continue

            try:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception as e:
                logger.error(f"Error loading adapter from {adapter_dir}: {e}")
                continue

            found = False
            for attr_name, attr_value in inspect.getmembers(module):
                if inspect.isclass(attr_value) and issubclass(attr_value, (IMAdapter, SocialMediaAdapter)) and attr_value not in (IMAdapter, SocialMediaAdapter):
                    cls._registry[platform_name] = attr_value
                    cls._manifests[platform_name] = manifest
                    cls._schemas[platform_name] = schema_fields
                    logger.info(f"Registered adapter: {platform_name}")
                    found = True
                    break

            if not found:
                logger.warning(f"No adapter class found in {adapter_dir}")

    async def initialize(self):
        for adapter_id in self.adas_config.keys():
            info = self.get_adapter_info(adapter_id)
            if not info:
                continue
            try:
                await self.register_adapter(info)
            except Exception as e:
                logger.error(f"Failed to register adapter {adapter_id}: {e}")
        from core.services.runtime import set_adapters
        set_adapters(self._adapters)
        logger.info(f"Adapters set: {list(self._adapters.keys())}")

    def generate_adapter_config(self, platform: str, name: str) -> Optional[str]:
        schema_fields = self.get_schema(platform)
        if not schema_fields:
            logger.error(f"No schema found for adapter platform: {platform}")
            return None

        adapter_id = uuid.uuid4().hex[:12]
        config_fields: Dict[str, object] = {}
        for field in schema_fields:
            if isinstance(field, BaseConfigField):
                config_fields[field.key] = field.default

        adapters_root = self.kira_config.get("adapters", {}) or {}
        adapters_root[adapter_id] = {
            "enabled": False,
            "name": name,
            "platform": platform,
            "desc": "",
            "config": config_fields,
        }
        self.kira_config["adapters"] = adapters_root
        try:
            self.kira_config.save_config()
        except Exception as e:
            logger.error(f"Failed to save generated adapter config for {platform}: {e}")
            return None

        self.adas_config = self.kira_config.get("adapters", {}) or {}
        logger.info(f"Generated adapter config for {name} ({platform})")
        return adapter_id

    async def create_adapter(
        self,
        name: str,
        platform: str,
        status: str,
        description: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Optional[AdapterInfo]:
        if not name or not platform:
            logger.error("Adapter name and platform are required for creation")
            return None

        adapter_id = self.generate_adapter_config(platform, name)
        if not adapter_id:
            return None

        adapters_config = self.kira_config.get("adapters", {}) or {}
        config_entry = adapters_config.get(adapter_id)
        if not isinstance(config_entry, dict):
            logger.error(f"Adapter config not found after generation for {adapter_id}")
            return None

        if config:
            entry_config = config_entry.get("config") or {}
            entry_config.update(config)
            config_entry["config"] = entry_config

        config_entry["name"] = name
        if description is not None:
            config_entry["desc"] = description

        enabled = status == "active"
        config_entry["enabled"] = enabled

        adapters_config[adapter_id] = config_entry
        self.kira_config["adapters"] = adapters_config
        try:
            self.kira_config.save_config()
        except Exception as e:
            logger.error(f"Failed to save adapter config for {adapter_id}: {e}")
            return None

        self.adas_config = adapters_config

        if enabled:
            try:
                info = self.get_adapter_info(adapter_id)
                if info:
                    await self.register_adapter(info)
            except Exception as e:
                logger.error(f"Failed to start adapter {adapter_id} after creation: {e}")

        info = self.get_adapter_info(adapter_id)
        if not info:
            logger.error(f"Failed to read adapter info after creating {adapter_id}")
            return None
        return info

    async def update_adapter(
        self,
        adapter_id: str,
        name: Optional[str] = None,
        platform: Optional[str] = None,
        status: Optional[str] = None,
        description: Optional[str] = None,
        config: Optional[dict] = None,
    ) -> Optional[AdapterInfo]:
        adapters_config = self.kira_config.get("adapters", {}) or {}
        config_entry = adapters_config.get(adapter_id)
        if not isinstance(config_entry, dict):
            return None

        old_enabled = bool(config_entry.get("enabled", False))

        if name:
            config_entry["name"] = name
        if platform:
            config_entry["platform"] = platform
        if description is not None:
            config_entry["desc"] = description
        if config:
            entry_config = config_entry.get("config") or {}
            entry_config.update(config)
            config_entry["config"] = entry_config

        if status:
            config_entry["enabled"] = status == "active"

        adapters_config[adapter_id] = config_entry
        self.kira_config["adapters"] = adapters_config
        try:
            self.kira_config.save_config()
        except Exception as e:
            logger.error(f"Failed to save adapter config for {adapter_id} on update: {e}")
            return None

        self.adas_config = adapters_config

        new_enabled = bool(config_entry.get("enabled", False))
        name_for_runtime = config_entry.get("name") or adapter_id

        if new_enabled and not old_enabled:
            try:
                info = self.get_adapter_info(adapter_id)
                if info:
                    await self.register_adapter(info)
            except Exception as e:
                logger.error(f"Failed to start adapter {adapter_id} after update: {e}")

        if old_enabled and not new_enabled:
            try:
                await self.stop_adapter(name_for_runtime)
            except Exception as e:
                logger.error(f"Failed to stop adapter {adapter_id} after update: {e}")

        info = self.get_adapter_info(adapter_id)
        if not info:
            logger.error(f"Failed to read adapter info after updating {adapter_id}")
            return None
        logger.info(f"Adapter configuration saved for {name_for_runtime}")
        return info

    async def register_adapter(self, info: AdapterInfo):
        platform = info.platform
        name = info.name or info.adapter_id
        if not platform:
            logger.error(f"Adapter {name} has no platform configured")
            return

        adapter_cls = self.get_adapter_class(platform)
        if not adapter_cls:
            logger.error(f"No adapter registered for platform {platform}")
            return

        if not info.enabled:
            return

        try:
            if issubclass(adapter_cls, IMAdapter):
                instance = adapter_cls(info, self.loop, self.event_queue, self.llm_api)
            elif issubclass(adapter_cls, SocialMediaAdapter):
                instance = adapter_cls(info, self.loop, self.event_queue)
            else:
                logger.error(f"Adapter class for platform {platform} is not a valid adapter type")
                return
        except Exception as e:
            logger.error(f"Failed to instantiate adapter {name}: {e}")
            return

        self._adapters[name] = instance
        from core.services.runtime import set_adapters
        set_adapters(self._adapters)
        await self.start_adapter(name)

    async def start_adapter(self, name):
        """start an adapter by specified adapter name"""
        try:
            task = asyncio.create_task(self._adapters[name].start())
            task.add_done_callback(lambda t: logger.info(f"Started adapter {name}"))
        except Exception as e:
            logger.error(f"Failed to start adapter {name}: {e}")

    async def stop_adapter(self, name: str):
        """stop an adapter by specified adapter name"""
        adapter = self._adapters.get(name)
        if adapter:
            await adapter.stop()
            self._adapters.pop(name, None)
            logger.info(f"Stopped adapter {name}")
            from core.services.runtime import set_adapters
            set_adapters(self._adapters)

    async def delete_adapter(self, adapter_id: str) -> bool:
        adapters_config = self.kira_config.get("adapters", {}) or {}
        config_entry = adapters_config.get(adapter_id)
        if not isinstance(config_entry, dict):
            return False

        entry_config = config_entry.get("config") or {}
        name_value = config_entry.get("name") or adapter_id

        if name_value in self._adapters:
            try:
                await self._adapters[name_value].stop()
            except Exception as e:
                logger.error(f"Failed to stop adapter {adapter_id} before deletion: {e}")
            self._adapters.pop(name_value, None)
            from core.services.runtime import set_adapters
            set_adapters(self._adapters)

        del adapters_config[adapter_id]
        self.kira_config["adapters"] = adapters_config
        try:
            self.kira_config.save_config()
        except Exception as e:
            logger.error(f"Failed to save config after deleting adapter {adapter_id}: {e}")
            return False

        self.adas_config = adapters_config
        logger.info(f"Deleted adapter: {name_value}")
        return True

    async def stop_adapters(self):
        """stop all running adapters"""
        for ada in self._adapters:
            await self._adapters[ada].stop()
        from core.services.runtime import set_adapters
        set_adapters(self._adapters)

    def get_adapters(self) -> dict[str, Union[IMAdapter, SocialMediaAdapter]]:
        """return the entire dict where adapters are registered"""
        return self._adapters

    def get_adapter(self, name: str) -> Union[IMAdapter, SocialMediaAdapter]:
        """get an adapter instance by specified adapter name"""
        return self._adapters.get(name)
