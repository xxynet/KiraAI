"""Regression coverage for skill preview and editing."""

import asyncio
import os
import stat
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from core.agent import skills_mgr
from webui.models import SkillFileUpdateRequest
from webui.routes.auth import require_auth
from webui.routes.skills import MAX_EDITABLE_FILE_BYTES, SkillsRoutes


ORIGINAL = '---\nname: demo\ndescription: Original description\n---\n# Hello\n\nSkill instructions.\n'
UPDATED = ORIGINAL.replace('Original description', 'Updated description').replace('Hello', '你好')
FILE_URL = '/api/skills/demo/file'
CONTENT_URL = FILE_URL + '?path=SKILL.md'


@pytest.fixture
def skill_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(skills_mgr, 'get_data_path', lambda: tmp_path)
    monkeypatch.setattr(skills_mgr, 'get_config_path', lambda: tmp_path)
    skill_path = tmp_path / 'skills' / 'package-folder'
    skill_path.mkdir(parents=True)
    content_path = skill_path / 'SKILL.md'
    content_path.write_bytes(ORIGINAL.encode('utf-8'))
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
    assert response.json() == {
        'path': 'SKILL.md', 'content': ORIGINAL, 'kind': 'text', 'reason': None,
        'size_bytes': len(ORIGINAL.encode('utf-8')),
    }


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


@pytest.mark.parametrize('content,code', [
    (ORIGINAL.replace('name: demo', 'name: renamed'), 'name_immutable'),
    ('# Missing frontmatter', 'missing_frontmatter'),
    ('---\nname: [broken\n---\nBody', 'invalid_yaml'),
    ('---\nname: demo\n---\nBody', 'invalid_metadata'),
])
def test_save_errors_expose_localizable_codes_and_original_diagnostics(skill_setup, content, code):
    response = save(skill_setup.client, content)
    assert response.status_code == 400
    detail = response.json()['detail']
    assert detail['code'] == code
    assert isinstance(detail['message'], str) and detail['message']
    if code == 'name_immutable':
        assert detail['message'] == 'Skill name cannot be changed'
    if code == 'invalid_yaml':
        assert 'Invalid SKILL.md frontmatter:' in detail['message']
        assert 'line' in detail['message']


@pytest.mark.parametrize('payload', [{}, {'content': UPDATED}, {'content': 123, 'original_content': ORIGINAL}])
def test_save_requires_string_content_and_original_version(skill_setup, payload):
    assert skill_setup.client.put(CONTENT_URL, json=payload).status_code == 422
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL


def test_stale_editor_cannot_overwrite_external_changes(skill_setup):
    skill_setup.content_path.write_text(UPDATED, encoding='utf-8')
    response = save(skill_setup.client, ORIGINAL)
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'file_changed'
    assert skill_setup.content_path.read_text(encoding='utf-8') == UPDATED


def test_failed_replacement_keeps_original_and_cleans_temporary_file(skill_setup, monkeypatch):
    def fail_replace(*args):
        raise OSError('Simulated write failure')

    monkeypatch.setattr('webui.routes.skills.os.replace', fail_replace)
    response = save(skill_setup.client)
    assert response.status_code == 500
    assert response.json()['detail']['code'] == 'write_failed'
    assert response.json()['detail']['diagnostic'] == 'Simulated write failure'
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL
    assert skill_setup.manager.skills_info[0].description == 'Original description'
    assert not list(skill_setup.content_path.parent.glob('.skill-*.tmp'))


@pytest.mark.parametrize('method', ['get', 'put'])
def test_content_requires_authentication(skill_setup, method):
    skill_setup.client.app.dependency_overrides.clear()
    kwargs = {'json': {'content': UPDATED, 'original_content': ORIGINAL}} if method == 'put' else {}
    assert getattr(skill_setup.client, method)(CONTENT_URL, **kwargs).status_code == 401


def test_missing_skill_and_content_are_not_created(skill_setup):
    assert skill_setup.client.get('/api/skills/missing/file?path=SKILL.md').status_code == 404
    assert skill_setup.client.put('/api/skills/missing/file?path=SKILL.md', json={
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
            return await skill_setup.routes.update_skill_file('demo', SkillFileUpdateRequest(
                content=content, original_content=ORIGINAL,
            ), path='SKILL.md')
        except HTTPException as exc:
            return exc.status_code

    outcomes = await asyncio.gather(update(UPDATED), update(UPDATED + '\nOther editor'))
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert 409 in outcomes


def test_file_list_includes_nested_and_hidden_files(skill_setup):
    root = skill_setup.content_path.parent
    (root / 'scripts').mkdir()
    (root / 'scripts' / 'run.py').write_text('print("hello")\n', encoding='utf-8')
    (root / '.settings').write_text('value=1\n', encoding='utf-8')
    response = skill_setup.client.get('/api/skills/demo/files')
    assert response.status_code == 200
    items = response.json()
    assert items[0]['path'] == 'SKILL.md'
    assert {item['path'] for item in items} == {
        'SKILL.md', 'reference.txt', 'scripts/run.py', '.settings',
    }
    assert all(item['size_bytes'] == (root / item['path']).stat().st_size for item in items)


@pytest.mark.parametrize('path', ['scripts/run.py', 'references/guide.md', 'references/SKILL.md', 'settings/config.json', '空 格/说明.txt'])
def test_nested_text_files_can_be_read_and_saved_without_skill_frontmatter(skill_setup, path):
    file_path = skill_setup.content_path.parent / path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    original = 'Original text\r\nNext line\r\n'
    updated = '更新内容\r\nNext line\r\n'
    file_path.write_bytes(original.encode('utf-8'))
    response = skill_setup.client.get(FILE_URL, params={'path': path})
    assert response.status_code == 200
    assert response.json()['content'] == original
    response = skill_setup.client.put(FILE_URL, params={'path': path}, json={
        'content': updated, 'original_content': original,
    })
    assert response.status_code == 200
    assert response.json()['description'] == 'Original description'
    assert file_path.read_bytes() == updated.encode('utf-8')
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL
    assert skill_setup.manager.skills_info[0].enabled is False
    assert skill_setup.manager.get_skill_scope('demo') == {'allow': ['session-1']}


@pytest.mark.parametrize('path', [
    '../outside.txt', 'scripts/../../outside.txt', '/absolute.txt',
    'C:/Windows/file.txt', 'C:file.txt', r'..\outside.txt', r'\\host\share\file',
    'SKILL.md:stream', '\x00.txt', '',
])
def test_all_file_operations_reject_unsafe_paths(skill_setup, path):
    client = skill_setup.client
    assert client.get(FILE_URL, params={'path': path}).status_code == 400
    assert client.get(FILE_URL + '/download', params={'path': path}).status_code == 400
    assert client.put(FILE_URL, params={'path': path}, json={
        'content': UPDATED, 'original_content': ORIGINAL,
    }).status_code == 400
    assert skill_setup.content_path.read_text(encoding='utf-8') == ORIGINAL


@pytest.mark.parametrize('path', ['scripts/missing.py', '.', 'scripts'])
def test_missing_files_and_directories_are_not_created_or_editable(skill_setup, path):
    (skill_setup.content_path.parent / 'scripts').mkdir()
    assert skill_setup.client.get(FILE_URL, params={'path': path}).status_code == 404
    assert skill_setup.client.put(FILE_URL, params={'path': path}, json={
        'content': UPDATED, 'original_content': '',
    }).status_code == 404


@pytest.mark.parametrize('name,data,kind', [
    ('asset.bin', b'\x00binary', 'binary'),
    ('legacy.txt', b'\xff\xfehello', 'binary'),
    ('photo.png', b'\x89PNG\r\n\x1a\n\x00image', 'image'),
    ('drawing.svg', b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', 'text'),
])
def test_non_text_files_can_be_inspected_and_downloaded_without_corruption(skill_setup, name, data, kind):
    file_path = skill_setup.content_path.parent / name
    file_path.write_bytes(data)
    response = skill_setup.client.get(FILE_URL, params={'path': name})
    assert response.status_code == 200
    assert response.json()['kind'] == kind
    if kind != 'text':
        assert response.json()['content'] is None
        assert skill_setup.client.put(FILE_URL, params={'path': name}, json={
            'content': 'overwrite', 'original_content': '',
        }).status_code == 415
    response = skill_setup.client.get(FILE_URL + '/download', params={'path': name})
    assert response.status_code == 200
    assert response.content == data
    assert response.headers['content-disposition'].startswith('attachment;')
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert file_path.read_bytes() == data


def test_large_files_require_download_and_cannot_be_overwritten(skill_setup):
    file_path = skill_setup.content_path.parent / 'large.txt'
    data = b'x' * (MAX_EDITABLE_FILE_BYTES + 1)
    file_path.write_bytes(data)
    response = skill_setup.client.get(FILE_URL, params={'path': 'large.txt'})
    assert response.status_code == 200
    assert response.json()['reason'] == 'too_large'
    assert response.json()['content'] is None
    assert skill_setup.client.put(FILE_URL, params={'path': 'large.txt'}, json={
        'content': '', 'original_content': '',
    }).status_code == 413
    assert skill_setup.client.put(FILE_URL, params={'path': 'reference.txt'}, json={
        'content': data.decode('utf-8'), 'original_content': 'Keep this reference',
    }).status_code == 413
    assert file_path.read_bytes() == data
    assert skill_setup.client.get(FILE_URL + '/download', params={'path': 'large.txt'}).content == data


def test_stale_nested_file_edits_are_rejected(skill_setup):
    file_path = skill_setup.content_path.parent / 'reference.txt'
    file_path.write_text('Modified elsewhere', encoding='utf-8')
    assert skill_setup.client.put(FILE_URL, params={'path': 'reference.txt'}, json={
        'content': 'My changes', 'original_content': 'Keep this reference',
    }).status_code == 409
    assert file_path.read_text(encoding='utf-8') == 'Modified elsewhere'


def test_skill_markdown_preserves_crlf_and_utf8_bom(skill_setup):
    original = '\ufeff' + ORIGINAL.replace('\n', '\r\n')
    updated = original.replace('Original description', 'Updated description')
    skill_setup.content_path.write_bytes(original.encode('utf-8'))
    assert skill_setup.client.get(CONTENT_URL).json()['content'] == original
    assert save(skill_setup.client, updated, original).status_code == 200
    assert skill_setup.content_path.read_bytes() == updated.encode('utf-8')
    assert skill_setup.manager.skills_info[0].description == 'Updated description'


@pytest.mark.skipif(os.name == 'nt', reason='POSIX executable permissions are not available on Windows')
def test_saving_script_preserves_executable_permissions(skill_setup):
    file_path = skill_setup.content_path.parent / 'run.sh'
    file_path.write_text('#!/bin/sh\necho old\n', encoding='utf-8')
    file_path.chmod(0o755)
    assert skill_setup.client.put(FILE_URL, params={'path': 'run.sh'}, json={
        'content': '#!/bin/sh\necho new\n', 'original_content': '#!/bin/sh\necho old\n',
    }).status_code == 200
    assert stat.S_IMODE(file_path.stat().st_mode) == 0o755


@pytest.mark.parametrize('url', ['/api/skills/demo/files', FILE_URL + '/download?path=SKILL.md'])
def test_file_listing_and_download_require_authentication(skill_setup, url):
    skill_setup.client.app.dependency_overrides.clear()
    assert skill_setup.client.get(url).status_code == 401
