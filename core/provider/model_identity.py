"""Stable model identities and legacy reference resolution."""

import uuid


MODEL_CONFIG_VERSION = 2
DEFAULT_MODEL_TYPES = {
    "default_llm": "llm",
    "default_fast_llm": "llm",
    "default_vlm": "llm",
    "default_tts": "tts",
    "default_stt": "stt",
    "default_image": "image",
    "default_embedding": "embedding",
    "default_rerank": "rerank",
    "default_video": "video",
}


def generate_model_id(provider_config: dict) -> str:
    """Generate an identity unique across all model types in this provider."""
    existing = {
        model_id
        for models in (provider_config.get("model_config") or {}).values()
        if isinstance(models, dict)
        for model_id in models
    }
    if provider_config.get("model_config_version") == MODEL_CONFIG_VERSION:
        existing.update(
            alias
            for models in (provider_config.get("model_config") or {}).values()
            if isinstance(models, dict)
            for entry in models.values()
            if isinstance(entry, dict)
            for alias in entry.get("legacy_ids", [])
        )
    while True:
        model_id = uuid.uuid4().hex
        if model_id not in existing:
            return model_id


def resolve_model_entry(provider_config: dict, model_id: str, model_type=None):
    """Resolve an internal ID or an unambiguous legacy alias, within a known type."""
    if hasattr(model_type, "value"):
        model_type = model_type.value
    groups = [
        (kind, models)
        for kind, models in (provider_config.get("model_config") or {}).items()
        if isinstance(models, dict) and (model_type is None or kind == model_type)
    ]
    for kind, models in groups:
        if model_id in models and isinstance(models[model_id], dict):
            return kind, model_id, models[model_id]
    if provider_config.get("model_config_version") != MODEL_CONFIG_VERSION:
        return None
    matches = [
        (kind, internal_id, entry)
        for kind, models in groups
        for internal_id, entry in models.items()
        if isinstance(entry, dict) and model_id in entry.get("legacy_ids", [])
    ]
    return matches[0] if len(matches) == 1 else None


def resolve_model_reference(providers: dict, reference, model_type=None):
    """Normalize only existing references; preserve missing and ambiguous values."""
    if not isinstance(reference, str) or ":" not in reference:
        return reference
    provider_id, model_id = reference.split(":", 1)
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        return reference
    result = resolve_model_entry(provider, model_id, model_type)
    return f"{provider_id}:{result[1]}" if result else reference
