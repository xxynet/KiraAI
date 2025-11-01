from typing import Dict, Any, Optional
import configparser
import os
from pathlib import Path


class ConfigError(Exception):
    """配置加载错误"""
    pass


def get_config(config_path: str) -> Dict[str, Dict[str, Any]]:
    """
    读取配置文件中的所有配置

    Args:
        config_path: 配置文件路径

    Returns:
        包含所有配置，键为配置名称，值为配置字典
        
    Raises:
        ConfigError: 配置文件不存在或读取失败
    """
    if not os.path.exists(config_path):
        raise ConfigError(f"配置文件不存在: {config_path}")
    
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

    if not config_dict:
        raise ConfigError(f"配置文件为空或格式错误: {config_path}")
    
    return config_dict


def get_ada_config(config_path: str = "config/adapters.ini") -> Dict[str, Dict[str, Any]]:
    """
    读取配置文件中的所有adapter配置

    Args:
        config_path: 配置文件路径

    Returns:
        包含所有adapter配置的字典，键为adapter名称，值为配置字典
        
    Raises:
        ConfigError: 配置文件不存在或读取失败
    """
    if not os.path.exists(config_path):
        raise ConfigError(f"配置文件不存在: {config_path}")
    
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

    if not adapters_dict:
        raise ConfigError(f"未找到任何适配器配置: {config_path}")
    
    return adapters_dict


# class Config:
#     """配置管理器，统一加载和管理所有配置"""
#
#     def __init__(self, config_dir: str = "config"):
#         """
#         初始化配置管理器
#
#         Args:
#             config_dir: 配置文件目录
#
#         Raises:
#             ConfigError: 配置加载失败
#         """
#         self.config_dir = Path(config_dir)
#
#         # 加载各项配置
#         try:
#             self._load_configs()
#             self._validate_configs()
#         except Exception as e:
#             raise ConfigError(f"配置加载失败: {e}") from e
#
#     def _load_configs(self):
#         """加载所有配置文件"""
#         # Adapter配置
#         ada_config_path = self.config_dir / "adapters.ini"
#         self.adapter_config = self._AdapterConfig(get_ada_config(str(ada_config_path)))
#
#         # Bot配置
#         bot_config_path = self.config_dir / "bot.ini"
#         bot_raw_config = get_config(str(bot_config_path))
#         self.bot_config = self._BotConfig(bot_raw_config)
#
#         # Provider配置
#         provider_config_path = self.config_dir / "providers.ini"
#         self.provider_config_raw = get_config(str(provider_config_path))
#
#         # Model配置
#         model_config_path = self.config_dir / "models.ini"
#         model_raw_config = get_config(str(model_config_path))
#         self.model_config = self._ModelConfig(model_raw_config)
#
#         # 为模型设置provider信息
#         self._set_model_provider_info()
#
#     def _set_model_provider_info(self):
#         """为所有模型设置provider信息"""
#         model_types = ['main_llm', 'tool_llm', 'vlm', 'util_model', 'embedding', 're_rank']
#
#         for model_type in model_types:
#             model = getattr(self.model_config, model_type)
#             if model and model.provider:
#                 provider_config = self.provider_config_raw.get(model.provider)
#                 if provider_config:
#                     model.api_key = provider_config.get("api_key")
#                     model.base_url = provider_config.get("base_url")
#                 else:
#                     raise ConfigError(f"Provider '{model.provider}' 未找到配置")
#
#     def _validate_configs(self):
#         """验证配置完整性"""
#         # 验证bot配置
#         if not self.bot_config:
#             raise ConfigError("Bot配置缺失")
#
#         # 验证必要模型
#         if not hasattr(self.model_config, 'main_llm') or not self.model_config.main_llm:
#             raise ConfigError("主模型配置缺失")
#
#         # 验证adapter配置
#         if not hasattr(self.adapter_config, 'ada_dict') or not self.adapter_config.ada_dict:
#             raise ConfigError("适配器配置缺失")
#
#     class _AdapterConfig:
#         """适配器配置"""
#         def __init__(self, ada_dict: dict):
#             self.ada_dict = ada_dict
#
#     class _BotConfig:
#         """Bot配置"""
#         def __init__(self, bot_config: dict):
#             bot_section = bot_config.get("bot")
#             if not bot_section:
#                 raise ConfigError("Bot配置section缺失")
#
#             # 类型转换和默认值
#             self.max_memory_length = int(bot_section.get("max_memory_length", 5))
#             self.max_message_interval = int(bot_section.get("max_message_interval", 2))
#
#     class _ProviderConfig:
#         """Provider配置"""
#         def __init__(self):
#             pass
#
#     class _ModelConfig:
#         """模型配置"""
#         def __init__(self, model_config: dict):
#             # 创建模型实例
#             self.main_llm = self._create_model(model_config, "main_llm")
#             self.tool_llm = self._create_model(model_config, "tool_llm")
#             self.vlm = self._create_model(model_config, "vlm")
#             self.util_model = self._create_model(model_config, "util_model")
#             self.embedding = self._create_model(model_config, "embedding")
#             self.re_rank = self._create_model(model_config, "re_rank")
#
#             # 其他特殊模型（只有model，没有provider）
#             tti_info = model_config.get("tti", {})
#             self.tti = self._Model(model=tti_info.get("model") if tti_info else None)
#
#             tts_info = model_config.get("tts", {})
#             self.tts = self._Model(model=tts_info.get("model") if tts_info else None)
#             self.tts_voice_name = tts_info.get("voice_name") if tts_info else None
#
#             stt_info = model_config.get("stt", {})
#             self.stt = self._Model(model=stt_info.get("model") if stt_info else None)
#
#         def _create_model(self, model_config: dict, model_type: str) -> Optional['_Model']:
#             """创建模型实例，如果配置不存在返回None"""
#             model_info = model_config.get(model_type)
#             if not model_info:
#                 return None
#             return self._Model(model_info.get("provider"), model_info.get("model"))
#
#         class _Model:
#             """单个模型配置"""
#             def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
#                 self.provider = provider
#                 self.model = model
#                 self.api_key = None
#                 self.base_url = None
#
#             def __bool__(self):
#                 """检查模型是否配置完整"""
#                 return bool(self.provider and self.model)


try:
    _global_config_ada = get_ada_config("config/adapters.ini")
    _global_config_providers = get_config("config/providers.ini")
    _global_config_models = get_config("config/models.ini")
    _global_config_bot = get_config("config/bot.ini")
    
    global_config = {
        "ada_config": _global_config_ada,
        "providers": _global_config_providers,
        "models": _global_config_models,
        "bot_config": _global_config_bot
    }
except Exception as e:
    print(f"error: loading global config: {e}")
    global_config = {}

# global_config_new = Config()
