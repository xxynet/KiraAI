import asyncio
import hashlib

import httpx
import pytest

from core.utils import github_api
from core.utils.github_api import parse_github_url, verify_sha256


def test_parse_standard_url():
    assert parse_github_url("https://github.com/owner/repo") == ("owner", "repo")


def test_parse_url_with_trailing_slash():
    assert parse_github_url("https://github.com/owner/repo/") == ("owner", "repo")


def test_parse_url_with_extra_path():
    assert parse_github_url("https://github.com/owner/repo/tree/main/sub") == ("owner", "repo")


def test_parse_shorthand():
    assert parse_github_url("owner/repo") == ("owner", "repo")


def test_parse_shorthand_with_spaces():
    assert parse_github_url("  owner/repo  ") == ("owner", "repo")


def test_parse_non_github_http_raises():
    with pytest.raises(ValueError, match="Not a GitHub URL"):
        parse_github_url("https://gitlab.com/owner/repo")


def test_parse_incomplete_path_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_github_url("owner")


def test_parse_empty_owner_raises():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_github_url("/repo")


def test_verify_sha256_match():
    data = b"hello world"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, digest) is True


def test_verify_sha256_with_prefix():
    data = b"hello world"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, f"sha256:{digest}") is True


def test_verify_sha256_mismatch():
    assert verify_sha256(b"hello", "0" * 64) is False


def test_verify_sha256_case_insensitive():
    data = b"test"
    digest = hashlib.sha256(data).hexdigest().upper()
    assert verify_sha256(data, digest) is True


def test_verify_sha256_strips_whitespace():
    data = b"test"
    digest = hashlib.sha256(data).hexdigest()
    assert verify_sha256(data, f"  {digest}  ") is True


def test_get_all_releases_follows_repository_transfer_redirect(monkeypatch):
    old_url = "https://api.github.com/repos/xxynet/KiraAI/releases?per_page=30&page=1"
    new_url = "https://api.github.com/repositories/1087096210/releases?per_page=30&page=1"
    requested_urls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if str(request.url) == old_url:
            return httpx.Response(301, headers={"Location": new_url}, request=request)
        if str(request.url) == new_url:
            return httpx.Response(200, json=[], request=request)
        raise AssertionError(f"Unexpected request: {request.url}")

    real_async_client = httpx.AsyncClient

    def mock_async_client(**kwargs):
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(github_api.httpx, "AsyncClient", mock_async_client)

    releases = asyncio.run(github_api.get_all_releases("xxynet", "KiraAI"))

    assert releases == []
    assert requested_urls == [old_url, new_url]

@pytest.mark.parametrize(
    ("failure_kind", "error_type"),
    [("network", httpx.ConnectError), ("status", httpx.HTTPStatusError),
     ("cancel", asyncio.CancelledError)],
)
def test_get_all_releases_propagates_page_failure_and_closes_client(
    monkeypatch, failure_kind, error_type,
):
    pages = []
    clients = []
    real_async_client = httpx.AsyncClient

    async def handler(request):
        page = int(request.url.params["page"])
        pages.append(page)
        if page == 1:
            return httpx.Response(200, json=[{"tag_name": "v1"}])
        if failure_kind == "network":
            raise httpx.ConnectError("request failed", request=request)
        if failure_kind == "cancel":
            raise asyncio.CancelledError("request cancelled")
        return httpx.Response(503)

    def mock_async_client(**kwargs):
        client = real_async_client(transport=httpx.MockTransport(handler), **kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(github_api.httpx, "AsyncClient", mock_async_client)
    with pytest.raises(error_type):
        asyncio.run(github_api.get_all_releases("owner", "repo", per_page=1))

    assert pages == [1, 2]
    assert len(clients) == 1
    assert clients[0].is_closed
