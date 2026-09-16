import pytest

from webui.middleware import PLUGIN_UPLOAD_PATH, PluginUploadSizeLimitMiddleware


@pytest.mark.anyio
async def test_plugin_upload_limit_rejects_oversized_content_length():
    app_called = False
    messages = []

    async def app(scope, receive, send):
        nonlocal app_called
        app_called = True

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    middleware = PluginUploadSizeLimitMiddleware(app, max_bytes=5)
    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": PLUGIN_UPLOAD_PATH,
            "headers": [(b"content-length", b"6")],
        },
        receive,
        send,
    )

    assert not app_called
    assert messages[0]["status"] == 413


@pytest.mark.anyio
async def test_plugin_upload_limit_rejects_stream_without_content_length():
    messages = []
    chunks = iter([b"123", b"456"])

    async def app(scope, receive, send):
        await receive()
        await receive()

    async def receive():
        try:
            return {"type": "http.request", "body": next(chunks), "more_body": True}
        except StopIteration:
            return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    middleware = PluginUploadSizeLimitMiddleware(app, max_bytes=5)
    await middleware(
        {"type": "http", "method": "POST", "path": PLUGIN_UPLOAD_PATH, "headers": []},
        receive,
        send,
    )

    assert messages[0]["status"] == 413
