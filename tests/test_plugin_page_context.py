"""Regression coverage for standalone plugin page context injection."""

import json
import re
from urllib.parse import quote

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.testclient import TestClient

from webui.middleware import PluginBridgeInjectionMiddleware
from webui.routes.auth import require_auth


@pytest.fixture
def page_client(tmp_path):
    """Serve dynamic and folder plugin pages through the production middleware."""
    app = FastAPI()
    app.add_middleware(PluginBridgeInjectionMiddleware)
    app.state.page_html = (
        '<!doctype html><html lang="fr" data-theme="light" class="plugin">'
        '<head><script src="/plugin-bridge.js"></script>'
        '<script>window.pageStarted = true</script></head><body>Plugin</body></html>'
    )

    @app.get("/page/plugin/demo/secure", dependencies=[Depends(require_auth)])
    async def secure_page():
        return HTMLResponse(app.state.page_html)

    @app.get("/page/plugin/demo/redirect")
    async def redirect_page():
        return Response(status_code=307, headers={"Location": "https://example.com"})

    folder = tmp_path / "page"
    folder.mkdir()
    (folder / "index.html").write_text(app.state.page_html, encoding="utf-8")
    app.mount("/page/plugin/folder/ui", StaticFiles(directory=folder, html=True))

    @app.get("/page/plugin/{plugin_id}/{page_route:path}")
    async def page(plugin_id: str, page_route: str):
        return HTMLResponse(
            app.state.page_html,
            headers={"ETag": '"old-body"', "Last-Modified": "Wed, 21 Oct 2026 00:00:00 GMT"},
        )

    @app.get("/other")
    async def other_page():
        return HTMLResponse(app.state.page_html)

    @app.get("/api/plugin/demo/status")
    async def plugin_api():
        return {"ok": True}

    with TestClient(app) as client:
        yield client


def read_context(response):
    """Read the JSON bootstrap without executing page scripts."""
    match = re.search(
        r'<script id="kira-plugin-page-context" type="application/json">(.*?)</script>',
        response.text,
        flags=re.DOTALL,
    )
    assert match is not None
    return json.loads(match.group(1))


@pytest.mark.parametrize("theme", ["dark", "light"])
@pytest.mark.parametrize("locale", ["zh", "en"])
def test_standalone_page_receives_initial_context_before_existing_bridge(page_client, theme, locale):
    response = page_client.get(
        "/page/plugin/demo/dashboard", params={"theme": theme, "locale": locale},
    )

    assert response.status_code == 200
    assert read_context(response) == {
        "pluginId": "demo", "pageRoute": "dashboard",
        "isDark": theme == "dark", "locale": locale,
    }
    assert response.text.index('id="kira-plugin-page-context"') < response.text.index('src="/plugin-bridge.js"')
    assert response.text.count('src="/plugin-bridge.js"') == 1
    assert response.text.count("data-theme=") == 1
    assert response.text.count("lang=") == 1
    assert f'data-theme="{theme}"' in response.text
    assert f'lang="{locale}"' in response.text
    assert 'class="plugin"' in response.text
    assert response.headers["cache-control"] == "no-store"
    assert "etag" not in response.headers
    assert "last-modified" not in response.headers
    assert int(response.headers["content-length"]) == len(response.content)


@pytest.mark.parametrize("markup", [
    "<HTML><HEAD><title>Plugin</title></HEAD><BODY>Plugin</BODY></HTML>",
    "<html><body>Plugin</body></html>",
    "<div>Plugin fragment</div>",
])
def test_missing_bridge_is_inserted_after_context(page_client, markup):
    page_client.app.state.page_html = markup
    response = page_client.get("/page/plugin/demo/", params={"theme": "dark", "locale": "zh"})

    assert read_context(response)["pageRoute"] == ""
    assert response.text.index('id="kira-plugin-page-context"') < response.text.index('src="/plugin-bridge.js"')
    assert response.text.count('src="/plugin-bridge.js"') == 1


def test_folder_page_receives_context(page_client):
    response = page_client.get("/page/plugin/folder/ui/", params={"theme": "dark", "locale": "en"})

    assert response.status_code == 200
    assert read_context(response) == {
        "pluginId": "folder", "pageRoute": "ui/", "isDark": True, "locale": "en",
    }


@pytest.mark.parametrize("params", [
    {}, {"theme": "dark"}, {"locale": "zh"},
    {"theme": "invalid", "locale": "zh"},
    {"theme": "dark", "locale": '"><script>alert(1)</script>'},
])
def test_legacy_or_invalid_parameters_keep_parent_initialization(page_client, params):
    response = page_client.get("/page/plugin/demo/dashboard", params=params)

    assert response.status_code == 200
    assert 'id="kira-plugin-page-context"' not in response.text
    assert response.text.count('src="/plugin-bridge.js"') == 1
    assert 'lang="fr" data-theme="light"' in response.text


def test_context_paths_cannot_terminate_json_script(page_client):
    page_route = 'nested/</script><script>alert("context")</script>/中文'
    response = page_client.get(
        "/page/plugin/demo/" + quote(page_route, safe="/"),
        params={"theme": "dark", "locale": "zh"},
    )

    assert read_context(response)["pageRoute"] == page_route
    assert '<script>alert("context")</script>' not in response.text
    assert r"\u003c/script\u003e" in response.text


def test_preferences_do_not_bypass_authentication(page_client):
    response = page_client.get(
        "/page/plugin/demo/secure", params={"theme": "dark", "locale": "zh"},
    )
    assert response.status_code == 401
    assert "kira-plugin-page-context" not in response.text


def test_unrelated_responses_are_unchanged(page_client):
    response = page_client.get("/other?theme=dark&locale=zh")
    assert response.text == page_client.app.state.page_html
    assert page_client.get("/api/plugin/demo/status?theme=dark&locale=zh").json() == {"ok": True}
    response = page_client.get(
        "/page/plugin/demo/redirect?theme=dark&locale=zh", follow_redirects=False,
    )
    assert response.status_code == 307
    assert response.headers["location"] == "https://example.com"


@pytest.mark.parametrize("bridge_tag", [
    '<script src=/plugin-bridge.js></script>',
    '<script src="/plugin-bridge.js?v=1"></script>',
    "<script SRC='/plugin-bridge.js'></script>",
])
def test_existing_bridge_variants_are_not_duplicated(page_client, bridge_tag):
    page_client.app.state.page_html = f"<html><head>{bridge_tag}</head><body>Plugin</body></html>"
    response = page_client.get("/page/plugin/demo/dashboard?theme=dark&locale=zh")

    assert read_context(response)["isDark"] is True
    assert bridge_tag in response.text
    assert response.text.count("/plugin-bridge.js") == 1
    assert response.text.index('id="kira-plugin-page-context"') < response.text.index(bridge_tag)


def test_data_src_does_not_count_as_a_loaded_bridge(page_client):
    page_client.app.state.page_html = '<html><head><script data-src="/plugin-bridge.js"></script></head></html>'
    response = page_client.get("/page/plugin/demo/dashboard?theme=dark&locale=zh")

    assert read_context(response)["locale"] == "zh"
    assert '<script src="/plugin-bridge.js"></script>' in response.text
