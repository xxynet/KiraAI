import asyncio
import socket

import httpx
import pytest

from core.utils import network


@pytest.mark.anyio
async def test_download_file_rejects_oversized_content_length(tmp_path, monkeypatch):
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"content-length": "6"}, content=b"123456")
    )
    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        network.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=transport, **kwargs),
    )
    target = tmp_path / "plugin.zip"

    with pytest.raises(ValueError, match="byte limit"):
        await network.download_file("https://example.test/plugin.zip", str(target), max_bytes=5)

    assert not target.exists()


@pytest.mark.anyio
@pytest.mark.parametrize("url,expected", [
    ("http://127.0.0.1/", False),
    ("http://[::1]/", False),
    ("http://[::ffff:127.0.0.1]/", False),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("http://100.64.0.1/", False),
    ("http://0.0.0.0/", False),
    ("http://10.0.0.1/", False),
    ("http://192.168.1.1/", False),
    ("ftp://1.1.1.1/", False),
    ("not-a-url", False),
    ("https://1.1.1.1/", True),
    ("http://8.8.8.8/", True),
    # Fake-IP compatibility applies to DNS answers, never literal addresses.
    ("http://198.18.1.121/", False),
    ("http://198.19.255.254/", False),
    ("http://0xc6120007/", False),
    ("http://3323068423/", False),
    ("http://2130706433/", False),
    ("http://0x7f000001/", False),
    # just outside 198.18.0.0/15: ordinary public address, still allowed
    ("http://198.20.0.1/", True),
])
async def test_is_public_http_url_ip_literals(url, expected):
    assert await network.is_public_http_url(url) is expected


def _fake_addrinfo(*ips):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443)) for ip in ips]


@pytest.mark.anyio
async def test_is_public_http_url_rejects_when_any_resolution_is_private(monkeypatch):
    async def fake_getaddrinfo(host, port, **kwargs):
        return _fake_addrinfo("93.184.216.34", "10.0.0.5")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await network.is_public_http_url("http://mixed.example/") is False


@pytest.mark.anyio
async def test_is_public_http_url_allows_fake_ip_only_resolution(monkeypatch):
    async def fake_getaddrinfo(host, port, **kwargs):
        return _fake_addrinfo("198.18.0.7")

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", fake_getaddrinfo)
    assert await network.is_public_http_url("http://fakeip.example/") is True
