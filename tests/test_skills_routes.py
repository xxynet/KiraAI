"""Regression coverage for skill preview and editing."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from core.agent import skills_mgr
from webui.models import SkillContentUpdateRequest
from webui.routes.auth import require_auth
from webui.routes.skills import SkillsRoutes


ORIGINAL = '---\nname: demo\ndescription: Original description\n---\n# Hello\n\nSkill instructions.\n'
UPDATED = ORIGINAL.replace('Original description', 'Updated description').replace('Hello', '你好')
CONTENT_URL = '/api/skills/demo/content'


@pytest.fixture
def skill_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_mgr, 'get_data_path', lambda: tmp_path)
    monkeypatch.setattr(skills_mgr, 'get_config_path', lambda: tmp_path)
    skill_path = tmp_path / 'skills' / 'package-folder'
    skill_path.mkdir(parents=True)
    content_path = skill_path / 'SKILL.md'
    content_path.write_text(ORIGINAL, encoding='utf-8')
    (skill_path / 'reference.txt').write_text('Keep this reference', encoding='utf-8')
    manager = skills_mgr.SkillsManager()
    manager.set_skill_enabled('demo', False)
    manager.set_skill_scope('demo', 'allow', ['session-1'])
    app = FastAPI()
    routes = SkillsRoutes(app, SimpleNamespace(skills_manager=manager))
    routes.register()
    app.dependency_overrides[require_auth] = lambda: 'admin'
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client, manager=manager, routes=routes, content_path=content_path,
        )


def save(client, content=UPDATED, original=ORIGINAL):
    return client.put(CONTENT_URL, json={'content': content, 'original_content': original})


def test_preview_returns_full_markdown_and_frontmatter(skill_setup):
    response = skill_setup.client.get(CONTENT_URL)
    assert response.status_code == 200
    assert response.json() == {'content': ORIGINAL}


def test_save_updates_file_catalog_and_prompt_preserving_configuration(skill_setup):
    setup = skill_setup
    response = save(setup.client)
    assert response.status_code == 200
    assert response.json()['description'] == 'Updated description'
    assert setup.content_path.read_text(encoding='utf-8') == UPDATED
    assert (setup.content_path.parent / 'reference.txt').read_text() == 'Keep this reference'
    assert not list(setup.content_path.parent.glob('.skill-*.tmp'))
    item = setup.client.get('/api/skills').json()[0]
    assert item['description'] == 'Updated description'
    assert item['size_bytes'] == sum(p.stat().st_size for p in setup.content_path.parent.iterdir())
    assert item['enabled'] is False
    assert setup.manager.get_skill_scope('demo') == {'allow': ['session-1']}
    setup.manager.set_skill_enabled('demo', True)
    assert 'Updated description' in setup.manager.build_skills_prompt().content
    setup.manager.skills_info = setup.manager.scan_skill_dir()
    assert setup.manager.skills_info[0].description == 'Updated description'


@pytest.mark.parametrize('content', [
    '', '# No frontmatter', '---\nname: demo\n---\nBody',
    '---\n- demo\n- description\n---\nBody',
    '---\nname: demo\ndescription: [broken\n---\nBody',
    '---\nname: demo\ndescription: 123\n---\nBody',
    '---\nname: demo\ndescription: " "\n---\nBody',
    ORIGINAL.replace('name: demo', 'name: renamed'),
])
def test_invalid_edits_leave_file_and_runtime_unchanged(skill_setup, content):
    response = save(skill_setup.client, content)
    assert response.status_code == 400
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL
    assert skill_setup.manager.skills_info[0].description == 'Original description'


@pytest.mark.parametrize('payload', [{}, {'content': UPDATED}, {'content': 123, 'original_content': ORIGINAL}])
def test_save_requires_string_content_and_original_version(skill_setup, payload):
    assert skill_setup.client.put(CONTENT_URL, json=payload).status_code == 422
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL


def test_stale_editor_cannot_overwrite_external_changes(skill_setup):
    skill_setup.content_path.write_text(UPDATED, encoding='utf-8')
    response = save(skill_setup.client, ORIGINAL)
    assert response.status_code == 409
    assert skill_setup.content_path.read_text(encoding='utf-8') == UPDATED


def test_failed_replacement_keeps_original_and_cleans_temporary_file(skill_setup, monkeypatch):
    def fail_replace(*args):
        raise OSError('Simulated write failure')

    monkeypatch.setattr('webui.routes.skills.os.replace', fail_replace)
    assert save(skill_setup.client).status_code == 500
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL
    assert skill_setup.manager.skills_info[0].description == 'Original description'
    assert not list(skill_setup.content_path.parent.glob('.skill-*.tmp'))


@pytest.mark.parametrize('method', ['get', 'put'])
def test_content_requires_authentication(skill_setup, method):
    skill_setup.client.app.dependency_overrides.clear()
    kwargs = {'json': {'content': UPDATED, 'original_content': ORIGINAL}} if method == 'put' else {}
    assert getattr(skill_setup.client, method)(CONTENT_URL, **kwargs).status_code == 401


def test_missing_skill_and_content_are_not_created(skill_setup):
    assert skill_setup.client.get('/api/skills/missing/content').status_code == 404
    assert skill_setup.client.put('/api/skills/missing/content', json={
        'content': UPDATED, 'original_content': ORIGINAL,
    }).status_code == 404
    skill_setup.content_path.unlink()
    assert skill_setup.client.get(CONTENT_URL).status_code == 404
    assert save(skill_setup.client).status_code == 404
    assert not skill_setup.content_path.exists()


def test_content_rejects_registered_path_outside_skills_directory(skill_setup, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    content_path = outside / 'SKILL.md'
    content_path.write_text(ORIGINAL, encoding='utf-8')
    skill_setup.manager.skills_info[0].path = outside
    assert skill_setup.client.get(CONTENT_URL).status_code == 400
    assert save(skill_setup.client).status_code == 400
    assert content_path.read_text(encoding='utf-8') == ORIGINAL


def test_content_rejects_symlink_outside_skill_directory(skill_setup, tmp_path):
    outside = tmp_path / 'outside.md'
    outside.write_text(ORIGINAL, encoding='utf-8')
    link = skill_setup.content_path.parent / 'test-link'
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip('Creating symlinks is not supported by this environment')
    skill_setup.content_path.unlink()
    link.rename(skill_setup.content_path)
    assert skill_setup.client.get(CONTENT_URL).status_code == 400
    assert save(skill_setup.client).status_code == 400
    assert outside.read_text(encoding='utf-8') == ORIGINAL


def test_content_reports_unavailable_manager():
    app = FastAPI()
    SkillsRoutes(app).register()
    app.dependency_overrides[require_auth] = lambda: 'admin'
    with TestClient(app) as client:
        assert client.get(CONTENT_URL).status_code == 503
        assert save(client).status_code == 503


@pytest.mark.anyio
async def test_concurrent_editors_cannot_both_save_the_same_version(skill_setup):
    async def update(content):
        try:
            return await skill_setup.routes.update_skill_content('demo', SkillContentUpdateRequest(
                content=content, original_content=ORIGINAL,
            ))
        except HTTPException as exc:
            return exc.status_code

    outcomes = await asyncio.gather(update(UPDATED), update(UPDATED + '\nOther editor'))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert 409 in outcomes
