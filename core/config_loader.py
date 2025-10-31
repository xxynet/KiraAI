from typing import Dict, Any, Union
import configparser


def get_config(config_path: str) -> Dict[str, Dict[str, Any]]:
    """
    读取配置文件中的所有配置

    Args:
        config_path: 配置文件路径

    Returns:
        包含所有配置，键为配置名称，值为配置字典
    """
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    config_dict = {}

    # 获取所有的section（每个section代表一个adapter）
    for section in config.sections():
        config_section = {}

        # 获取该section下的所有配置项
        for key, value in config.items(section):
            config_section[key] = value
        config_dict[section] = config_section

    return config_dict


def get_ada_config(config_path: str = "config/adapters.ini") -> Dict[str, Dict[str, Any]]:
    """
    读取配置文件中的所有adapter配置

    Args:
        config_path: 配置文件路径

    Returns:
        包含所有adapter配置的字典，键为adapter名称，值为配置字典
    """
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')

    adapters_dict = {}

    # 获取所有的section（每个section代表一个adapter）
    for section in config.sections():
        adapter_config = {}

        # 获取该section下的所有配置项
        for key, value in config.items(section):
            adapter_config[key] = value
        adapter_config["adapter_name"] = section
        adapters_dict[section] = adapter_config

    return adapters_dict


class Config:
    def __init__(self):
        pass

    class _AdapterConfig:
        def __init__(self):
            pass


global_config = {}
global_config["ada_config"] = get_ada_config()
global_config["providers"] = get_config("config/providers.ini")
global_config["models"] = get_config("config/models.ini")
global_config["bot_config"] = get_config("config/bot.ini")
