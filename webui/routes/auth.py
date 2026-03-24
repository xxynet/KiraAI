from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse

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

    def get_routes(self):
        return [
            RouteDefinition(
                path="/login",
                methods=["GET"],
                endpoint=self.login_page,
                response_class=HTMLResponse,
                tags=["web"],
            ),
            RouteDefinition(
                path="/",
                methods=["GET"],
                endpoint=self.index,
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

    async def login_page(self):
        template_path = self.templates_dir / "login.html"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>Login page not found</h1>", status_code=404)

    async def index(self, request: Request):
        template_path = self.templates_dir / "index.html"
        if template_path.exists():
            with open(template_path, "r", encoding="utf-8") as f:
                return HTMLResponse(content=f.read())
        return HTMLResponse(content="<h1>Template not found</h1>", status_code=404)

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
