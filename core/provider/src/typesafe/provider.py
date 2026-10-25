from core.provider import BaseProvider, ModelType, ProviderAPIError

from .model_clients import TypeSafeDecisionClient, request_json


class TypeSafeProvider(BaseProvider):
    models = {ModelType.DECISION: TypeSafeDecisionClient}

    async def get_llm_list(self) -> list[dict]:
        """Expose decision models through the existing provider model-list interface."""
        data = await request_json(self.provider_config, "GET", "models", timeout=10)
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise ProviderAPIError("TypeSafe API returned an invalid model list")
        models = []
        for item in data["models"]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"]:
                raise ProviderAPIError("TypeSafe API returned an invalid model list")
            models.append({
                "id": item["name"], "name": item["name"],
                "description": item.get("description", ""),
            })
        return models
