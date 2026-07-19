from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from webui import models
from webui.models import OnboardingCompleteRequest
from webui.routes.auth import AuthRoutes


class Config(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


def make_routes(config=None, lifecycle=True):
    current_lifecycle = SimpleNamespace(kira_config=config) if lifecycle else None
    return AuthRoutes(FastAPI(), current_lifecycle, 'token', Path('.'))


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
