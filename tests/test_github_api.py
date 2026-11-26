import asyncio
import gzip
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


class _TrackingStream(httpx.AsyncByteStream):
    """Async byte stream that records how many chunks were consumed and closure."""

    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.consumed = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk

    async def aclose(self) -> None:
        self.closed = True


def _mock_async_client(monkeypatch, handler) -> None:
    real_async_client = httpx.AsyncClient

    def mock_async_client(**kwargs):
        return real_async_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(github_api.httpx, "AsyncClient", mock_async_client)


@pytest.mark.anyio
async def test_download_asset_enforces_max_bytes(monkeypatch):
    body = b"x" * 2048

    async def handler(request):
        return httpx.Response(200, content=body, request=request)

    _mock_async_client(monkeypatch, handler)

    assert await github_api.download_asset("https://example.test/a.zip") == body
    assert await github_api.download_asset("https://example.test/a.zip", max_bytes=4096) == body
    assert await github_api.download_asset("https://example.test/a.zip", max_bytes=len(body)) == body
    with pytest.raises(ValueError, match="byte limit"):
        await github_api.download_asset("https://example.test/a.zip", max_bytes=1024)


@pytest.mark.anyio
async def test_download_asset_rejects_streamed_body_incrementally(monkeypatch):
    stream = _TrackingStream([b"a" * 600, b"b" * 600, b"sentinel"])

    async def handler(request):
        return httpx.Response(200, stream=stream, request=request)

    _mock_async_client(monkeypatch, handler)

    with pytest.raises(ValueError, match="byte limit"):
        await github_api.download_asset("https://example.test/a.zip", max_bytes=1024)
    assert stream.consumed == 2
    assert stream.closed


@pytest.mark.anyio
async def test_download_asset_rejects_oversized_content_length_before_reading(monkeypatch):
    stream = _TrackingStream([b"x" * 10])

    async def handler(request):
        return httpx.Response(200, stream=stream, headers={"Content-Length": "4096"}, request=request)

    _mock_async_client(monkeypatch, handler)

    with pytest.raises(ValueError, match="byte limit"):
        await github_api.download_asset("https://example.test/a.zip", max_bytes=1024)
    assert stream.consumed == 0
    assert stream.closed


@pytest.mark.anyio
async def test_download_asset_does_not_read_redirect_bodies(monkeypatch):
    body = b"zip archive"
    redirect_stream = _TrackingStream([b"r" * 4096])
    seen: list[tuple[str, str | None]] = []

    async def handler(request):
        seen.append((str(request.url), request.headers.get("Accept-Encoding")))
        if request.url.host == "github.test":
            return httpx.Response(
                302,
                stream=redirect_stream,
                headers={"Location": "https://codeload.test/a.zip"},
                request=request,
            )
        return httpx.Response(200, content=body, request=request)

    _mock_async_client(monkeypatch, handler)

    assert await github_api.download_asset("https://github.test/a.zip", max_bytes=1024) == body
    assert seen == [
        ("https://github.test/a.zip", "identity"),
        ("https://codeload.test/a.zip", "identity"),
    ]
    assert redirect_stream.consumed == 0
    assert redirect_stream.closed


@pytest.mark.anyio
async def test_download_asset_limits_redirect_count(monkeypatch):
    requests: list[str] = []

    async def handler(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "https://example.test/loop"}, request=request)

    _mock_async_client(monkeypatch, handler)

    with pytest.raises(ConnectionError, match="redirects"):
        await github_api.download_asset("https://example.test/loop", max_bytes=1024)
    # Initial request plus httpx's default limit of 20 redirects
    assert len(requests) == 21


@pytest.mark.anyio
async def test_download_asset_rejects_content_encoding_when_limited(monkeypatch):
    body = b"x" * 2048
    encoded = gzip.compress(gzip.compress(body))
    streams: list[_TrackingStream] = []

    async def handler(request):
        stream = _TrackingStream([encoded])
        streams.append(stream)
        return httpx.Response(
            200,
            stream=stream,
            headers={"Content-Encoding": "gzip, gzip"},
            request=request,
        )

    _mock_async_client(monkeypatch, handler)

    with pytest.raises(ValueError, match="Content-Encoding"):
        await github_api.download_asset("https://example.test/a.zip", max_bytes=4096)
    assert streams[0].consumed == 0
    assert streams[0].closed

    # Unbounded downloads keep transparent decoding for existing callers.
    assert await github_api.download_asset("https://example.test/a.zip") == body
