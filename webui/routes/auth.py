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
    def __init__(self, app, lifecycle, access_token: str, dist_dir: Path):
        super().__init__(app, lifecycle)
        self.access_token = access_token
        self.dist_dir = dist_dir

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
        """Serve the Vue SPA.

        index.html is served for every browser navigation; vue-router then takes
        over client-side. Root-level files present in the dist (favicon.ico,
        robots.txt, etc.) are served directly so they are not hijacked by the
        HTML fallback. If the build is missing, returns a 404 hint pointing at
        the build command.
        """
        # Don't serve SPA for paths handled by dedicated mounts.
        if full_path.startswith(("api/", "sticker/", "assets/", "monacoeditorwork/")):
            raise HTTPException(status_code=404)
        # Serve single-segment root files from dist (favicon.ico, etc.).
        # Restrict to one path segment to avoid traversal.
        if full_path and "/" not in full_path and ".." not in full_path:
            candidate = self.dist_dir / full_path
            try:
                resolved = candidate.resolve()
                dist_resolved = self.dist_dir.resolve()
                if candidate.is_file() and str(resolved).startswith(str(dist_resolved)):
                    return FileResponse(candidate)
            except (OSError, ValueError):
                pass
        # Only serve the SPA for GET requests that accept HTML (browser navigations)
        if request and (request.method != "GET" or "text/html" not in request.headers.get("accept", "")):
            raise HTTPException(status_code=404)
        # SPA index.html must not be cached — asset filenames are content-hashed
        # in /assets, but index.html is the stable URL that points at the
        # current hash. If browsers cache it, users load the page with stale
        # asset references after a rebuild.
        no_cache_headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }
        spa_index = self.dist_dir / "index.html"
        if spa_index.exists():
            return FileResponse(spa_index, media_type="text/html", headers=no_cache_headers)
        return HTMLResponse(
            content="<h1>Frontend not built. Run <code>npm install &amp;&amp; npm run build</code> inside <code>webui/frontend/</code>.</h1>",
            status_code=503,
        )

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
