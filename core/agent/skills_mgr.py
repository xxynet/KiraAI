import json
import os
import yaml

from typing import Optional, Literal
from pathlib import Path
from dataclasses import dataclass, field

from core.utils.path_utils import get_data_path, get_config_path
from core.logging_manager import get_logger
from core.prompt_manager import Prompt

logger = get_logger("skills", "green")


@dataclass
class SkillInfo:
    name: str
    description: str
    path: Path
    enabled: bool = True


class SkillsManager:
    def __init__(self):
        self.skills_dir = get_data_path() / "skills"
        self.skills_config = get_config_path() / "skills.json"
        self.skills_config_dict = self.get_skill_config_dict()
        self.skills_info = self.scan_skill_dir()
        logger.info(f"Loaded skills: {[info.name for info in self.skills_info]}")

    def scan_skill_dir(self) -> list[SkillInfo]:
        skills_info = []
        self.skills_config_dict = self.get_skill_config_dict()
        skills_config_dict = self.skills_config_dict


        for s in os.listdir(self.skills_dir):
            skill_path = self.skills_dir / s
            if skill_path.is_dir() and not s.startswith("_"):
                skill_info = self.parse_skill_info(skill_path)
                if not skill_info:
                    continue
                if skill_info.name in skills_config_dict:
                    enabled = skills_config_dict.get(skill_info.name, True)
                    if isinstance(enabled, bool):
                        skill_info.enabled = enabled

                skills_info.append(skill_info)

        return skills_info

    def get_skill_config_dict(self):
        skills_config_dict = {}
        if not self.skills_config.exists():
            self.skills_config.write_text("{}", encoding="utf-8")
        with open(self.skills_config, 'r', encoding="utf-8") as f:
            skills_config = f.read()
        try:
            skills_config_dict = json.loads(skills_config)
        except json.JSONDecodeError:
            logger.error("Error loading data/config/skills.json")
        return skills_config_dict

    def set_skill_enabled(self, skill_name: str, enabled: bool):
        for skill in self.skills_info:
            if skill.name == skill_name:
                if skill.enabled != enabled:
                    skill.enabled = enabled
                    self.skills_config_dict[skill_name] = enabled
                    with open(self.skills_config, 'w', encoding="utf-8") as f:
                        f.write(json.dumps(self.skills_config_dict, indent=4, ensure_ascii=False))
                    return True
                return False
        return False

    @staticmethod
    def parse_skill_info(skill_path: Path) -> Optional[SkillInfo]:
        skill_md = skill_path.resolve() / "SKILL.md"
        if not skill_md.exists():
            logger.error(f"SKILL.md not found in {skill_path}")
            return None

        try:
            with open(skill_md, 'r', encoding='utf-8') as f:
                text = f.read()

            parts = text.split('---')
            if len(parts) < 3:
                logger.warning(f'Invalid format in {skill_md}')
                return None

            frontmatter = parts[1]
            data = yaml.safe_load(frontmatter)
            if not data or not data.get('name') or not data.get('description'):
                logger.warning(f'Missing name or description in {skill_md}')
                return None

            return SkillInfo(
                name=data.get("name"),
                description=data.get("description"),
                path=skill_path
            )
        except Exception as e:
            logger.error(f'Failed to parse {skill_md}: {e}')
            return None

    def build_skills_prompt(self, skills_info: list[SkillInfo] = None) -> Prompt:
        if skills_info is None:
            skills_info = self.skills_info
        p = Prompt(
            name="skills",
            source="system",
            content="## Skills\n"
        )

        p.content += "".join((
            "You have **Skills**,reusable instruction bundles stored\n",
            "Before replying: scan description entries of the skills below.\n",
            "- If exactly one skill clearly applies: read its SKILL.md with `read_file` tool, then follow it.\n",
            "  e.g. if the path is `data/skills/skill_name`, read `data/skills/skill_name/SKILL.md`\n",
            "- If multiple could apply: choose the most specific one, then read/follow it.\n",
            "- If none clearly apply: do not read any SKILL.md.\n",
            "Constraints: never read more than one skill up front; only read after selecting.\n",
            "If you need to store files while executing skills, store to `data/files` for persistent ",
            "storage, `data/temp` for temporary storage, DO NOT directly store to current working directory\n",
            "DO NOT read a specific skill file if the user just asked what skills you have",
            "Available skills are listed below:\n"
        ))

        for s in skills_info:
            if not s.enabled:
                continue

            p.content += f"- **{s.name}**: {s.description}\n  Path: {str(s.path)}"

        return p

