from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from webui.routes.skills import SkillsRoutes


def _make_routes(skills_info):
    lifecycle = SimpleNamespace(
        skills_manager=SimpleNamespace(skills_info=skills_info),
    )
    return SkillsRoutes(lifecycle=lifecycle)


@pytest.mark.asyncio
async def test_get_skill_readme_returns_skill_md_content(tmp_path):
    skill_dir = tmp_path / "demo-skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# Demo Skill\n\nUsage instructions.", encoding="utf-8")

    routes = _make_routes([SimpleNamespace(name="demo-skill", path=skill_dir)])
    result = await routes.get_skill_readme("demo-skill")
    assert result == {"readme": "# Demo Skill\n\nUsage instructions."}


@pytest.mark.asyncio
async def test_get_skill_readme_returns_none_when_missing(tmp_path):
    skill_dir = tmp_path / "empty-skill"
    skill_dir.mkdir()

    routes = _make_routes([SimpleNamespace(name="empty-skill", path=skill_dir)])
    result = await routes.get_skill_readme("empty-skill")
    assert result == {"readme": None}


@pytest.mark.asyncio
async def test_get_skill_readme_raises_404_for_unknown_skill(tmp_path):
    routes = _make_routes([])
    with pytest.raises(HTTPException) as exc_info:
        await routes.get_skill_readme("nonexistent")
    assert exc_info.value.status_code == 404
