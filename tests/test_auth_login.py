from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from webui.models import TokenLoginRequest
from webui.routes import auth as auth_routes
from webui.routes.auth import AuthRoutes


def make_routes(token="secret-token"):
    app = FastAPI()
    app.state.access_token = token
    app.state.disable_auth = False
    return AuthRoutes(app, None, token, Path(".")), app


def make_request(app, host="203.0.113.10"):
    return SimpleNamespace(app=app, client=SimpleNamespace(host=host))


@pytest.fixture
def clock(monkeypatch):
    state = {"now": 1000.0}
    monkeypatch.setattr(auth_routes, "monotonic", lambda: state["now"])
    return state


async def fail_login(routes, request, token="wrong"):
    with pytest.raises(HTTPException) as exc_info:
        await routes.token_login(TokenLoginRequest(access_token=token), request)
    return exc_info.value


@pytest.mark.anyio
async def test_login_failures_are_rate_limited_per_client(clock):
    routes, app = make_routes()
    request = make_request(app)

    for _ in range(auth_routes.LOGIN_FAILURE_LIMIT):
        assert (await fail_login(routes, request)).status_code == 401

    limited = await fail_login(routes, request)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    # Another client still gets ordinary 401s.
    assert (await fail_login(routes, make_request(app, host="198.51.100.7"))).status_code == 401

    clock["now"] = 1059.5
    assert (await fail_login(routes, request)).status_code == 429

    clock["now"] = 1060.0
    assert (await fail_login(routes, request)).status_code == 401


@pytest.mark.anyio
async def test_login_failures_are_rate_limited_across_many_clients(clock):
    routes, app = make_routes()

    hosts = auth_routes.LOGIN_GLOBAL_FAILURE_LIMIT // auth_routes.LOGIN_FAILURE_LIMIT
    for index in range(hosts):
        request = make_request(app, host=f"198.51.100.{index + 1}")
        for _ in range(auth_routes.LOGIN_FAILURE_LIMIT):
            assert (await fail_login(routes, request)).status_code == 401

    limited = await fail_login(routes, make_request(app, host="203.0.113.99"))
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "60"

    # The owner can still sign in while the global budget is exhausted.
    request = make_request(app, host="203.0.113.99")
    response = await routes.token_login(TokenLoginRequest(access_token="secret-token"), request)
    assert "kira_token=" in response.headers["set-cookie"]


@pytest.mark.anyio
async def test_retry_after_covers_both_failure_budgets(clock):
    routes, app = make_routes()
    first = make_request(app, host="203.0.113.10")
    for _ in range(auth_routes.LOGIN_FAILURE_LIMIT):
        assert (await fail_login(routes, first)).status_code == 401

    clock["now"] = 1050.0
    extra = auth_routes.LOGIN_GLOBAL_FAILURE_LIMIT - auth_routes.LOGIN_FAILURE_LIMIT
    for index in range(extra):
        request = make_request(app, host=f"198.51.100.{index + 1}")
        assert (await fail_login(routes, request)).status_code == 401

    clock["now"] = 1055.0
    limited = await fail_login(routes, first)
    assert limited.status_code == 429
    assert limited.headers["Retry-After"] == "5"


@pytest.mark.anyio
async def test_successful_login_clears_failure_budget(clock):
    routes, app = make_routes()
    request = make_request(app)

    for _ in range(auth_routes.LOGIN_FAILURE_LIMIT - 1):
        assert (await fail_login(routes, request)).status_code == 401

    response = await routes.token_login(TokenLoginRequest(access_token="secret-token"), request)
    assert "kira_token=" in response.headers["set-cookie"]

    for _ in range(auth_routes.LOGIN_FAILURE_LIMIT - 1):
        assert (await fail_login(routes, request)).status_code == 401