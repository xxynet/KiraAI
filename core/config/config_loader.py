from typing import Dict, Any, Optional
import configparser
import json
import os
import uuid

from core.utils.path_utils import get_config_path
from core.logging_manager import get_logger

from .default import DEFAULT_CONFIG

logger = get_logger("config", "green")

CONFIG_PATH = get_config_path() / "system_config.json"


class ConfigError(Exception):
    def __init__(self, message: str = "failed to load KiraAI config"):
        super().__init__(f"ConfigError: {message}")


class KiraConfig(dict):
    def __init__(self, default_config: Optional[dict] = None):
        super().__init__()
        object.__setattr__(self, "default_config", default_config or DEFAULT_CONFIG)

        self._load_config()

    def _load_config(self):
        """Load config from JSON or migrate from INI"""
        if os.path.exists(CONFIG_PATH):
            self.load_from_json()
        elif self._check_ini_files_exist():
            self.migrate_from_ini()
        else:
            self.load_defaults()

    @staticmethod
    def _check_ini_files_exist() -> bool:
        return any(os.path.exists(os.path.join("data", "config", f)) 
                   for f in ["bot.ini", "adapters.ini"])

    def migrate_from_ini(self):
        """Migrate existing INI files to JSON"""
        logger.info("Migrating configuration from INI to JSON...")
        
        # Load from INI files
        bot_config = self.load_from_ini("data/config/bot.ini")
        ada_config = self.load_from_ini("data/config/adapters.ini", "adapter_name")
        
        # Construct full config structure
        full_config = self.default_config
        full_config["bot_config"] = bot_config
        full_config["adapters"] = ada_config
        
        # Save to JSON
        self.save_to_json(full_config)

        self.update(full_config)
        
        self._migrate_adapters_config()

    def load_defaults(self):
        """Load default configuration"""
        full_config = self.default_config
        self.save_to_json(full_config)
        self.update(full_config)
        self._migrate_adapters_config()

    def load_from_json(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.update(data)
            self._migrate_adapters_config()
        except Exception as e:
            logger.error(f"Error loading JSON config: {e}")

    def save_config(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(json.dumps(self, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to save config to JSON: {e}")

    def save_to_json(self, data: dict):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(json.dumps(data, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to save config to JSON: {e}")

    def get_config(self, key: str, default: Optional = None):
        keys = key.split(".")
        v = self
        for k in keys:
            if isinstance(v, dict) and k in v:
                v = v[k]
            else:
                return default
        return v

    def _migrate_adapters_config(self):
        adapters = self.get("adapters")
        if not isinstance(adapters, dict):
            self["adapters"] = {}
            if "ada_config" in self:
                del self["ada_config"]
            return

        new_adapters: dict = {}

        sample_value = next(iter(adapters.values()), None)
        if sample_value and "config" in sample_value:
            for adapter_id, adapter_entry in adapters.items():
                enabled = adapter_entry.get("enabled", False)
                platform = adapter_entry.get("platform")
                desc = adapter_entry.get("desc", "")
                config = adapter_entry.get("config") or {}
                name = adapter_entry.get("name") or config.get("adapter_name") or adapter_id
                cleaned_config = dict(config)
                cleaned_config.pop("adapter_name", None)

                new_adapters[adapter_id] = {
                    "enabled": bool(enabled),
                    "name": name,
                    "platform": platform,
                    "desc": desc,
                    "config": cleaned_config,
                }
        else:
            for old_name, cfg in adapters.items():
                adapter_id = uuid.uuid4().hex[:12]
                enabled_raw = cfg.get("enabled")
                enabled_flag = False
                if isinstance(enabled_raw, bool):
                    enabled_flag = enabled_raw
                elif isinstance(enabled_raw, str):
                    enabled_flag = enabled_raw.lower() == "true"

                platform = cfg.get("platform")
                desc = cfg.get("desc", "")
                config_fields = dict(cfg)
                for key in ["enabled", "platform", "desc"]:
                    config_fields.pop(key, None)
                name = config_fields.get("adapter_name") or old_name
                config_fields.pop("adapter_name", None)

                new_adapters[adapter_id] = {
                    "enabled": enabled_flag,
                    "name": name,
                    "platform": platform,
                    "desc": desc,
                    "config": config_fields,
                }

            self["adapters"] = new_adapters
            try:
                self.save_config()
            except Exception as e:
                logger.error(f"Failed to save migrated adapter config: {e}")

        self["adapters"] = new_adapters

        if "ada_config" in self:
            del self["ada_config"]

    @staticmethod
    def _load_from_ini(config_path: str, section_name: Optional[str] = None):
        """

        :param config_path: ini file path
        :param section_name: if set, the section name will be included in the dict under the key 'section_name'
        :return: config dict
        """
        if not os.path.exists(config_path):
            raise ConfigError(f"Config file does not exist: {config_path}")

        config = configparser.RawConfigParser()
        try:
            config.read(config_path, encoding='utf-8')
        except configparser.ParsingError as e:
            raise ConfigError(str(e))

        _config_dict = {}

        # get all sections
        for section in config.sections():
            config_section = {}

            # get configuration beneath the section
            for key, value in config.items(section):
                config_section[key] = value
            if section_name:
                config_section[section_name] = section
            _config_dict[section] = config_section

        if not _config_dict:
            raise ConfigError(f"Configuration file is empty in: {config_path}")

        return _config_dict

    def load_from_ini(self, config_path: str, section_name: Optional[str] = None):
        try:
            return self._load_from_ini(config_path, section_name)
        except ConfigError as e:
            logger.error(f"Failed to load from ini: {e}")
            return {}

    def __setattr__(self, key: str, value: Any) -> None:
        """set an attribute"""
        self[key] = value

    def __getattr__(self, key: str) -> Any:
        """get an attribute，raise AttributeError if not exists"""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")

    def __delattr__(self, key: str) -> None:
        """delete an attribute"""
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{key}'")
