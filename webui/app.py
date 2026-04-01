"""
KiraAI WebUI Application
Provides a web-based admin panel for managing KiraAI system
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn

from core.lifecycle import KiraLifecycle
from core.utils.path_utils import get_data_path
from webui.utils import _get_or_generate_access_token
from webui.routes.auth import AuthRoutes
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


class KiraWebUI:
    """
    WebUI class for KiraAI admin panel
    Holds lifecycle instance for accessing system components
    """

    def __init__(self, lifecycle: KiraLifecycle):
        self.lifecycle = lifecycle
        self.access_token = _get_or_generate_access_token()
        self.app = FastAPI(
            title="KiraAI Admin Panel",
            description="Administration panel for KiraAI system",
            version="1.0.0",
            openapi_url="/api/openapi.json",
            docs_url="/api/docs",
        )

        # Paths
        self.webui_dir = Path(__file__).parent
        self.static_dir = self.webui_dir / "static"
        self.templates_dir = self.webui_dir / "templates"
        self.sticker_dir = get_data_path() / "sticker"

        # Setup CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # Mount static files
        if self.static_dir.exists():
            self.app.mount(
                "/static", StaticFiles(directory=str(self.static_dir)), name="static"
            )
        if self.sticker_dir.exists():
            self.app.mount(
                "/sticker", StaticFiles(directory=str(self.sticker_dir)), name="sticker"
            )

        # Mount Vue SPA dist assets at root level
        self.dist_dir = self.static_dir / "dist"
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

    def _register_routes(self):
        auth_routes = AuthRoutes(self.app, self.lifecycle, self.access_token, self.templates_dir)
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
        SettingsRoutes(self.app, self.lifecycle).register()

        # SPA catch-all must be registered last
        auth_routes.register_spa_fallback()

    async def run(self, host: str, port: int):
        config = uvicorn.Config(
            self.app,
            host=host,
            port=port,
            log_level="info",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        await server.serve()

    def get_app(self) -> FastAPI:
        """Get the FastAPI application instance"""
        return self.app


if __name__ == '__main__':
    from core.lifecycle import KiraLifecycle
    lifecycle = KiraLifecycle()
    webui = KiraWebUI(lifecycle)
    app = webui.get_app()
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5267,
    )
