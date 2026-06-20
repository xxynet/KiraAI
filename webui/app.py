"""
KiraAI WebUI Application
Provides a web-based admin panel for managing KiraAI system
"""
import mimetypes
import os
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
import uvicorn

from core.lifecycle import KiraLifecycle
from core.utils.path_utils import get_data_path, get_webui_dist_path
from webui.utils import _get_or_generate_access_token
from webui.routes.auth import AuthRoutes
from webui.routes.releases import ReleasesRoutes
from webui.routes.overview import OverviewRoutes
from webui.routes.logs import LogsRoutes
from webui.routes.personas import PersonasRoutes
from webui.routes.mcp import McpRoutes
from webui.routes.adapters import AdaptersRoutes
from webui.routes.plugins import PluginsRoutes
from webui.routes.providers import ProvidersRoutes
from webui.routes.sessions import SessionsRoutes
from webui.routes.config import ConfigRoutes
from webui.routes.stickers import StickersRoutes
from webui.routes.settings import SettingsRoutes
from webui.routes.skills import SkillsRoutes
from webui.routes.scope import ScopeRoutes
from webui.routes.system import SystemRoutes


class KiraWebUI:
    """
    WebUI class for KiraAI admin panel
    Holds lifecycle instance for accessing system components
    """

    def __init__(self, lifecycle: KiraLifecycle, dist_dir: Optional[Path] = None, disable_auth: bool = False):
        # Ensure proper MIME types on Windows (fixes .js served as text/plain)
        mimetypes.add_type("application/javascript", ".js")
        mimetypes.add_type("text/javascript", ".js")
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("application/json", ".json")
        mimetypes.add_type("image/svg+xml", ".svg")

        self.lifecycle = lifecycle
        self.disable_auth = disable_auth
        if disable_auth:
            self.access_token = "disabled"
        else:
            self.access_token = _get_or_generate_access_token()
        self.is_prod = os.environ.get("KIRA_ENV", "prod").lower() == "prod"
        fastapi_kwargs: dict = {
            "title": "KiraAI Admin Panel",
            "description": "Administration panel for KiraAI system",
            "version": "1.0.0",
        }
        if not self.is_prod:
            fastapi_kwargs["openapi_url"] = "/api/openapi.json"
            fastapi_kwargs["docs_url"] = "/api/docs"
        else:
            fastapi_kwargs["openapi_url"] = None
            fastapi_kwargs["docs_url"] = None
            fastapi_kwargs["redoc_url"] = None
        self.app = FastAPI(**fastapi_kwargs)
        # require_auth reads this to detect mode-mismatched JWTs.
        self.app.state.disable_auth = disable_auth
        self.app.state.access_token = self.access_token

        # Paths
        self.webui_dir = Path(__file__).parent
        self.dist_dir = dist_dir or get_webui_dist_path()
        self.sticker_dir = get_data_path() / "sticker"

        # Setup CORS.
        # Auth is carried by the Authorization: Bearer header (and a
        # same-origin, SameSite=Lax kira_token cookie for iframe/plugin pages),
        # so cross-origin *credentialed* access is never needed. Combining
        # allow_origins=["*"] with allow_credentials=True is the classic unsafe
        # CORS misconfiguration (Starlette reflects the request Origin and sets
        # Allow-Credentials: true, letting any site make credentialed calls and
        # read the responses). Keep the wildcard for convenience but disable
        # credentials so the wildcard stays a true, non-reflecting "*".
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Inject plugin-bridge.js into HTML responses served under /page/plugin/
        _BRIDGE_TAG = '<script src="/plugin-bridge.js"></script>'
        _BRIDGE_MARKER = '/plugin-bridge.js'

        class PluginBridgeInjectionMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                path = request.url.path
                if not path.startswith('/page/plugin/') or request.method != 'GET':
                    return response
                ct = response.headers.get('content-type', '')
                if 'text/html' not in ct:
                    return response
                body = b''
                async for chunk in response.body_iterator:
                    body += chunk if isinstance(chunk, bytes) else chunk.encode()
                try:
                    html = body.decode('utf-8')
                except UnicodeDecodeError:
                    return Response(content=body, status_code=response.status_code,
                                   headers=dict(response.headers))
                if _BRIDGE_MARKER in html:
                    return Response(content=html.encode('utf-8'), status_code=response.status_code,
                                   headers={k: v for k, v in response.headers.items()
                                            if k.lower() != 'content-length'},
                                   media_type='text/html')
                if '</head>' in html:
                    html = html.replace('</head>', _BRIDGE_TAG + '</head>', 1)
                elif '<body' in html:
                    idx = html.index('<body')
                    end = html.index('>', idx) + 1
                    html = html[:end] + _BRIDGE_TAG + html[end:]
                else:
                    html = _BRIDGE_TAG + html
                # Strip content-length + caching headers — body changed,
                # and stale cached copies would miss the bridge injection.
                strip = {'content-length', 'etag', 'last-modified'}
                hdrs = {k: v for k, v in response.headers.items()
                        if k.lower() not in strip}
                hdrs['cache-control'] = 'no-store'
                return Response(content=html.encode('utf-8'), status_code=response.status_code,
                               headers=hdrs, media_type='text/html')

        self.app.add_middleware(PluginBridgeInjectionMiddleware)

        # Serve the plugin bridge SDK directly so it works before frontend is built
        bridge_js_path = self.webui_dir / 'frontend' / 'public' / 'plugin-bridge.js'
        if bridge_js_path.exists():
            from fastapi.responses import FileResponse as _FileResponse
            @self.app.get('/plugin-bridge.js', include_in_schema=False)
            async def serve_bridge_js():
                return _FileResponse(bridge_js_path, media_type='application/javascript')

        # Mount user sticker library
        if self.sticker_dir.exists():
            self.app.mount(
                "/sticker", StaticFiles(directory=str(self.sticker_dir)), name="sticker"
            )

        # Mount Vue SPA build output. /assets holds content-hashed JS/CSS chunks,
        # /monacoeditorwork holds Monaco Editor web-worker bundles.
        dist_assets = self.dist_dir / "assets"
        dist_monaco = self.dist_dir / "monacoeditorwork"
        if dist_assets.exists():
            self.app.mount(
                "/assets", StaticFiles(directory=str(dist_assets)), name="dist_assets"
            )
        if dist_monaco.exists():
            self.app.mount(
                "/monacoeditorwork", StaticFiles(directory=str(dist_monaco)), name="dist_monaco"
            )

        # Register routes
        self._register_routes()

        # Store app reference on lifecycle so plugin_manager can pick it up
        # after it is initialized in init_and_run_system()
        self.lifecycle.webui_app = self.app

    def _register_routes(self):
        auth_routes = AuthRoutes(self.app, self.lifecycle, self.access_token, self.dist_dir, self.disable_auth)
        auth_routes.register()
        OverviewRoutes(self.app, self.lifecycle).register()
        LogsRoutes(self.app, self.lifecycle).register()
        PersonasRoutes(self.app, self.lifecycle).register()
        McpRoutes(self.app, self.lifecycle).register()
        AdaptersRoutes(self.app, self.lifecycle).register()
        PluginsRoutes(self.app, self.lifecycle).register()
        ProvidersRoutes(self.app, self.lifecycle).register()
        SessionsRoutes(self.app, self.lifecycle).register()
        ConfigRoutes(self.app, self.lifecycle).register()
        StickersRoutes(self.app, self.lifecycle).register()
        SkillsRoutes(self.app, self.lifecycle).register()
        ScopeRoutes(self.app, self.lifecycle).register()
        SettingsRoutes(self.app, self.lifecycle).register()
        SystemRoutes(self.app, self.lifecycle).register()
        ReleasesRoutes(self.app, self.lifecycle).register()

        # SPA catch-all must be registered last
        auth_routes.register_spa_fallback()

    async def run(self, host: str, port: int):
        config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="warning" if self.is_prod else "info",
            loop="asyncio",
            access_log=not self.is_prod,
        )
        self.server = uvicorn.Server(config)
        self.lifecycle.uvicorn_server = self.server
        await self.server.serve()

    def get_app(self) -> FastAPI:
        """Get the FastAPI application instance"""
        return self.app


# Note: this module is intentionally not a standalone entrypoint.
# `main.py` is the canonical launcher — it runs `KiraLauncher.start()` which
# awaits `KiraLifecycle.init_and_run_system()` before serving. Instantiating
# `KiraLifecycle` directly here and passing it to `uvicorn.run()` leaves
# `db_manager`, `provider_manager`, `plugin_manager`, etc. as `None` and
# most API routes will return 500.
