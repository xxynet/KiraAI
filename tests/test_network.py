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
