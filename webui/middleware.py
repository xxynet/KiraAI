from __future__ import annotations

import json
import re

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
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
            or scope["path"] not in {PLUGIN_UPLOAD_PATH, "/api/plugins/tasks/install/upload"}
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


class PluginBridgeInjectionMiddleware(BaseHTTPMiddleware):
    """Inject the plugin Bridge and optional standalone context into page HTML."""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        prefix = "/page/plugin/"
        path = request.url.path
        if (
            not path.startswith(prefix)
            or request.method != "GET"
            or response.status_code != 200
            or "text/html" not in response.headers.get("content-type", "")
        ):
            return response

        body = b"".join([
            chunk if isinstance(chunk, bytes) else chunk.encode()
            async for chunk in response.body_iterator
        ])
        try:
            html = body.decode("utf-8")
        except UnicodeDecodeError:
            return Response(
                content=body, status_code=response.status_code,
                headers=dict(response.headers),
            )

        # Quoted greater-than signs belong to attribute values, not tag boundaries.
        tag_attributes = r"""(?:[^"'>]|"[^"]*"|'[^']*')*"""
        html_tag = re.compile(r"<html\b(" + tag_attributes + r")>", re.IGNORECASE)
        bootstrap = ""
        theme = request.query_params.get("theme")
        locale = request.query_params.get("locale")
        plugin_id, separator, page_route = path[len(prefix):].partition("/")
        if theme in {"light", "dark"} and locale in {"zh", "en"} and plugin_id and separator:
            context = {
                "pluginId": plugin_id,
                "pageRoute": page_route,
                "isDark": theme == "dark",
                "locale": locale,
            }
            # Escape markup delimiters so paths cannot terminate the JSON script.
            context_json = json.dumps(context, ensure_ascii=True).replace("<", r"\u003c")
            context_json = context_json.replace(">", r"\u003e").replace("&", r"\u0026")
            bootstrap = (
                '<script id="kira-plugin-page-context" type="application/json">'
                f"{context_json}</script>"
            )

            def set_html_attributes(match):
                attrs = re.sub(
                    r"""\s+([^\s=/>"']+)(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>"']+))?""",
                    lambda attr: "" if attr.group(1).lower() in {"data-theme", "lang"} else attr.group(0),
                    match.group(1),
                )
                return f'<html{attrs} data-theme="{theme}" lang="{locale}">'

            html = html_tag.sub(set_html_attributes, html, count=1)

        bridge_present = re.search(
            r"<script\b" + tag_attributes + r"""\ssrc\s*=\s*["']?/plugin-bridge\.js(?=["'?\s>])""",
            html, flags=re.IGNORECASE,
        )
        if not bridge_present:
            bootstrap += '<script src="/plugin-bridge.js"></script>'
        if bootstrap:
            head = re.search(r"<head\b" + tag_attributes + ">", html, re.IGNORECASE)
            if head:
                html = html[:head.end()] + bootstrap + html[head.end():]
            else:
                root = html_tag.search(html)
                if root:
                    html = html[:root.end()] + bootstrap + html[root.end():]
                else:
                    html = bootstrap + html

        # Personalized responses must not reuse cached context or old body validators.
        strip = {"content-length", "etag", "last-modified"}
        headers = {key: value for key, value in response.headers.items() if key.lower() not in strip}
        headers["cache-control"] = "no-store"
        return Response(
            content=html.encode("utf-8"), status_code=response.status_code,
            headers=headers, media_type="text/html",
        )
