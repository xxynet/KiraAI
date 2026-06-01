from copy import deepcopy
from typing import Dict

from fastapi import Depends, HTTPException

from core.logging_manager import get_logger, setup_logging
from webui.routes.auth import require_auth
from webui.routes.base import RouteDefinition, Routes

logger = get_logger("webui", "blue")


class ConfigRoutes(Routes):
    def get_routes(self):
        return [
            RouteDefinition(
                path="/api/configuration",
                methods=["GET"],
                endpoint=self.get_configuration,
                tags=["configuration"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/configuration",
                methods=["POST"],
                endpoint=self.update_configuration,
                tags=["configuration"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    async def get_configuration(self):
        if not self.lifecycle or not getattr(self.lifecycle, "kira_config", None):
            raise HTTPException(status_code=500, detail="Configuration not available")
        config = self.lifecycle.kira_config
        bot_config = config.get("bot_config", {})
        models = config.get("models", {})
        providers_config = config.get("providers", {}) or {}
        providers = []
        provider_models: Dict[str, Dict] = {}
        for provider_id, provider_cfg in providers_config.items():
            provider_name = (
                provider_cfg.get("name")
                or provider_cfg.get("provider_config", {}).get("name")
                or provider_id
            )
            providers.append({"id": provider_id, "name": provider_name})
            model_config: Dict = {}
            if self.lifecycle and self.lifecycle.provider_manager:
                try:
                    models_from_manager = self.lifecycle.provider_manager.get_models(provider_id)
                    if models_from_manager:
                        model_config = models_from_manager
                except Exception as e:
                    logger.error(f"Error getting models for provider {provider_id}: {e}")
            if not model_config:
                model_config = provider_cfg.get("model_config", {}) or {}
            provider_models[provider_id] = model_config
        return {
            "configuration": {
                "bot_config": bot_config,
                "models": models,
                "logging": config.get("logging", {}),
                "adapters": config.get("adapters", {}),
                "network": config.get("network", {}),
            },
            "providers": providers,
            "provider_models": provider_models,
        }

    async def update_configuration(self, payload: Dict):
        if not self.lifecycle or not getattr(self.lifecycle, "kira_config", None):
            raise HTTPException(status_code=500, detail="Configuration not available")
        config = self.lifecycle.kira_config
        bot_config = payload.get("bot_config")
        models = payload.get("models")
        logging_config = payload.get("logging")
        adapters_config = payload.get("adapters")
        network_config = payload.get("network")
        updated = False
        if isinstance(bot_config, dict):
            config["bot_config"] = bot_config
            updated = True
        if isinstance(models, dict):
            config["models"] = models
            updated = True
        logging_changed = False
        if isinstance(logging_config, dict):
            old_logging = deepcopy(config.get("logging", {}))
            logging_changed = logging_config != old_logging
            if logging_changed:
                try:
                    setup_logging(
                        log_level=logging_config.get("log_level", "INFO"),
                        log_file_path=logging_config.get("log_file_path"),
                        log_file_max_size=logging_config.get("log_file_max_size", 10),
                    )
                    config["logging"] = logging_config
                    updated = True
                    logger.info("Logging configuration applied")
                except Exception as e:
                    logger.error(f"Failed to apply logging config, not saving: {e}")
        if isinstance(adapters_config, dict):
            config["adapters"] = adapters_config
            updated = True
        if isinstance(network_config, dict):
            config["network"] = network_config
            updated = True
        if updated:
            config.save_config()
            logger.info("Configuration saved")
        return {
            "status": "ok",
            "configuration": {
                "bot_config": config.get("bot_config", {}),
                "models": config.get("models", {}),
                "logging": config.get("logging", {}),
                "adapters": config.get("adapters", {}),
                "network": config.get("network", {}),
            },
        }
