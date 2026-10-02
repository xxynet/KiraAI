"""Model configuration migration, backups, and migration-specific persistence."""

import copy
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path

from core.config import ConfigError
from core.config.config_field import ConfigType, SectionField
from .model_identity import (
    DEFAULT_MODEL_TYPES, MODEL_CONFIG_VERSION, resolve_model_reference, validate_model_names,
)


LEGACY_MODEL_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://kira-ai.top/model-identity/v1")


def migrate_provider_models(provider: dict) -> bool:
    """Derive recoverable legacy identities without discarding model parameters."""
    version = provider.get("model_config_version")
    if version == MODEL_CONFIG_VERSION:
        groups = provider.get("model_config") or {}
        if not isinstance(groups, dict):
            raise ValueError("Invalid model configuration")
        for models in groups.values():
            validate_model_names(models)
        return False
    if version is not None:
        raise ValueError("Unsupported model configuration version")
    groups = provider.get("model_config") or {}
    if not isinstance(groups, dict):
        raise ValueError("Invalid model configuration")
    migrated = {}
    reserved_ids = {key for models in groups.values() if isinstance(models, dict) for key in models}
    for kind, models in groups.items():
        if not isinstance(models, dict):
            raise ValueError("Invalid model configuration group")
        migrated[kind] = {}
        for name, config in models.items():
            if not isinstance(config, dict):
                raise ValueError("Invalid model parameters")
            attempt = 0
            while True:
                identity = json.dumps([kind, name, attempt], ensure_ascii=False)
                model_id = uuid.uuid5(LEGACY_MODEL_NAMESPACE, identity).hex
                if model_id not in reserved_ids:
                    break
                attempt += 1
            reserved_ids.add(model_id)
            migrated[kind][model_id] = {
                "model_name": name,
                "config": config,
                "legacy_ids": [name],
            }
    for models in migrated.values():
        validate_model_names(models)
    provider["model_config"] = migrated
    provider["model_config_version"] = MODEL_CONFIG_VERSION
    return True


def migrate_model_config(config: dict) -> bool:
    """Migrate providers and typed default selections; safe to run repeatedly."""
    providers = config.get("providers") or {}
    if not isinstance(providers, dict):
        raise ValueError("Invalid providers configuration")
    models = config.get("models", {})
    if not isinstance(models, dict):
        raise ValueError("Invalid models configuration")
    changed = False
    for provider in providers.values():
        if isinstance(provider, dict):
            changed = migrate_provider_models(provider) or changed
    for key, kind in DEFAULT_MODEL_TYPES.items():
        if key in models:
            normalized = resolve_model_reference(providers, models[key], kind)
            if normalized != models[key]:
                models[key] = normalized
                changed = True
    return changed


def migrate_model_select_fields(config: dict, fields, providers: dict) -> bool:
    """Normalize schema-declared model selections, never unrelated strings."""
    if not isinstance(providers, dict):
        return False
    changed = False
    for field in fields:
        value = config.get(field.key)
        if isinstance(field, SectionField):
            if isinstance(value, dict):
                changed = migrate_model_select_fields(value, field.fields, providers) or changed
        elif field.type == ConfigType.ModelSelect or getattr(field, "source", None) == "model":
            kind = getattr(field, "model_type", None) or "llm"
            if isinstance(value, list):
                normalized = [resolve_model_reference(providers, item, kind) for item in value]
            else:
                normalized = resolve_model_reference(providers, value, kind)
            if normalized != value:
                config[field.key] = normalized
                changed = True
    return changed

def _back_up_config(path: Path):
    backup_path = path.with_name(path.name + ".model-identity-v1.bak")
    if backup_path.exists():
        return
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent,
            prefix=".model_backup-", suffix=".tmp", delete=False,
        ) as backup:
            temporary_path = backup.name
            with path.open("rb") as original:
                shutil.copyfileobj(original, backup)
        os.replace(temporary_path, backup_path)
    except OSError as e:
        raise ConfigError("failed to back up model configuration") from e
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def write_migrated_model_config(path: Path, config: dict):
    """Migration writes independently of the normal configuration save API."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.stem}-", suffix=".tmp", delete=False,
        ) as f:
            temporary_path = f.name
            json.dump(config, f, indent=4, ensure_ascii=False)
        os.replace(temporary_path, path)
    except (OSError, ValueError, TypeError) as e:
        raise ConfigError("failed to save migrated model configuration") from e
    finally:
        if temporary_path and os.path.exists(temporary_path):
            os.unlink(temporary_path)


def migrate_model_config_file(config: dict, path: Path) -> bool:
    """Persist a migration before updating live configuration; otherwise do nothing."""
    migrated = copy.deepcopy(dict(config))
    try:
        changed = migrate_model_config(migrated)
    except ValueError as e:
        raise ConfigError("failed to migrate model configuration") from e
    if not changed:
        return False
    path = Path(path)
    _back_up_config(path)
    write_migrated_model_config(path, migrated)
    config.clear()
    config.update(migrated)
    return True
