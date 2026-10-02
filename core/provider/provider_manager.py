import os
import json
import time
import uuid
import importlib.util
import inspect
import copy
from contextlib import aclosing
from functools import wraps
from pathlib import Path
from typing import Dict, Optional, Type

from .provider import (
    BaseProvider, BaseModelClient, ProviderInfo, ModelInfo, ModelType, ProviderAPIError,
    LLMModelClient, TTSModelClient, STTModelClient, ImageModelClient,
    VideoModelClient, EmbeddingModelClient, RerankModelClient
)
from .llm_model import LLMRequest
from core.agent.message import OpenAIMessage

from core.utils.path_utils import get_config_path, resolve_manifest_icon_path
from core.logging_manager import get_logger
from core.config import KiraConfig
from core.config import config_loader
from .model_identity import (
    DEFAULT_MODEL_TYPES, MODEL_CONFIG_VERSION, generate_model_id, resolve_model_entry,
)
from .model_migration import migrate_provider_models, migrate_model_config_file
from core.config.config_field import BaseConfigField, build_fields
from core.db.service import DatabaseService

logger = get_logger("provider_manager", "cyan")


class ProviderManager:
    """管理所有 Provider"""
    
    _instance = None
    _providers: Dict[str, BaseProvider] = {}  # Provider instances
    _provider_configs: Dict[str, dict]
    
    # Registry data
    _registry: Dict[str, Type[BaseProvider]] = {}  # Provider classes
    _manifests: Dict[str, dict] = {}
    _manifest_dirs: Dict[str, Path] = {}
    _schemas: Dict[str, dict] = {}
    
    def __new__(cls, db: DatabaseService, kira_config: KiraConfig):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db: DatabaseService, kira_config: KiraConfig):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            
            # Load providers from src directory using Registry logic
            src_dir = os.path.join(os.path.dirname(__file__), "src")
            self.scan_providers(src_dir)

            self.db = db
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
        schema = cls._schemas.get(name, {})
        return copy.deepcopy(schema) if schema else {}

    @classmethod
    def get_manifest(cls, name: str) -> dict:
        manifest = cls._manifests.get(name, {})
        return copy.deepcopy(manifest) if manifest else {}

    @classmethod
    def get_icon_path(cls, name: str, dark: bool = False) -> Optional[Path]:
        manifest_dir = cls._manifest_dirs.get(name)
        manifest = cls._manifests.get(name, {})
        if not manifest_dir:
            return None
        return resolve_manifest_icon_path(
            manifest_dir, manifest.get("icon-dark" if dark else "icon"),
        )

    @classmethod
    def register_provider_type(cls, provider_format: str, provider_cls: Type[BaseProvider], manifest: dict, manifest_dir: Path, schema: Optional[dict] = None) -> None:
        """Register a Provider type supplied by a plugin."""
        if not isinstance(provider_format, str) or not provider_format.strip():
            raise ValueError("Provider format must be a non-empty string")
        if not inspect.isclass(provider_cls) or not issubclass(provider_cls, BaseProvider):
            raise TypeError("Provider class must inherit from BaseProvider")
        if not isinstance(manifest, dict) or (schema is not None and not isinstance(schema, dict)):
            raise TypeError("Provider manifest and schema must be dictionaries")
        provider_format = provider_format.strip()
        existing = cls._registry.get(provider_format)
        if existing is not None and existing is not provider_cls:
            raise ValueError(f"Provider format '{provider_format}' is already registered")
        cls._registry[provider_format] = provider_cls
        cls._manifests[provider_format] = manifest.copy()
        cls._manifest_dirs[provider_format] = Path(manifest_dir)
        cls._schemas[provider_format] = copy.deepcopy(schema) if schema else {}

    @classmethod
    def unregister_provider_type(cls, provider_format: str, provider_cls: Type[BaseProvider]) -> bool:
        """Remove a plugin Provider type without affecting another owner."""
        if cls._registry.get(provider_format) is not provider_cls:
            return False
        cls._registry.pop(provider_format, None)
        cls._manifests.pop(provider_format, None)
        cls._manifest_dirs.pop(provider_format, None)
        cls._schemas.pop(provider_format, None)
        return True

    def remove_provider_instances_by_format(self, provider_format: str) -> int:
        """Remove runtime instances while preserving their stored configuration."""
        removed = 0
        configs = self.kira_config.get("providers", {}) or {}
        for provider_id in list(self._providers):
            if isinstance(configs.get(provider_id), dict) and configs[provider_id].get("format") == provider_format:
                self._providers.pop(provider_id, None)
                removed += 1
        return removed

    def get_model_client(
        self,
        provider_id: str,
        model_id: str,
        model_type: Optional[ModelType | str] = None,
    ) -> Optional[BaseModelClient]:
        provider = self._require_provider_available(provider_id)
        model_info = self.get_model_info(provider_id, model_id, model_type)
        if not model_info:
            return
        model_type_enum = model_info.model_type

        if model_type_enum not in provider.models:
            raise ValueError(f"Unsupported model type {model_type_enum.value}")

        model_cls = provider.models[model_type_enum]
        model_client = model_cls(model_info)
        # Recheck at invocation time for clients retained by plugins or agent loops.
        for name, method in inspect.getmembers(model_client, callable):
            if not name.startswith('_') and (
                inspect.iscoroutinefunction(method) or inspect.isasyncgenfunction(method)
            ):
                setattr(model_client, name, self._guard_model_call(provider_id, method))
        return model_client

    def _require_provider_available(self, provider_id: str) -> BaseProvider:
        config = self.kira_config.get('providers', {}).get(provider_id, {})
        if config.get('status', 'active') != 'active':
            raise ProviderAPIError(f'Provider {provider_id} is disabled')
        provider = self.get_provider(provider_id)
        if provider is None:
            raise ValueError(f'Provider {provider_id} is not available')
        return provider

    def _guard_model_call(self, provider_id: str, method):
        if inspect.isasyncgenfunction(method):
            @wraps(method)
            async def guarded_stream(*args, **kwargs):
                self._require_provider_available(provider_id)
                async with aclosing(method(*args, **kwargs)) as stream:
                    async for chunk in stream:
                        yield chunk
            return guarded_stream

        @wraps(method)
        async def guarded_call(*args, **kwargs):
            self._require_provider_available(provider_id)
            return await method(*args, **kwargs)
        return guarded_call

    def get_default_llm(self) -> LLMModelClient:
        model_info = self.get_default_model_info("default_llm")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, LLMModelClient):
            raise TypeError(
                f"Expected LLMModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_fast_llm(self) -> LLMModelClient:
        model_info = self.get_default_model_info("default_fast_llm")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, LLMModelClient):
            raise TypeError(
                f"Expected LLMModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_vlm(self) -> LLMModelClient:
        model_info = self.get_default_model_info("default_vlm")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, LLMModelClient):
            raise TypeError(
                f"Expected LLMModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_tts(self) -> TTSModelClient:
        model_info = self.get_default_model_info("default_tts")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, TTSModelClient):
            raise TypeError(
                f"Expected TTSModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_stt(self) -> STTModelClient:
        try:
            model_info = self.get_default_model_info("default_stt")
        except ValueError:
            logger.error("default_stt not configured, please configure it in Configuration")
            raise
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, STTModelClient):
            raise TypeError(
                f"Expected STTModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_image(self) -> ImageModelClient:
        model_info = self.get_default_model_info("default_image")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, ImageModelClient):
            raise TypeError(
                f"Expected ImageModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_video(self) -> VideoModelClient:
        model_info = self.get_default_model_info("default_video")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, VideoModelClient):
            raise TypeError(
                f"Expected VideoModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_embedding(self) -> EmbeddingModelClient:
        model_info = self.get_default_model_info("default_embedding")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, EmbeddingModelClient):
            raise TypeError(
                f"Expected EmbeddingModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_rerank(self) -> RerankModelClient:
        model_info = self.get_default_model_info("default_rerank")
        model_client = self.get_model_client(
            model_info.provider_id, model_info.model_id, model_info.model_type
        )
        if not isinstance(model_client, RerankModelClient):
            raise TypeError(
                f"Expected RerankModelClient, got {type(model_client).__name__}"
            )
        return model_client

    def get_default_model_info(self, model_key: str):
        reference = self.kira_config.get_config(f"models.{model_key}")
        if not reference or ":" not in reference:
            raise ValueError(f"{model_key} not set")
        provider_id, model_id = reference.split(":", 1)
        info = self.get_model_info(provider_id, model_id, DEFAULT_MODEL_TYPES[model_key])
        if info is None:
            raise ValueError(f"{model_key} model not found")
        return info

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

    def _save_provider_models(self, provider_id: str, provider_config: dict):
        """Persist model changes before applying them to runtime clients."""
        original = self.kira_config["providers"][provider_id]
        self.kira_config["providers"][provider_id] = provider_config
        try:
            self.kira_config.save_config(raise_on_error=True)
        except Exception:
            self.kira_config["providers"][provider_id] = original
            raise
        self.set_provider(provider_id, provider_config)

    def _model_defaults(self, provider_config: dict, model_type: str) -> dict:
        fields = (self.get_schema(provider_config.get("format")) or {}).get("model_config", {})
        return {
            field.key: copy.deepcopy(field.default)
            for field in fields.get(model_type, [])
            if isinstance(field, BaseConfigField)
        }

    def register_model(self, provider_id: str, model_type: str, model_name: str, config: Optional[dict] = None):
        """Register an upstream model under a generated, immutable internal ID."""
        ModelType(model_type)
        model_name = model_name.strip()
        if not model_name:
            raise ValueError("model_name must not be empty")
        original = self.kira_config.get("providers", {}).get(provider_id)
        if not original:
            return None
        provider = copy.deepcopy(original)
        migrate_provider_models(provider)
        model_id = generate_model_id(provider)
        model_config = self._model_defaults(provider, model_type)
        model_config.update(config or {})
        provider["model_config"].setdefault(model_type, {})[model_id] = {
            "model_name": model_name, "config": model_config,
        }
        self._save_provider_models(provider_id, provider)
        return model_id

    def get_models(self, provider_id: str) -> dict:
        """Return model entries keyed by internal ID, with API names and parameters."""
        models = {}
        for info in self.get_model_infos(provider_id):
            models.setdefault(info.model_type.value, {})[info.model_id] = {
                "model_name": info.model_name, "config": info.model_config,
            }
        return models

    def _build_model_info(self, provider_id: str, provider: dict, kind: str, model_id: str, entry: dict):
        modern = provider.get("model_config_version") == MODEL_CONFIG_VERSION
        return ModelInfo(
            model_type=ModelType(kind),
            model_id=model_id,
            model_name=entry["model_name"] if modern else model_id,
            provider_id=provider_id,
            provider_name=provider.get("name", provider_id),
            provider_config=provider.get("provider_config") or {},
            model_config=(entry.get("config") or {}) if modern else entry,
        )

    def get_model_info(
        self, provider_id: str, model_id: str,
        model_type: Optional[ModelType | str] = None,
    ) -> Optional[ModelInfo]:
        provider = self.kira_config.get("providers", {}).get(provider_id) or {}
        if isinstance(model_type, str):
            model_type = ModelType(model_type)
        resolved = resolve_model_entry(provider, model_id, model_type)
        if resolved:
            kind, internal_id, entry = resolved
            return self._build_model_info(provider_id, provider, kind, internal_id, entry)
        return None

    def get_model_infos(self, provider_id: str) -> list[ModelInfo]:
        provider = self.kira_config.get("providers", {}).get(provider_id) or {}
        return [
            self._build_model_info(provider_id, provider, kind, model_id, entry)
            for kind, models in (provider.get("model_config") or {}).items()
            if isinstance(models, dict)
            for model_id, entry in models.items()
            if isinstance(entry, dict)
        ]

    def update_model(
        self, provider_id: str, model_type: str, model_id: str, config: Optional[dict] = None,
        model_name: Optional[str] = None,
    ) -> bool:
        ModelType(model_type)
        original = self.kira_config.get("providers", {}).get(provider_id)
        if not original:
            return False
        provider = copy.deepcopy(original)
        migrate_provider_models(provider)
        resolved = resolve_model_entry(provider, model_id, model_type)
        if not resolved:
            return False
        entry = resolved[2]
        if model_name is not None:
            model_name = model_name.strip()
            if not model_name:
                raise ValueError("model_name must not be empty")
            entry["model_name"] = model_name
        if config is not None:
            entry["config"] = copy.deepcopy(config)
        self._save_provider_models(provider_id, provider)
        return True

    def delete_model(self, provider_id: str, model_type: str, model_id: str) -> bool:
        ModelType(model_type)
        original = self.kira_config.get("providers", {}).get(provider_id)
        if not original:
            return False
        provider = copy.deepcopy(original)
        migrate_provider_models(provider)
        resolved = resolve_model_entry(provider, model_id, model_type)
        if not resolved:
            return False
        del provider["model_config"][model_type][resolved[1]]
        self._save_provider_models(provider_id, provider)
        return True

    def sync_models(
        self, provider_id: str, model_type: str, add_ids: list[str],
        delete_ids: list[str], config: Optional[dict] = None,
    ) -> dict:
        """Sync upstream names while preserving IDs and configs of retained entries."""
        ModelType(model_type)
        original = self.kira_config.get("providers", {}).get(provider_id)
        if not original:
            return {"added": 0, "removed": 0, "errors": ["Provider not found"]}
        provider = copy.deepcopy(original)
        migrate_provider_models(provider)
        models = provider["model_config"].setdefault(model_type, {})
        names_to_add = {name.strip() for name in add_ids}
        names_to_delete = {name.strip() for name in delete_ids}
        if "" in names_to_add or names_to_add & names_to_delete:
            raise ValueError("Invalid model sync selection")
        added = removed = 0
        for name in names_to_add:
            if any(entry["model_name"] == name for entry in models.values()):
                continue
            model_config = self._model_defaults(provider, model_type)
            model_config.update(config or {})
            models[generate_model_id(provider)] = {"model_name": name, "config": model_config}
            added += 1
        for model_id, entry in list(models.items()):
            if entry["model_name"] in names_to_delete:
                del models[model_id]
                removed += 1
        if added or removed:
            self._save_provider_models(provider_id, provider)
        return {"added": added, "removed": removed, "errors": []}

    async def health_check(self, provider_id: str, model_type: str, model_id: str) -> dict:
        """
        Test model availability by sending a simple prompt.
        :return: {"success": bool, "latency": int (ms), "error": str | None}
        """
        try:
            model_client = self.get_model_client(provider_id, model_id, model_type)
        except Exception as e:
            return {"success": False, "latency": None, "error": str(e)}
        if not model_client:
            return {"success": False, "latency": None, "error": "Model client not found"}

        try:
            start = time.time()

            if isinstance(model_client, LLMModelClient):
                request = LLMRequest(
                    messages=[OpenAIMessage(role="user", content="Say 'pong'")],
                    tools=None,
                    tool_choice="none",
                )
                await model_client.chat(request)
            elif isinstance(model_client, TTSModelClient):
                await model_client.text_to_speech("ping")
            elif isinstance(model_client, EmbeddingModelClient):
                await model_client.embed(["ping"])
            elif isinstance(model_client, RerankModelClient):
                await model_client.rerank("ping", ["ping"])
            else:
                return {
                    "success": False,
                    "latency": None,
                    "error": f"Health check not supported for {model_type} models",
                }

            latency = round((time.time() - start) * 1000)
            return {"success": True, "latency": latency, "error": None}
        except Exception as e:
            return {"success": False, "latency": None, "error": str(e)}

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
                schema: dict = {}
                if os.path.exists(schema_path):
                    try:
                        with open(schema_path, "r", encoding="utf-8") as f:
                            raw_schema = json.load(f)
                        if isinstance(raw_schema, dict):
                            provider_fields: list[BaseConfigField] = []
                            model_fields: Dict[str, list[BaseConfigField]] = {}
                            provider_config_schema = raw_schema.get("provider_config") or {}
                            if isinstance(provider_config_schema, dict):
                                provider_fields = build_fields(provider_config_schema)
                            model_config_schema = raw_schema.get("model_config") or {}
                            if isinstance(model_config_schema, dict):
                                for model_type, fields_schema in model_config_schema.items():
                                    if isinstance(fields_schema, dict):
                                        model_fields[model_type] = build_fields(fields_schema)
                            schema = {
                                "provider_config": provider_fields,
                                "model_config": model_fields,
                            }
                    except Exception as e:
                        logger.warning(f"Failed to load schema for {provider_name}: {e}")

                provider_script = None
                module_name = None
                candidate_files = [
                    (os.path.join(provider_dir, f"{entry}.py"), f"core.provider.src.{entry}.{entry}"),
                    (os.path.join(provider_dir, "provider.py"), f"core.provider.src.{entry}.provider"),
                    (os.path.join(provider_dir, "__init__.py"), f"core.provider.src.{entry}"),
                ]
                for script_path, candidate_module in candidate_files:
                    if os.path.exists(script_path):
                        provider_script = script_path
                        module_name = candidate_module
                        break
                if not provider_script or not module_name:
                    logger.warning(f"No {entry}.py, provider.py or __init__.py found in {provider_dir}")
                    continue
                
                # Import the module
                spec = importlib.util.spec_from_file_location(module_name, provider_script)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Find the provider class
                    found = False
                    for attr_name, attr_value in inspect.getmembers(module):
                        if inspect.isclass(attr_value) and issubclass(attr_value, BaseProvider) and attr_value is not BaseProvider:
                            # Register it using the manifest name
                            key = provider_name
                            cls._registry[key] = attr_value
                            cls._manifests[key] = manifest
                            cls._manifest_dirs[key] = Path(provider_dir)
                            cls._schemas[key] = schema
                            logger.info(f"Registered provider: {provider_name}")
                            found = True
                            break
                    
                    if not found:
                        logger.warning(f"No class inheriting from BaseProvider found in {provider_dir}")

            except Exception as e:
                logger.error(f"Error loading provider from {provider_dir}: {e}")
    
    @staticmethod
    def _deep_fill_defaults(target: dict, defaults: dict) -> bool:
        """
        Recursively fill *target* dict with missing keys from *defaults*.
        If both sides have a dict value for the same key, recurse into it.
        Returns True if any changes were made.
        """
        changed = False
        for key, default_value in defaults.items():
            if key not in target:
                if isinstance(default_value, (dict, list)):
                    target[key] = copy.deepcopy(default_value)
                else:
                    target[key] = default_value
                changed = True
            elif isinstance(default_value, dict) and isinstance(target[key], dict):
                if ProviderManager._deep_fill_defaults(target[key], default_value):
                    changed = True
        return changed

    def _backfill_provider_config(self, provider_id: str, provider_config: dict) -> bool:
        """
        Compare provider config and model configs against the schema,
        fill in any missing keys (including nested dict keys) with their
        default values.  Returns True if any changes were made.
        """
        changed = False
        provider_format = provider_config.get("format")
        if not provider_format:
            return False

        schema = self.get_schema(provider_format)
        if not schema:
            return False

        # 1. Backfill provider_config
        provider_fields = schema.get("provider_config") or []
        provider_config_value = provider_config.get("provider_config")
        if not isinstance(provider_config_value, dict):
            provider_config["provider_config"] = {}
        instance_config = provider_config["provider_config"]
        for field in provider_fields:
            if isinstance(field, BaseConfigField):
                if field.key not in instance_config:
                    if isinstance(field.default, (dict, list)):
                        instance_config[field.key] = copy.deepcopy(field.default)
                    else:
                        instance_config[field.key] = field.default
                    changed = True
                elif isinstance(field.default, dict) and isinstance(instance_config.get(field.key), dict):
                    if self._deep_fill_defaults(instance_config[field.key], field.default):
                        changed = True

        # 2. Backfill model configs
        model_fields_root = schema.get("model_config") or {}
        model_config_root = provider_config.get("model_config") or {}
        for model_type, type_fields in model_fields_root.items():
            if not isinstance(type_fields, list):
                continue
            type_models = model_config_root.get(model_type)
            if not isinstance(type_models, dict):
                continue
            for model_id, model_entry in type_models.items():
                if not isinstance(model_entry, dict):
                    continue
                model_cfg = model_entry.get("config") if provider_config.get("model_config_version") == MODEL_CONFIG_VERSION else model_entry
                if not isinstance(model_cfg, dict):
                    continue
                for field in type_fields:
                    if not isinstance(field, BaseConfigField):
                        continue
                    if field.key not in model_cfg:
                        if isinstance(field.default, (dict, list)):
                            model_cfg[field.key] = copy.deepcopy(field.default)
                        else:
                            model_cfg[field.key] = field.default
                        changed = True
                    elif isinstance(field.default, dict) and isinstance(model_cfg.get(field.key), dict):
                        if self._deep_fill_defaults(model_cfg[field.key], field.default):
                            changed = True

        return changed

    def _load_providers(self):
        """从配置加载所有 providers，同时补充 schema 中新增的配置项"""
        migrate_model_config_file(self.kira_config, config_loader.CONFIG_PATH)
        self.providers_config = self.kira_config.get("providers", {})
        providers_config = self.providers_config
        need_save = False
        for provider_id, provider in providers_config.items():
            if self._backfill_provider_config(provider_id, provider):
                need_save = True
            self.set_provider(provider_id, provider)
        if need_save:
            self.kira_config.save_config()

    def generate_provider_config(self, provider_format: str, provider_id: str):
        """
        Generate provider config file from schema.json.
        Saves to data/config/provider_{provider_id}.json.
        """
        
        schema = self.get_schema(provider_format)
        if not schema:
            logger.error(f"No schema found for provider format: {provider_format}")
            return

        provider_fields = schema.get("provider_config") or []
        generated_config = {
            "format": provider_format,
            "status": "active",
            "model_config_version": MODEL_CONFIG_VERSION,
            "name": provider_id,
            "provider_config": {},
            "model_config": {
                # model_type: { internal_id: { model_name, config } }
            }
        }

        for field in provider_fields:
            if isinstance(field, BaseConfigField):
                generated_config["provider_config"][field.key] = field.default

        try:
            self.kira_config["providers"][provider_id] = generated_config
            self.kira_config.save_config()
            logger.info(f"Generated config for provider {provider_id}")
        except Exception as e:
            logger.error(f"Failed to save generated config for {provider_id}: {e}")
        return generated_config

    def set_provider(self, provider_id: str, provider: dict):
        if provider.get("status", "active") != "active":
            self._providers.pop(provider_id, None)
            return
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
                logger.info(f"Loaded provider {provider_name} ({provider_id})")
            except Exception as e:
                logger.error(f"Failed to instantiate provider {provider_name} ({provider_id}): {e}")

        if provider_inst:
            self._providers[provider_id] = provider_inst

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """获取指定的 provider"""
        config = self.kira_config.get("providers", {}).get(provider_id, {})
        if config.get("status", "active") != "active":
            return None
        return self._providers.get(provider_id)
    
    def get_all_providers(self) -> Dict[str, BaseProvider]:
        """获取所有 providers"""
        return self._providers.copy()

    async def fetch_remote_models(self, provider_id: str, model_type: str = "llm") -> list[dict]:
        """
        Fetch available models from a provider's remote API.
        Returns a list of model info dicts.
        """
        provider = self._require_provider_available(provider_id)
        try:
            models = await provider.get_llm_list()
            return models
        except Exception as e:
            logger.error(f"Failed to fetch remote models for provider {provider_id}: {e}")
            raise
