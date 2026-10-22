"""Regression coverage for cache policy on the stable plugin bridge URL."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from webui.routes.auth import AuthRoutes


@pytest.fixture(params=["fallback", "direct"])
def static_client(tmp_path, request):
    app = FastAPI()
    routes = AuthRoutes(app, None, "test-token", tmp_path)
    routes.register()
    if request.param == "direct":
        @app.get("/plugin-bridge.js")
        async def bridge():
            return await routes.serve_spa(full_path="plugin-bridge.js")
    routes.register_spa_fallback()
    bridge = tmp_path / "plugin-bridge.js"
    bridge.write_text("window.bridgeVersion = 1;", encoding="utf-8")
    (tmp_path / "favicon.ico").write_bytes(b"icon")
    with TestClient(app) as client:
        yield client, bridge


@pytest.mark.parametrize("accept", ["*/*", "text/html"])
@pytest.mark.parametrize("url", ["/plugin-bridge.js", "/plugin-bridge.js?v=1"])
def test_plugin_bridge_requires_cache_revalidation(static_client, accept, url):
    client, _ = static_client
    response = client.get(url, headers={"Accept": accept})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == "window.bridgeVersion = 1;"


def test_updated_bridge_is_returned_with_old_cache_validators(static_client):
    client, bridge = static_client
    original = client.get("/plugin-bridge.js")
    bridge.write_text("window.bridgeVersion = 2; // updated", encoding="utf-8")

    response = client.get("/plugin-bridge.js", headers={
        "If-None-Match": original.headers["etag"],
        "If-Modified-Since": original.headers["last-modified"],
    })

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == "window.bridgeVersion = 2; // updated"
    assert response.headers["etag"] != original.headers["etag"]


def test_other_root_assets_keep_existing_cache_policy(static_client):
    client, _ = static_client
    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.content == b"icon"
    assert "cache-control" not in response.headers
