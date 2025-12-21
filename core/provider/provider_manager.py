"""Provider 管理器，负责创建和管理所有 Provider 实例"""
from typing import Dict, Optional, Type
from core.logging_manager import get_logger
from .provider import (
    BaseProvider, LLMProvider, TTSProvider, STTProvider,
    EmbeddingProvider, RerankProvider, ImageProvider, VideoProvider
)

logger = get_logger("provider_manager", "cyan")


class ProviderManager:
    """管理所有 Provider"""
    
    _instance = None
    _providers: Dict[str, BaseProvider] = {}
    
    def __new__(cls, providers_config: dict):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, providers_config: dict):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self.providers_config = providers_config
            self._load_providers()
    
    def _load_providers(self):
        """从配置加载所有 providers"""
        providers_config = self.providers_config
        
        for provider_config in providers_config:
            provider = providers_config[provider_config]
            provider["provider_name"] = provider_config
            self.set_provider(provider)

    def set_provider(self, provider: dict):
        provider_name = provider.get("provider_name")
        provider_type = provider.get("type")
        provider_format = provider.get("format")

        provider_inst = None

        if provider_format == "openai":
            if provider_type == "llm":
                from .src.openai_provider import OpenAIProvider
                provider_inst = OpenAIProvider(provider_name, provider_name, provider)
            elif provider_type == "image":
                from .src.openai_provider import OpenAIImageProvider
                provider_inst = OpenAIImageProvider(provider_name, provider_name, provider)
        elif provider_format == "siliconflow":
            if provider_type == "image":
                from .src.siliconflow import SiliconflowImageProvider
                provider_inst = SiliconflowImageProvider(provider_name, provider_name, provider)
            elif provider_type == "tts":
                from .src.siliconflow import SiliconflowTTSProvider
                provider_inst = SiliconflowTTSProvider(provider_name, provider_name, provider)
            elif provider_type == "stt":
                from .src.siliconflow import SiliconflowSTTProvider
                provider_inst = SiliconflowSTTProvider(provider_name, provider_name, provider)
        elif provider_format == "volcengine":
            if provider_type == "llm":
                from .src.volcengine import VolcLLMProvider
                provider_inst = VolcLLMProvider(provider_name, provider_name, provider)
            elif provider_type == "image":
                from .src.volcengine import VolcImageProvider
                provider_inst = VolcImageProvider(provider_name, provider_name, provider)
        elif provider_format == "modelscope":
            if provider_type == "image":
                from .src.modelscope import ModelScopeImageProvider
                provider_inst = ModelScopeImageProvider(provider_name, provider_name, provider)

        if provider_inst:
            self._providers[provider_name] = provider_inst

    def get_provider(self, provider_id: str) -> Optional[BaseProvider]:
        """获取指定的 provider"""
        return self._providers.get(provider_id)
    
    def get_llm_provider(self, provider_id: str) -> Optional[LLMProvider]:
        """获取 LLM provider"""
        provider = self.get_provider(provider_id)
        if isinstance(provider, LLMProvider):
            return provider
        return None
    
    def get_tts_provider(self, provider_id: str) -> Optional[TTSProvider]:
        """获取 TTS provider"""
        provider = self.get_provider(provider_id)
        if isinstance(provider, TTSProvider):
            return provider
        return None
    
    def get_stt_provider(self, provider_id: str) -> Optional[STTProvider]:
        """获取 STT provider"""
        provider = self.get_provider(provider_id)
        if isinstance(provider, STTProvider):
            return provider
        return None

    def get_image_provider(self, provider_id: str) -> Optional[ImageProvider]:
        """获取 Image provider"""
        provider = self.get_provider(provider_id)
        if isinstance(provider, ImageProvider):
            return provider
        return None
    
    def get_all_providers(self) -> Dict[str, BaseProvider]:
        """获取所有 providers"""
        return self._providers.copy()
