from typing import Dict, Any, Optional
import configparser
import os


class ConfigError(Exception):
    def __init__(self, message: str = "failed to load KiraAI config"):
        super().__init__(f"ConfigError: {message}")


class KiraConfig(dict):
    def __init__(self, default_config: Optional[dict] = None):
        super().__init__()
        object.__setattr__(self, "default_config", default_config)

        self["bot_config"] = self.load_from_ini("data/config/bot.ini")
        self["providers"] = self.load_from_ini("data/config/providers.ini")
        self["models"] = self.load_from_ini("data/config/models.ini")
        self["ada_config"] = self.load_from_ini("data/config/adapters.ini", "adapter_name")

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
            print(str(e))
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
