from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.logging_manager import get_logger
from core.utils.path_utils import get_data_path
from .models import SubAgentConfig, ParentContextStrategy

logger = get_logger("subagent", "magenta")

SUBAGENT_CONFIG_PATH: Path = get_data_path() / "config" / "subagents.json"


class SubAgentRegistry:
    """管理 SubAgent 的注册、配置加载与生命周期"""

    def __init__(self):
        self._configs: Dict[str, SubAgentConfig] = {}
        self._instances: Dict[str, Any] = {}  # app_scope 缓存
        self._load_configs()

    def _load_configs(self):
        if not SUBAGENT_CONFIG_PATH.exists():
            return
        try:
            with open(SUBAGENT_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            for subagent_id, cfg in data.items():
                try:
                    try:
                        context_strategy = ParentContextStrategy(cfg.get("context_strategy", "none"))
                    except ValueError:
                        context_strategy = ParentContextStrategy.NONE

                    config = SubAgentConfig(
                        subagent_id=subagent_id,
                        name=cfg.get("name", subagent_id),
                        description=cfg.get("description", ""),
                        persona=cfg.get("persona", ""),
                        model_uuid=cfg.get("model_uuid"),
                        tools=cfg.get("tools", []),
                        max_steps=cfg.get("max_steps", 3),
                        timeout=cfg.get("timeout", 60.0),
                        context_strategy=context_strategy,
                        lifecycle=cfg.get("lifecycle", "on_demand"),
                        max_tool_loop=cfg.get("max_tool_loop", 2),
                        extra=cfg.get("extra", {}),
                    )
                    self._configs[subagent_id] = config
                except Exception as e:
                    logger.error(f"Failed to load SubAgent config '{subagent_id}': {e}")
        except Exception as e:
            logger.error(f"Failed to load SubAgent configs: {e}")

    def _save_configs(self) -> bool:
        try:
            SUBAGENT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            for subagent_id, cfg in self._configs.items():
                data[subagent_id] = {
                    "name": cfg.name,
                    "description": cfg.description,
                    "persona": cfg.persona,
                    "model_uuid": cfg.model_uuid,
                    "tools": cfg.tools,
                    "max_steps": cfg.max_steps,
                    "timeout": cfg.timeout,
                    "context_strategy": cfg.context_strategy.value,
                    "lifecycle": cfg.lifecycle,
                    "max_tool_loop": cfg.max_tool_loop,
                    "extra": cfg.extra,
                }
            temp_path = SUBAGENT_CONFIG_PATH.with_suffix(".tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=4, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            # Best-effort directory fsync; not all platforms support opening directories
            dir_fd = None
            try:
                if hasattr(os, "O_DIRECTORY"):
                    dir_fd = os.open(SUBAGENT_CONFIG_PATH.parent, os.O_RDONLY | os.O_DIRECTORY)
                    os.fsync(dir_fd)
            except (OSError, NotImplementedError) as exc:
                logger.debug(f"Directory fsync not performed: {exc}")
            finally:
                if dir_fd is not None:
                    os.close(dir_fd)
            os.replace(temp_path, SUBAGENT_CONFIG_PATH)
            return True
        except Exception as e:
            logger.error(f"Failed to save SubAgent configs: {e}", exc_info=True)
            return False

    def register(self, config: SubAgentConfig, persist: bool = True) -> bool:
        if not config.subagent_id:
            logger.error("SubAgent config must have a subagent_id")
            return False
        previous = self._configs.get(config.subagent_id)
        self._configs[config.subagent_id] = config
        if persist and not self._save_configs():
            # Rollback on save failure
            if previous is not None:
                self._configs[config.subagent_id] = previous
            else:
                del self._configs[config.subagent_id]
            logger.error(f"Failed to persist SubAgent '{config.subagent_id}', registration rolled back")
            return False
        logger.info(f"Registered SubAgent '{config.subagent_id}' ({config.name})")
        return True

    def unregister(self, subagent_id: str) -> bool:
        if subagent_id not in self._configs:
            return False
        removed_config = self._configs.pop(subagent_id)
        removed_instance = self._instances.pop(subagent_id, None)
        if not self._save_configs():
            # Rollback on save failure
            self._configs[subagent_id] = removed_config
            if removed_instance is not None:
                self._instances[subagent_id] = removed_instance
            logger.error(f"Failed to persist unregistration of SubAgent '{subagent_id}', rolled back")
            return False
        logger.info(f"Unregistered SubAgent '{subagent_id}'")
        return True

    def get_config(self, subagent_id: str) -> Optional[SubAgentConfig]:
        return self._configs.get(subagent_id)

    def list_configs(self) -> Dict[str, SubAgentConfig]:
        return dict(self._configs)

    def get_instance(self, subagent_id: str):
        return self._instances.get(subagent_id)

    def set_instance(self, subagent_id: str, instance):
        self._instances[subagent_id] = instance

    def remove_instance(self, subagent_id: str):
        self._instances.pop(subagent_id, None)
