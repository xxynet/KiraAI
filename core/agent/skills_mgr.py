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

SKILLS_DIR = get_data_path() / "skills"
SKILLS_CONFIG = get_config_path() / "skills.json"


@dataclass
class SkillInfo:
    name: str
    description: str
    path: Path
    enabled: bool = True


class SkillsManager:
    def __init__(self):
        self.skills_info = self.scan_skill_dir()
        logger.info(f"Loaded skills: {[info.name for info in self.skills_info]}")

    def scan_skill_dir(self) -> list[SkillInfo]:
        skills_info = []
        for s in os.listdir(SKILLS_DIR):
            skill_path = SKILLS_DIR / s
            if skill_path.is_dir() and not s.startswith("_"):
                skill_info = self.parse_skill_info(skill_path)
                if skill_info:
                    skills_info.append(skill_info)
        return skills_info

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
            "Use a skill when the user names it explicitly or the situation clearly ",
            "matches the skill description\nBefore executing a skill, you MUST read its ",
            "`SKILL.md` file first via `read_file` tool\ne.g. if the path is ",
            "`data/skills/skill_name`, read `data/skills/skill_name/SKILL.md`\n",
            "DO NOT read a specific skill file if the user just asked what skills you have",
            "Available skills are listed below:\n"
        ))

        for s in skills_info:
            if not s.enabled:
                continue

            p.content += f"- **{s.name}**: {s.description}\n  Path: {str(s.path)}"

        return p

