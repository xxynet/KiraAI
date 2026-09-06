from pathlib import Path
from types import SimpleNamespace

import json

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from webui import models
from webui.models import OnboardingCompleteRequest, OnboardingTokenSetupRequest
from webui.routes.auth import AuthRoutes
from webui.utils import _access_token_fingerprint, _verify_jwt_token


class Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


def make_routes(config=None, lifecycle=True, disable_auth=False):
    current_lifecycle = SimpleNamespace(kira_config=config) if lifecycle else None
    return AuthRoutes(FastAPI(), current_lifecycle, 'token', Path('.'), disable_auth)


def make_request():
    return SimpleNamespace(app=FastAPI())


@pytest.fixture
def patch_token_setup(monkeypatch):
    """Stub the webui.json-backed token-setup flag with an in-memory value."""
    state = {'done': False, 'updated_tokens': []}
    monkeypatch.setattr('webui.routes.auth._is_token_setup_done', lambda: state['done'])
    monkeypatch.setattr('webui.routes.auth._mark_token_setup_done', lambda: state.update(done=True))
    monkeypatch.setattr(
        'webui.routes.auth._update_access_token',
        lambda token: state['updated_tokens'].append(token),
    )
    return state


@pytest.mark.anyio
async def test_onboarding_requires_available_config():
    for routes in (make_routes(lifecycle=False), make_routes(config=None), make_routes(config='invalid')):
        with pytest.raises(HTTPException) as exc_info:
            await routes.get_onboarding_status()
        assert exc_info.value.status_code == 503


@pytest.mark.anyio
async def test_onboarding_status_and_completion_round_trip():
    config = Config({'onboarding': {'completed': False, 'version': 3}})
    routes = make_routes(config)

    before = await routes.get_onboarding_status()
    assert before.completed is False
    assert before.version == 3

    completed = await routes.complete_onboarding(
        OnboardingCompleteRequest(lang='zh', timezone='Asia/Shanghai'),
    )
    assert completed.completed is True
    assert completed.version == 3
    assert config['locale'] == {'lang': 'zh', 'TZ': 'Asia/Shanghai'}
    assert config['onboarding'] == {'completed': True, 'version': 3}
    assert config.save_calls == 1

    after = await routes.get_onboarding_status()
    assert after.completed is True
    assert after.version == 3


def test_onboarding_rejects_invalid_timezone():
    with pytest.raises(ValidationError, match='Invalid IANA timezone'):
        OnboardingCompleteRequest(lang='en', timezone='Not/A_Real_Timezone')


def test_onboarding_rejects_timezone_lookup_os_error(monkeypatch):
    def raise_os_error(_: str):
        raise OSError('Timezone data unavailable')

    monkeypatch.setattr(models, 'ZoneInfo', raise_os_error)
    with pytest.raises(ValidationError, match='Invalid IANA timezone'):
        OnboardingCompleteRequest(lang='en', timezone='Asia/Shanghai')


@pytest.mark.anyio
async def test_onboarding_status_reports_token_setup_required(patch_token_setup):
    config = Config({'onboarding': {'completed': False, 'version': 1}})
    routes = make_routes(config)

    pending = await routes.get_onboarding_status()
    assert pending.token_setup_required is True

    patch_token_setup['done'] = True
    visited = await routes.get_onboarding_status()
    assert visited.token_setup_required is False

    patch_token_setup['done'] = False
    config['onboarding']['completed'] = True
    finished = await routes.get_onboarding_status()
    assert finished.token_setup_required is False


@pytest.mark.anyio
async def test_onboarding_token_setup_not_required_when_auth_disabled(patch_token_setup):
    routes = make_routes(Config({'onboarding': {'completed': False}}), disable_auth=True)
    status = await routes.get_onboarding_status()
    assert status.token_setup_required is False

    with pytest.raises(HTTPException) as exc_info:
        await routes.setup_onboarding_token(OnboardingTokenSetupRequest(token='new-token'), make_request())
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_setup_token_skip_only_marks_done(patch_token_setup):
    routes = make_routes(Config({'onboarding': {'completed': False}}))

    response = await routes.setup_onboarding_token(OnboardingTokenSetupRequest(token=None), make_request())
    assert response.skipped is True
    assert response.access_token is None
    assert patch_token_setup['done'] is True
    assert patch_token_setup['updated_tokens'] == []


@pytest.mark.anyio
async def test_setup_token_rotates_token_and_remints_session(patch_token_setup):
    routes = make_routes(Config({'onboarding': {'completed': False}}))
    request = make_request()

    response = await routes.setup_onboarding_token(
        OnboardingTokenSetupRequest(token='  my-secret-token  '), request
    )
    body = json.loads(response.body)
    assert body['skipped'] is False
    assert patch_token_setup['updated_tokens'] == ['my-secret-token']
    assert request.app.state.access_token == 'my-secret-token'
    assert patch_token_setup['done'] is True

    payload = _verify_jwt_token(body['access_token'])
    assert payload['auth_mode'] == 'enabled'
    assert payload['tv'] == _access_token_fingerprint('my-secret-token')
    assert 'set-cookie' in {key.lower() for key in response.headers.keys()}
    assert 'kira_token=' in response.headers.get('set-cookie', '')


@pytest.mark.anyio
async def test_setup_token_validation_errors(patch_token_setup):
    routes = make_routes(Config({'onboarding': {'completed': False}}))

    for token, detail in (
        ('short', 'at least 6 characters'),
        ('disabled', 'reserved'),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await routes.setup_onboarding_token(OnboardingTokenSetupRequest(token=token), make_request())
        assert exc_info.value.status_code == 400
        assert detail in exc_info.value.detail
    assert patch_token_setup['done'] is False


@pytest.mark.anyio
async def test_setup_token_rejected_after_onboarding_completed(patch_token_setup):
    routes = make_routes(Config({'onboarding': {'completed': True}}))

    with pytest.raises(HTTPException) as exc_info:
        await routes.setup_onboarding_token(OnboardingTokenSetupRequest(token='new-token'), make_request())
    assert exc_info.value.status_code == 400
    assert patch_token_setup['updated_tokens'] == []
