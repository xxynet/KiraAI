from anthropic import AnthropicError

from core.provider import BaseProvider, ModelType, ProviderAPIError

from .model_clients import (
    AnthropicCompatibleLLMClient,
    build_anthropic_client,
)


class AnthropicProvider(BaseProvider):
    models = {ModelType.LLM: AnthropicCompatibleLLMClient}

    def __init__(self, provider_id, provider_name, provider_config):
        super().__init__(provider_id, provider_name, provider_config)

    async def get_llm_list(self) -> list[dict]:
        """Fetch all models exposed by an Anthropic-compatible Models API."""
        models: list[dict] = []
        try:
            async with build_anthropic_client(
                self.provider_config,
                timeout=10,
            ) as client:
                page = await client.models.list(limit=1000)
                while True:
                    for item in page.data:
                        model_id = getattr(item, "id", "")
                        if not model_id:
                            continue
                        models.append(
                            {
                                "id": model_id,
                                "name": getattr(item, "display_name", "")
                                or getattr(item, "name", "")
                                or model_id,
                                "description": getattr(item, "description", "") or "",
                            }
                        )

                    if not page.has_next_page():
                        break
                    page = await page.get_next_page()
        except AnthropicError as e:
            raise ProviderAPIError(str(e)) from e

        return models
