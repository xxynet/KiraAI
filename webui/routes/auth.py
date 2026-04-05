from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse

from core.config.default import VERSION
from webui.models import LoginResponse, TokenLoginRequest, VersionResponse
from webui.routes.base import RouteDefinition, Routes
from webui.utils import _create_jwt_token, _verify_jwt_token


async def require_auth(authorization: Optional[str] = Header(None)) -> str:
    """Authenticate requests using JWT Bearer token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = authorization.split(" ", 1)[1]
    payload = _verify_jwt_token(token)
    return payload.get("sub", "admin")


class AuthRoutes(Routes):
    def __init__(self, app, lifecycle, access_token: str, templates_dir: Path):
        super().__init__(app, lifecycle)
        self.access_token = access_token
        self.templates_dir = templates_dir
        self.dist_dir = Path(__file__).parent.parent / "static" / "dist"

    def get_routes(self):
        return [
            RouteDefinition(
                path="/login",
                methods=["GET"],
                endpoint=self.serve_spa,
                response_class=HTMLResponse,
                tags=["web"],
            ),
            RouteDefinition(
                path="/",
                methods=["GET"],
                endpoint=self.serve_spa,
                response_class=HTMLResponse,
                tags=["web"],
            ),
            RouteDefinition(
                path="/api/health",
                methods=["GET"],
                endpoint=self.health,
                tags=["system"],
            ),
            RouteDefinition(
                path="/api/version",
                methods=["GET"],
                endpoint=self.get_version,
                response_model=VersionResponse,
                tags=["system"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/auth/login",
                methods=["POST"],
                endpoint=self.token_login,
                response_model=LoginResponse,
                tags=["auth"],
            ),
            RouteDefinition(
                path="/api/auth/logout",
                methods=["POST"],
                endpoint=self.logout,
                status_code=status.HTTP_204_NO_CONTENT,
                tags=["auth"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    def register_spa_fallback(self):
        """Register SPA catch-all route. Must be called AFTER all other routes."""
        self.app.add_api_route(
            "/{full_path:path}",
            self.serve_spa,
            methods=["GET"],
            response_class=HTMLResponse,
            tags=["web"],
            include_in_schema=False,
        )

    async def serve_spa(self, request: Request = None, full_path: str = ""):
        """Serve Vue SPA index.html for all non-API, non-static routes"""
        # Don't serve SPA for static asset paths — let mounts handle them
        if full_path.startswith(("api/", "static/", "sticker/", "assets/", "monacoeditorwork/")):
            raise HTTPException(status_code=404)
        spa_index = self.dist_dir / "index.html"
        if spa_index.exists():
            return FileResponse(spa_index, media_type="text/html")
        # Fallback to legacy templates
        template_path = self.templates_dir / "index.html"
        if template_path.exists():
            return FileResponse(template_path, media_type="text/html")
        return HTMLResponse(content="<h1>Frontend not found. Run npm run build in webui/frontend/</h1>", status_code=404)

    async def health(self):
        return {"status": "ok", "lifecycle_available": self.lifecycle is not None}

    async def get_version(self):
        return VersionResponse(version=VERSION)

    async def token_login(self, payload: TokenLoginRequest):
        if payload.access_token != self.access_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )
        access_token = _create_jwt_token(
            data={"sub": "admin"},
            expires_delta=timedelta(days=5),
        )
        return LoginResponse(access_token=access_token)

    async def logout(self):
        return None
