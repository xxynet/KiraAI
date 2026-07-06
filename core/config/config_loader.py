from typing import Dict, Any, Optional
import copy
import json
import os

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
        """Load config from JSON. Raises ConfigError if file is corrupt or unreadable.
        On first launch (file missing), creates a default config file."""
        if not os.path.exists(CONFIG_PATH):
            logger.warning(f"Config file not found, creating default: {CONFIG_PATH}")
            self.update(copy.deepcopy(self.default_config))
            self.save_config()
            return

        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in config file: {e}")
            raise ConfigError(f"invalid JSON in config file: {e}") from e
        except OSError as e:
            logger.error(f"Cannot read config file: {e}")
            raise ConfigError(f"cannot read config file: {e}") from e

        if not isinstance(data, dict):
            logger.error(f"Config file root must be a JSON object, got {type(data).__name__}")
            raise ConfigError(f"config file root must be a JSON object, got {type(data).__name__}")

        self.update(copy.deepcopy(self.default_config))
        self._deep_update(self, data)
        # Only persist when merging defaults actually changed the config (e.g.
        # newly-added default keys). An unchanged config must not be rewritten
        # on every boot.
        if dict(self) != data:
            self.save_config()

    def _deep_update(self, target: dict, source: dict):
        """Recursively update target dict with source dict"""
        for key, value in source.items():
            if key in target and isinstance(target[key], dict) and isinstance(value, dict):
                self._deep_update(target[key], value)
            else:
                target[key] = value

    def save_config(self):
        """Save current config to JSON file"""
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                f.write(json.dumps(self, indent=4, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to save config to JSON: {e}")

    def get_config(self, key: str, default: Optional = None, splitter: str = "."):
        keys = key.split(splitter)
        v = self
        for k in keys:
            if isinstance(v, dict) and k in v:
                v = v[k]
            else:
                return default
        return v

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
