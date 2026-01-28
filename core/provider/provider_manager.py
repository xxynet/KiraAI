import os
import json
import uuid
import importlib.util
import inspect
from typing import Dict, Optional, Type

from .provider import (
    BaseProvider, LLMProvider, TTSProvider, STTProvider,
    EmbeddingProvider, RerankProvider, ImageProvider, VideoProvider,
    NewBaseProvider, ProviderInfo, ModelInfo
)

from core.utils.path_utils import get_config_path
from core.logging_manager import get_logger
from core.config import KiraConfig

logger = get_logger("provider_manager", "cyan")


class ProviderManager:
    """管理所有 Provider"""
    
    _instance = None
    _providers: Dict[str, NewBaseProvider] = {}
    _provider_configs: Dict[str, dict]
    
    # Registry data
    _registry: Dict[str, Type[NewBaseProvider]] = {}
    _manifests: Dict[str, dict] = {}
    _schemas: Dict[str, dict] = {}
    
    def __new__(cls, kira_config: KiraConfig):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, kira_config: KiraConfig):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            # Load providers from src directory using Registry logic
            src_dir = os.path.join(os.path.dirname(__file__), "src")
            self.scan_providers(src_dir)

            self.kira_config = kira_config
            
            self.providers_config = kira_config.get("providers", {})
            self._load_providers()
            
    @classmethod
    def get_provider_class(cls, name: str) -> Optional[Type]:
        return cls._registry.get(name)

    @classmethod
    def get_provider_types(cls) -> list[str]:
        return list(cls._registry.keys())

    @classmethod
    def get_schema(cls, name: str) -> dict:
        return cls._schemas.get(name, {})

    def get_default_model(self, model_key: str):
        default_model = self.kira_config.get_config(f"models.{model_key}")
        if default_model and ":" in default_model:
            model_provider = default_model.split(":")[0]
            model_id = "".join(default_model.split(":")[1:])

            model_type_mapping = {
                "default_llm": "llm",
                "default_fast_llm": "llm",
                "default_vlm": "llm",
                "default_tts": "tts",
                "default_stt": "stt",
                "default_image": "image",
                "default_embedding": "embedding",
                "default_rerank": "rerank",
                "default_video": "video"
            }
            model_type = model_type_mapping[model_key]

            model_info = ModelInfo(
                model_type,
                model_id,
                model_provider,
                self.kira_config.get_config(f"providers.{model_provider}.name"),
                self.kira_config.get_config(f"providers.{model_provider}.provider_config"),
                # When the model ID has a dot, kira_config.get_config would return unexpected value
                self.kira_config.get_config(f"providers.{model_provider}.model_config.{model_type}").get(model_id)
            )
            return model_info

    def get_provider_info(self, provider_id: str) -> Optional[ProviderInfo]:
        providers_config = self.kira_config.get("providers", {})
        config = providers_config.get(provider_id)
        if not config:
            return None
        provider_config = config.get("provider_config", {}) or {}
        if "name" in provider_config and "name" not in config:
            config["name"] = provider_config.pop("name")
            self.kira_config["providers"][provider_id] = config
            self.kira_config.save_config()
        provider_type = config.get("format", "unknown")
        provider_name = config.get("name", provider_id)
        return ProviderInfo(
            provider_name=provider_name,
            provider_id=provider_id,
            provider_type=provider_type,
            provider_config=provider_config,
        )

    def register_provider(self, name: str, provider_name: str):
        """
        Register a provider instance
        :param name: name of the provider instance, e.g. openai-official, nvidia
        :param provider_name: which provider to load from, e.g. OpenAI
        :return:
        """
        if provider_name in self._registry:
            provider_id = uuid.uuid4().hex[:8]
            provider_config = self.generate_provider_config(provider_name, provider_id)
            provider_inst = self._registry[provider_name](provider_id, name, provider_config)
            self._providers[provider_id] = provider_inst
            return True
        else:
            return False

    def register_model(self, provider_id: str, model_type: str, model_id: str, config: Optional[dict] = None):
        """
        Register a model to an existing provider
        :param provider_id: an ID of an existing provider instance
        :param model_type: type of the model, e.g. llm, tts, image
        :param model_id: a specific model ID defined by your provider, e.g. gpt-3.5-turbo
        :param config: model config
        :return:
        """
        providers_config = self.kira_config.get("providers", {})
        provider_config = providers_config.get(provider_id)
        if not provider_config:
            logger.error(f"Provider {provider_id} not found in config")
            return False
        
        model_config_root = provider_config.setdefault("model_config", {})
        model_type_config = model_config_root.setdefault(model_type, {})
            
        # 3. Get default config from schema
        model_defaults = {}
        # 提供商的名字，如OpenAI
        provider_format = provider_config.get("format")
        if provider_format:
            schema = self.get_schema(provider_format)
            if schema:
                model_config_schema = schema.get("model_config", {}).get(model_type, {})
                for key, value_info in model_config_schema.items():
                    model_defaults[key] = value_info.get("default")
        
        model_config = dict(model_defaults)
        if config:
            model_config.update(config)
        
        model_type_config[model_id] = model_config
        
        self.kira_config["providers"][provider_id] = provider_config
        self.kira_config.save_config()
        
        try:
            self.set_provider(provider_id, provider_config)
        except Exception as e:
            logger.error(f"Failed to re-instantiate provider {provider_id} after registering model: {e}")
        logger.info(f"Registered model {model_id} ({model_type}) to provider {provider_id}")
        return True

    def get_models(self, provider_id: str) -> dict:
        model_infos = self.get_model_infos(provider_id)
        models: dict = {}
        for info in model_infos:
            type_dict = models.setdefault(info.model_type, {})
            type_dict[info.model_id] = info.model_config
        return models

    def get_model_infos(self, provider_id: str) -> list[ModelInfo]:
        providers_config = self.kira_config.get("providers", {})
        provider_config = providers_config.get(provider_id) or {}
        provider_instance_config = provider_config.get("provider_config", {}) or {}
        provider_name = provider_config.get("name", provider_id)
        model_config_root = provider_config.get("model_config") or {}
        model_infos: list[ModelInfo] = []
        for model_type, type_models in model_config_root.items():
            if not isinstance(type_models, dict):
                continue
            for model_id, model_cfg in type_models.items():
                if not isinstance(model_cfg, dict):
                    continue
                model_infos.append(
                    ModelInfo(
                        model_type=model_type,
                        model_id=model_id,
                        provider_id=provider_id,
                        provider_name=provider_name,
                        provider_config=provider_instance_config,
                        model_config=model_cfg,
                    )
                )
        return model_infos

    def update_model(self, provider_id: str, model_type: str, model_id: str, config: dict) -> bool:
        providers_config = self.kira_config.get("providers", {})
        provider_config = providers_config.get(provider_id)
        if not provider_config:
            logger.error(f"Provider {provider_id} not found in config")
            return False

        model_config_root = provider_config.get("model_config") or {}
        model_type_config = model_config_root.get(model_type)
        if not model_type_config or model_id not in model_type_config:
            logger.error(f"Model {model_id} ({model_type}) not found for provider {provider_id}")
            return False

        model_type_config[model_id] = config
        provider_config["model_config"] = model_config_root
        self.kira_config["providers"][provider_id] = provider_config
        self.kira_config.save_config()

        try:
            self.set_provider(provider_id, provider_config)
        except Exception as e:
            logger.error(f"Failed to re-instantiate provider {provider_id} after updating model: {e}")

        logger.info(f"Updated model {model_id} ({model_type}) for provider {provider_id}")
        return True

    def delete_model(self, provider_id: str, model_type: str, model_id: str) -> bool:
        providers_config = self.kira_config.get("providers", {})
        provider_config = providers_config.get(provider_id)
        if not provider_config:
            logger.error(f"Provider {provider_id} not found in config")
            return False

        model_config_root = provider_config.get("model_config") or {}
        model_type_config = model_config_root.get(model_type)
        if not model_type_config or model_id not in model_type_config:
            logger.error(f"Model {model_id} ({model_type}) not found for provider {provider_id}")
            return False

        del model_type_config[model_id]
        provider_config["model_config"] = model_config_root
        self.kira_config["providers"][provider_id] = provider_config
        self.kira_config.save_config()

        try:
            self.set_provider(provider_id, provider_config)
        except Exception as e:
            logger.error(f"Failed to re-instantiate provider {provider_id} after deleting model: {e}")

        logger.info(f"Deleted model {model_id} ({model_type}) for provider {provider_id}")
        return True

    @classmethod
    def scan_providers(cls, src_dir: str):
        """
        Scan subdirectories in src_dir for manifest.json and provider.py
        """
        if not os.path.exists(src_dir):
            logger.error(f"Provider source directory not found: {src_dir}")
            return

        for entry in os.listdir(src_dir):
            provider_dir = os.path.join(src_dir, entry)
            if not os.path.isdir(provider_dir):
                continue

            manifest_path = os.path.join(provider_dir, "manifest.json")
            if not os.path.exists(manifest_path):
                continue

            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                
                provider_name = manifest.get("name")
                if not provider_name:
                    logger.warning(f"Manifest in {provider_dir} missing 'name'")
                    continue

                # Load schema if exists
                schema_path = os.path.join(provider_dir, "schema.json")
                schema = {}
                if os.path.exists(schema_path):
                    try:
                        with open(schema_path, "r", encoding="utf-8") as f:
                            schema = json.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to load schema for {provider_name}: {e}")

                provider_script = os.path.join(provider_dir, "provider.py")
                if not os.path.exists(provider_script):
                    provider_script = os.path.join(provider_dir, "__init__.py")
                    if not os.path.exists(provider_script):
                        logger.warning(f"No provider.py or __init__.py found in {provider_dir}")
                        continue
                
                # Import the module
                module_name = f"core.provider.src.{entry}.provider"
                spec = importlib.util.spec_from_file_location(module_name, provider_script)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Find the provider class
                    found = False
                    for attr_name, attr_value in inspect.getmembers(module):
                        if inspect.isclass(attr_value) and issubclass(attr_value, NewBaseProvider) and attr_value is not NewBaseProvider:
                            # Register it using the manifest name
                            key = provider_name
                            cls._registry[key] = attr_value
                            cls._manifests[key] = manifest
                            cls._schemas[key] = schema
                            logger.info(f"Registered provider: {provider_name}")
                            found = True
                            break
                    
                    if not found:
                        logger.warning(f"No class inheriting from NewBaseProvider found in {provider_dir}")

            except Exception as e:
                logger.error(f"Error loading provider from {provider_dir}: {e}")
    
    def _load_providers(self):
        """从配置加载所有 providers"""
        providers_config = self.providers_config
        for provider_id, provider in providers_config.items():
            self.set_provider(provider_id, provider)

    def generate_provider_config(self, provider_format: str, provider_id: str):
        """
        Generate provider config file from schema.json.
        Saves to data/config/provider_{provider_id}.json.
        """
        
        schema = self.get_schema(provider_format)
        if not schema:
            logger.error(f"No schema found for provider format: {provider_format}")
            return

        provider_config_schema = schema.get("provider_config", {})
        generated_config = {
            "format": provider_format,
            "name": provider_id,
            "provider_config": {},
            "model_config": {
                # model_type: { model_id: { **model_config } }
            }
        }

        for key, value_info in provider_config_schema.items():
            default_value = value_info.get("default")
            generated_config["provider_config"][key] = default_value

        try:
            self.kira_config["providers"][provider_id] = generated_config
            self.kira_config.save_config()
            logger.info(f"Generated config for provider {provider_id}")
        except Exception as e:
            logger.error(f"Failed to save generated config for {provider_id}: {e}")
        return generated_config

    def set_provider(self, provider_id: str, provider: dict):
        provider_type = provider.get("type")
        provider_format = provider.get("format")
        provider_name = provider.get("name", provider_id)

        provider_inst = None

        # Try registry first
        provider_cls = self.get_provider_class(provider_format)
        if provider_cls:
            try:
                provider_inst = provider_cls(
                    provider_id,
                    provider_name,
                    provider.get("provider_config", {}) or {},
                )
                logger.info(f"Loaded provider {provider_name} ({provider_id}) from registry")
            except Exception as e:
                logger.error(f"Failed to instantiate provider {provider_name} ({provider_id}) from registry: {e}")

        if provider_inst:
            self._providers[provider_id] = provider_inst

    def get_provider(self, provider_id: str) -> Optional[NewBaseProvider]:
        """获取指定的 provider"""
        return self._providers.get(provider_id)
    
    def get_all_providers(self) -> Dict[str, NewBaseProvider]:
        """获取所有 providers"""
        return self._providers.copy()
