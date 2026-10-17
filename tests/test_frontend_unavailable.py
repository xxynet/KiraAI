"""Exercise missing-build recovery without starting the KiraAI lifecycle."""

import json
from pathlib import Path
from string import Template

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.routes.auth import AuthRoutes


@pytest.fixture
def recovery_client(tmp_path):
    app = FastAPI()
    dist = tmp_path / "dist"
    routes = AuthRoutes(app, None, "test-token", dist)
    routes.register()
    routes.register_spa_fallback()
    with TestClient(app) as client:
        yield client, dist


@pytest.mark.parametrize("path", ["/", "/login", "/overview"])
def test_missing_dist_returns_uncached_recovery_page(recovery_client, path):
    client, _ = recovery_client
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("text/html")
    assert "no-store" in response.headers["cache-control"]
    assert "WebUI 暂时无法打开" in response.text
    assert "WebUI is unavailable right now" in response.text
    assert "Frontend not built" not in response.text
    assert '<script src=' not in response.text
    assert '<link ' not in response.text


@pytest.mark.parametrize("path", ["/api/missing", "/assets/missing.js", "/monacoeditorwork/missing.js", "/page/missing"])
def test_recovery_does_not_replace_api_or_asset_errors(recovery_client, path):
    client, _ = recovery_client
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 404
    assert "WebUI is unavailable" not in response.text


@pytest.mark.parametrize("path", ["/", "/login", "/overview"])
def test_restored_index_is_served_on_next_request(recovery_client, path):
    client, dist = recovery_client
    assert client.get(path, headers={"Accept": "text/html"}).status_code == 503
    dist.mkdir()
    (dist / "index.html").write_text("<html>restored</html>", encoding="utf-8")
    response = client.get(path, headers={"Accept": "text/html"})
    assert response.status_code == 200
    assert response.text == "<html>restored</html>"
    assert "no-store" in response.headers["cache-control"]


def test_non_browser_requests_and_health_remain_unchanged(recovery_client):
    client, _ = recovery_client
    assert client.get("/").status_code == 404
    assert client.get("/overview").status_code == 404
    assert client.post("/overview", headers={"Accept": "text/html"}).status_code == 404
    assert client.get("/api/health").json()["status"] == "ok"


def test_recovery_locales_match_template():
    webui = Path(__file__).resolve().parents[1] / "webui"
    messages = {
        locale: json.loads((webui / "locales" / f"frontend_unavailable.{locale}.json").read_text(encoding="utf-8"))
        for locale in ("en", "zh")
    }
    assert messages["en"].keys() == messages["zh"].keys()
    template = (webui / "templates" / "frontend_unavailable.html").read_text(encoding="utf-8")
    identifiers = {
        match.group("named") or match.group("braced")
        for match in Template.pattern.finditer(template)
    }
    assert identifiers == set(messages["en"]) | {"page_title", "release_url"}
    for translations in messages.values():
        assert all(isinstance(value, str) and value.strip() for value in translations.values())
