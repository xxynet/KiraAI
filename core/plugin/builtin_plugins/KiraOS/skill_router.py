"""
Skill Router — Progressive Disclosure for KiraAI.

Implements the same pattern as Claude's Skill system:
  - At startup: scan skill folders, load only lightweight manifest.json as Tool definitions
  - At runtime: when LLM triggers a skill, lazy-load instruction.md and return it
    as the tool result — the main LLM reads and executes the instruction in the
    SAME tool-loop turn, with ZERO extra API calls.

Each skill resides in its own directory under `data/skills/` and contains:
  - manifest.json   — compact tool definition (name, description, parameters)
  - instruction.md  — full execution rules, loaded only when triggered
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional, Callable

from core.logging_manager import get_logger

logger = get_logger("skill_router", "magenta")


class SkillInfo:
    """Parsed metadata for a single skill."""

    __slots__ = ("skill_id", "name", "description", "parameters", "instruction_path", "manifest_path", "root_path", "_instruction_cache")

    def __init__(self, skill_id: str, name: str, description: str, parameters: dict,
                 instruction_path: Path, manifest_path: Path, root_path: Path):
        self.skill_id = skill_id
        self.name = name
        self.description = description
        self.parameters = parameters
        self.instruction_path = instruction_path
        self.manifest_path = manifest_path
        self.root_path = root_path
        self._instruction_cache: str | None = None

    def load_instruction(self) -> str:
        """Read instruction.md — cached after first load."""
        if self._instruction_cache is not None:
            return self._instruction_cache
        if self.instruction_path.exists():
            self._instruction_cache = self.instruction_path.read_text(encoding="utf-8")
            return self._instruction_cache
        return ""

    def __repr__(self):
        return f"<Skill {self.name!r} @ {self.root_path}>"


class SkillRouter:
    """
    Scans a directory for skill folders, parses manifests,
    and provides a factory for creating tool executor functions.
    """

    def __init__(self, skills_dir: str | Path):
        self.skills_dir = Path(skills_dir)
        self.skills: Dict[str, SkillInfo] = {}

    def discover(self) -> list[SkillInfo]:
        """
        Scan skills_dir for subdirectories containing manifest.json.
        Returns a list of newly discovered SkillInfo objects.
        """
        self.skills.clear()
        discovered = []

        if not self.skills_dir.exists():
            self.skills_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created skills directory: {self.skills_dir}")
            return discovered

        if not self.skills_dir.is_dir():
            logger.warning(f"Skills path exists but is not a directory: {self.skills_dir}")
            return discovered

        for entry in sorted(self.skills_dir.iterdir()):
            if not entry.is_dir():
                continue
            if entry.name.startswith("_") or entry.name.startswith("."):
                continue

            manifest_path = entry / "manifest.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning(f"Failed to parse manifest in {entry.name}: {e}")
                continue

            if not isinstance(manifest, dict):
                logger.warning(f"Manifest for {entry.name} is not a JSON object, skipping")
                continue

            name = manifest.get("name")
            if not name:
                logger.warning(f"Skill {entry.name} has no 'name' in manifest, skipping")
                continue
            if not isinstance(name, str):
                logger.warning(f"Skill {entry.name} has non-string 'name': {name!r}, skipping")
                continue

            description = manifest.get("description", "")
            parameters = manifest.get("parameters", {"type": "object", "properties": {}, "required": []})
            if not isinstance(parameters, dict):
                logger.warning(f"Skill {entry.name} has invalid 'parameters' ({type(parameters).__name__}), using default")
                parameters = {"type": "object", "properties": {}, "required": []}
            instruction_path = entry / "instruction.md"

            if not instruction_path.exists():
                logger.warning(f"Skill {entry.name} has manifest but no instruction.md, skipping")
                continue

            skill = SkillInfo(
                skill_id=entry.name,
                name=name,
                description=description,
                parameters=parameters,
                instruction_path=instruction_path,
                manifest_path=manifest_path,
                root_path=entry,
            )
            if name in self.skills:
                existing = self.skills[name]
                logger.warning(
                    f"Duplicate skill name '{name}': {entry.name}/manifest.json "
                    f"conflicts with {existing.root_path.name}/manifest.json, skipping"
                )
                continue
            self.skills[name] = skill
            discovered.append(skill)
            logger.info(f"Discovered skill: {name} ({entry.name})")

        return discovered

    def get_skill(self, name: str) -> Optional[SkillInfo]:
        return self.skills.get(name)

    def build_instruction_prompt(self, skill: SkillInfo, args: dict) -> str:
        """
        Load instruction.md and substitute argument placeholders.
        Placeholders use {arg_name} format.
        """
        template = skill.load_instruction()
        if not template:
            return ""

        # Substitute known argument values
        for key, value in args.items():
            template = template.replace(f"{{{key}}}", str(value))

        return template
