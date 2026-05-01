import httpx

from core.provider import BaseProvider, ModelType

from .model_clients import ModelScopeLLMClient, ModelScopeImageClient, ModelScopeEmbeddingClient


class ModelScopeProvider(BaseProvider):
    models = {
        ModelType.LLM: ModelScopeLLMClient,
        ModelType.IMAGE: ModelScopeImageClient,
        ModelType.EMBEDDING: ModelScopeEmbeddingClient
    }

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def get_llm_list(self) -> list[dict]:
        """
        Fetch available models from ModelScope API (GET /v1/models).
        """
        base_url = "https://api-inference.modelscope.cn/v1"
        api_key = self.provider_config.get("api_key", "")
        headers = {"Authorization": f"Bearer {api_key}"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()

        models = []
        for item in data.get("data", []):
            model_id = item.get("id", "")
            if not model_id:
                continue
            models.append({
                "id": model_id,
                "name": item.get("name", model_id),
                "description": item.get("description", ""),
            })
        return models
