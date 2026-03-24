from typing import Dict, List

from fastapi import Depends, HTTPException, status

from core.logging_manager import get_logger
from webui.models import (
    ModelCreateRequest,
    ModelUpdateRequest,
    ProviderBase,
    ProviderResponse,
)
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _generate_id

logger = get_logger("webui", "blue")


class ProvidersRoutes(Routes):
    def __init__(self, app, lifecycle):
        super().__init__(app, lifecycle)
        self._providers: Dict[str, ProviderResponse] = {}

    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/provider-types",
                methods=["GET"],
                endpoint=self.get_provider_types,
                response_model=List[str],
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/schema/{provider_type}",
                methods=["GET"],
                endpoint=self.get_provider_schema,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers",
                methods=["GET"],
                endpoint=self.list_providers,
                response_model=List[ProviderResponse],
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers",
                methods=["POST"],
                endpoint=self.create_provider,
                response_model=ProviderResponse,
                status_code=status.HTTP_201_CREATED,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}",
                methods=["GET"],
                endpoint=self.get_provider,
                response_model=ProviderResponse,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}",
                methods=["PUT"],
                endpoint=self.update_provider,
                response_model=ProviderResponse,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}/models",
                methods=["POST"],
                endpoint=self.add_model,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}/models",
                methods=["GET"],
                endpoint=self.get_models,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}/models/{model_type}/{model_id:path}",
                methods=["PUT"],
                endpoint=self.update_model,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}/models/{model_type}/{model_id:path}",
                methods=["DELETE"],
                endpoint=self.delete_model,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/providers/{provider_id}",
                methods=["DELETE"],
                endpoint=self.delete_provider,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["providers"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    def _get_supported_model_types(self, provider_id: str) -> List[str]:
        if not self.lifecycle or not self.lifecycle.provider_manager:
            return []
        try:
            providers_config = self.lifecycle.kira_config.get("providers", {}) or {}
            provider_cfg = providers_config.get(provider_id) or {}
            provider_format = provider_cfg.get("format")
            if not provider_format:
                return []
            provider_cls = self.lifecycle.provider_manager.get_provider_class(provider_format)
            if not provider_cls:
                return []
            models_attr = getattr(provider_cls, "models", None)
            if not models_attr:
                return []
            supported: List[str] = []
            for key in models_attr.keys():
                type_key = getattr(key, "value", None)
                if not type_key:
                    type_key = str(key)
                if isinstance(type_key, str):
                    supported.append(type_key)
            return supported
        except Exception as e:
            logger.error(f"Failed to get supported model types for provider {provider_id}: {e}")
            return []

    async def get_provider_types(self):
        try:
            if not self.lifecycle or not self.lifecycle.provider_manager:
                logger.warning("Provider manager not available for get_provider_types")
                return []
            return self.lifecycle.provider_manager.get_provider_types()
        except Exception as e:
            logger.error(f"Error getting provider types: {e}")
            return []

    async def get_provider_schema(self, provider_type: str):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=404, detail="Provider manager not available")

        schema = self.lifecycle.provider_manager.get_schema(provider_type)
        if not schema:
            raise HTTPException(
                status_code=404,
                detail=f"Schema not found for provider type: {provider_type}",
            )

        provider_fields = schema.get("provider_config") or []
        model_fields_root = schema.get("model_config") or {}

        provider_config_dict: Dict[str, Dict] = {}
        for field in provider_fields:
            key = getattr(field, "key", None)
            if not key:
                continue
            provider_config_dict[key] = field.to_dict()

        model_config_dict: Dict[str, Dict[str, Dict]] = {}
        for model_type, fields in model_fields_root.items():
            type_dict: Dict[str, Dict] = {}
            for field in fields:
                key = getattr(field, "key", None)
                if not key:
                    continue
                type_dict[key] = field.to_dict()
            model_config_dict[model_type] = type_dict

        return {
            "provider_config": provider_config_dict,
            "model_config": model_config_dict,
        }

    async def list_providers(self):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            return list(self._providers.values())

        providers = []
        configured_providers = self.lifecycle.kira_config.get("providers", {})
        active_providers = self.lifecycle.provider_manager._providers

        for provider_id in configured_providers.keys():
            provider_info = self.lifecycle.provider_manager.get_provider_info(provider_id)
            if not provider_info:
                continue
            is_active = provider_id in active_providers
            config = self.lifecycle.kira_config.get("providers", {}).get(provider_id, {})
            supported_model_types = self._get_supported_model_types(provider_id)
            providers.append(
                ProviderResponse(
                    id=provider_info.provider_id,
                    name=provider_info.provider_name,
                    type=provider_info.provider_type,
                    status="active" if is_active else "inactive",
                    config=provider_info.provider_config,
                    model_config_data=config.get("model_config", {}),
                    supported_model_types=supported_model_types,
                )
            )
        return providers

    async def create_provider(self, payload: ProviderBase):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            provider_id = _generate_id()
            provider_data = payload.model_dump()
            provider_data["id"] = provider_id
            provider_data["model_config_data"] = {}
            provider = ProviderResponse(**provider_data)
            self._providers[provider_id] = provider
            return provider

        provider_id = _generate_id()
        provider_type = payload.type
        try:
            generated_config = self.lifecycle.provider_manager.generate_provider_config(
                provider_type, provider_id
            )
            if not generated_config:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to generate config for type {provider_type}",
                )
            if payload.config:
                generated_config["provider_config"].update(payload.config)
            if payload.name:
                generated_config["name"] = payload.name
            self.lifecycle.kira_config["providers"][provider_id] = generated_config
            self.lifecycle.kira_config.save_config()
            config_for_instantiation = generated_config.copy()
            self.lifecycle.provider_manager.set_provider(provider_id, config_for_instantiation)
            return ProviderResponse(
                id=provider_id,
                name=payload.name or provider_id,
                type=provider_type,
                status="active",
                config=generated_config["provider_config"],
                model_config_data=generated_config.get("model_config", {}),
                supported_model_types=self._get_supported_model_types(provider_id),
            )
        except Exception as e:
            logger.error(f"Error creating provider: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_provider(self, provider_id: str):
        if self.lifecycle and self.lifecycle.provider_manager:
            provider_inst = self.lifecycle.provider_manager.get_provider(provider_id)
            provider_info = self.lifecycle.provider_manager.get_provider_info(provider_id)
            if not provider_info:
                raise HTTPException(status_code=404, detail="Provider not found")
            config = self.lifecycle.kira_config.get("providers", {}).get(provider_id, {})
            return ProviderResponse(
                id=provider_info.provider_id,
                name=provider_info.provider_name,
                type=provider_info.provider_type,
                status="active" if provider_inst else "inactive",
                config=provider_info.provider_config,
                model_config_data=config.get("model_config", {}),
                supported_model_types=self._get_supported_model_types(provider_id),
            )
        provider = self._providers.get(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        return provider

    async def update_provider(self, provider_id: str, payload: ProviderBase):
        if self.lifecycle and self.lifecycle.provider_manager:
            config = self.lifecycle.kira_config.get("providers", {}).get(provider_id)
            if not config:
                raise HTTPException(status_code=404, detail="Provider not found")
            if payload.config:
                config["provider_config"].update(payload.config)
            if payload.name:
                config["name"] = payload.name
            self.lifecycle.kira_config["providers"][provider_id] = config
            self.lifecycle.kira_config.save_config()
            config_for_instantiation = config.copy()
            self.lifecycle.provider_manager.set_provider(provider_id, config_for_instantiation)
            return ProviderResponse(
                id=provider_id,
                name=config.get("name", provider_id),
                type=config.get("format", "unknown"),
                status="active",
                config=config["provider_config"],
                model_config_data=config.get("model_config", {}),
                supported_model_types=self._get_supported_model_types(provider_id),
            )
        provider = self._providers.get(provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
        updated = provider.model_copy(update=payload.model_dump())
        self._providers[provider_id] = updated
        return updated

    async def add_model(self, provider_id: str, payload: ModelCreateRequest):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=500, detail="Provider manager not available")
        model_type = payload.model_type
        model_id = payload.model_id
        if not model_type or not model_id:
            raise HTTPException(status_code=400, detail="model_type and model_id are required")
        success = self.lifecycle.provider_manager.register_model(
            provider_id=provider_id,
            model_type=model_type,
            model_id=model_id,
            config=payload.config or {},
        )
        if not success:
            raise HTTPException(status_code=400, detail="Failed to register model")
        return {"success": True}

    async def get_models(self, provider_id: str):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=500, detail="Provider manager not available")
        models = self.lifecycle.provider_manager.get_models(provider_id)
        return models

    async def update_model(
        self,
        provider_id: str,
        model_type: str,
        model_id: str,
        payload: ModelUpdateRequest,
    ):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=500, detail="Provider manager not available")
        success = self.lifecycle.provider_manager.update_model(
            provider_id=provider_id,
            model_type=model_type,
            model_id=model_id,
            config=payload.config or {},
        )
        if not success:
            raise HTTPException(status_code=404, detail="Model not found")
        return {"success": True}

    async def delete_model(self, provider_id: str, model_type: str, model_id: str):
        if not self.lifecycle or not self.lifecycle.provider_manager:
            raise HTTPException(status_code=500, detail="Provider manager not available")
        success = self.lifecycle.provider_manager.delete_model(
            provider_id=provider_id,
            model_type=model_type,
            model_id=model_id,
        )
        if not success:
            raise HTTPException(status_code=404, detail="Model not found")
        return {"success": True}

    async def delete_provider(self, provider_id: str):
        if self.lifecycle and self.lifecycle.provider_manager:
            found = False
            if provider_id in self.lifecycle.provider_manager._providers:
                del self.lifecycle.provider_manager._providers[provider_id]
                found = True
            if provider_id in self.lifecycle.kira_config.get("providers", {}):
                del self.lifecycle.kira_config["providers"][provider_id]
                self.lifecycle.kira_config.save_config()
                found = True
            if not found:
                raise HTTPException(status_code=404, detail="Provider not found")
            return None
        if provider_id not in self._providers:
            raise HTTPException(status_code=404, detail="Provider not found")
        self._providers.pop(provider_id, None)
        return None
