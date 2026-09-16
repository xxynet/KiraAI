from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


PLUGIN_UPLOAD_PATH = "/api/plugins/install/upload"
MAX_PLUGIN_UPLOAD_BYTES = 50 * 1024 * 1024


class PluginUploadSizeLimitMiddleware:
    """Reject oversized plugin uploads before multipart parsing writes temp files."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"] != PLUGIN_UPLOAD_PATH
        ):
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for name, value in scope.get("headers", []) if name == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                if int(content_length) > self.max_bytes:
                    await self._send_too_large(send)
                    return
            except ValueError:
                pass

        received_bytes = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > self.max_bytes:
                    raise _RequestBodyTooLarge
            return message

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except _RequestBodyTooLarge:
            if not response_started:
                await self._send_too_large(send)

    @staticmethod
    async def _send_too_large(send: Send) -> None:
        body = b'{"detail":"Plugin archive exceeds the 50 MiB size limit"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _RequestBodyTooLarge(Exception):
    pass
