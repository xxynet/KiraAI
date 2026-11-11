"""Persist reusable subagent definitions independently of live sessions."""

import asyncio
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from core.prompt_manager import Prompt
from core.utils.path_utils import get_config_path

from .config import AgentExecutionConfig, SubAgentConfig, ToolExecutionConfig


class SubAgentPreset(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    name: str = Field(
        min_length=1,
        max_length=100,
    )
    description: str = Field(
        default="",
        max_length=2000,
    )
    instruction_source: Literal["persona", "custom"] = "persona"
    persona_id: str | None = Field(default=None, min_length=1)
    instruction: str = Field(
        default="",
        max_length=50000,
    )
    max_steps: int = Field(
        default=-1,
        ge=-1,
    )
    tool_mode: Literal["inherit", "exclude", "custom"] = "inherit"
    tools: list[str] = Field(
        default_factory=list,
        max_length=500,
    )
    enabled: bool = True
    model: str | None = None

    @field_validator("persona_id")
    @classmethod
    def validate_persona_id(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("Persona ID must not be blank")
        return value

    @field_validator("max_steps")
    @classmethod
    def validate_max_steps(cls, value: int) -> int:
        if value == 0:
            raise ValueError("max_steps must be -1 or a positive integer")
        return value

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        provider_id, separator, model_id = value.partition(":")
        if not separator or not provider_id.strip() or not model_id.strip():
            raise ValueError("Model must use provider_id:model_id")
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Preset name must not be blank")
        return value.strip()

    @field_validator("tools")
    @classmethod
    def validate_tools(cls, value: list[str]) -> list[str]:
        if any(not name.strip() for name in value):
            raise ValueError("Tool names must not be blank")
        return list(dict.fromkeys(name.strip() for name in value))

    def execution_config(
        self,
        tool_config: ToolExecutionConfig,
    ) -> SubAgentConfig:
        return SubAgentConfig(
            execution=AgentExecutionConfig(
                max_steps=self.max_steps,
                tool_config=tool_config,
            ),
            instruction=self.instruction if self.instruction_source == "custom" else "",
            instruction_source=self.instruction_source,
            persona_id=self.persona_id if self.instruction_source == "persona" else None,
            tool_mode=self.tool_mode,
            tool_names=tuple(self.tools) if self.tool_mode == "custom" else (),
            excluded_tools=tuple(self.tools) if self.tool_mode == "exclude" else (),
        )


class DuplicatePresetNameError(ValueError):
    pass


class SubAgentPresetStore:
    def __init__(self, path: Path | None = None):
        self.path = path if path is not None else get_config_path() / "subagent_presets.json"
        self._items: dict[str, SubAgentPreset] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            def read():
                if not self.path.exists():
                    return {}
                return json.loads(self.path.read_text(encoding="utf-8"))

            raw = await asyncio.to_thread(read)
            if not isinstance(raw, dict):
                raise TypeError("Subagent presets must be an object")
            self._items = {identity: SubAgentPreset.model_validate(item) for identity, item in raw.items()}

    def list(self, *, enabled_only: bool = False) -> list[dict]:
        return [
            {"id": identity, **preset.model_dump()}
            for identity, preset in self._items.items()
            if not enabled_only or preset.enabled
        ]

    def get(self, identity: str) -> SubAgentPreset:
        return self._items[identity].model_copy(deep=True)

    def get_enabled_by_name(self, name: str) -> tuple[str, SubAgentPreset]:
        for identity, preset in self._items.items():
            if preset.name == name:
                if not preset.enabled:
                    raise ValueError(f"Subagent preset is disabled: {name}")
                return identity, preset.model_copy(deep=True)
        raise ValueError(f"Unknown subagent preset: {name}")

    def has_available_presets(self) -> bool:
        return any(preset.enabled for preset in self._items.values())

    def build_presets_prompt(self) -> Prompt | None:
        presets = [preset for preset in self._items.values() if preset.enabled]
        if not presets:
            return None
        content = (
            "## Subagents\n"
            "You can delegate independent tasks to background subagents.\n"
            "Before delegating, scan the preset names and descriptions below and choose a suitable preset.\n"
            "Use `spawn_agent` with the exact `preset_name` from this list and a complete, self-contained `task`.\n"
            "The selected preset supplies the system prompt, model and tool settings.\n"
            "Delegation returns immediately. Completed turns are delivered to this session as system notices.\n\n"
            "Available subagent presets:\n"
        )
        for preset in presets:
            content += f"- **{preset.name}**: {preset.description}\n"
        return Prompt(
            content,
            name="subagent_presets",
            source="system",
            persist=False,
        )

    def _write(self, items: dict[str, SubAgentPreset]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        contents = json.dumps(
            {identity: preset.model_dump() for identity, preset in items.items()},
            ensure_ascii=False,
            indent=2,
        )
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                delete=False,
            ) as target:
                temporary = target.name
                target.write(contents)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)

    async def _commit(self, items: dict[str, SubAgentPreset]) -> None:
        write = asyncio.create_task(asyncio.to_thread(self._write, items))
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            await write
            self._items = items
            raise
        self._items = items

    async def save(self, preset: SubAgentPreset, identity: str | None = None) -> dict:
        async with self._lock:
            if identity is not None and identity not in self._items:
                raise KeyError(identity)
            if any(other_id != identity and other.name == preset.name for other_id, other in self._items.items()):
                raise DuplicatePresetNameError(f"A subagent preset named {preset.name!r} already exists")
            identity = identity or f"preset_{uuid.uuid4().hex}"
            items = {**self._items, identity: preset.model_copy(deep=True)}
            await self._commit(items)
            return {"id": identity, **preset.model_dump()}

    async def delete(self, identity: str) -> None:
        async with self._lock:
            items = dict(self._items)
            del items[identity]
            await self._commit(items)
