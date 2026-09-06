from datetime import timedelta
from pathlib import Path
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from core.config.default import VERSION
from webui.models import (
    LoginResponse,
    OnboardingCompleteRequest,
    OnboardingStatusResponse,
    OnboardingTokenSetupRequest,
    OnboardingTokenSetupResponse,
    TokenLoginRequest,
    VersionResponse,
)
from webui.routes.base import RouteDefinition, Routes
from webui.utils import (
    _access_token_fingerprint,
    _create_jwt_token,
    _is_token_setup_done,
    _mark_token_setup_done,
    _update_access_token,
    verify_session_token,
)


async def require_auth(
    request: Request,
    authorization: Optional[str] = Header(None),
) -> str:
    """Authenticate requests using JWT Bearer token.

    Beyond signature/expiry, also rejects JWTs whose auth_mode claim doesn't
    match the current server mode — so a sentinel JWT issued under
    --disable-webui-auth becomes invalid the moment the server restarts with
    auth enabled (and vice versa). Truth lives in the JWT, not in a client-side
    marker.

    Accepts kira_token cookie as a fallback for iframe/plugin page requests
    that cannot send Authorization headers.
    """
    token = None

    # 1. Try Authorization header (standard path for API calls)
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ", 1)[1]
    else:
        # 2. Fallback: try kira_token cookie (for iframe/plugin page requests)
        token = request.cookies.get("kira_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    # Signature/expiry + auth_mode + access-token (tv) binding, via the shared
    # helper so plugin page/static auth enforces the exact same claims.
    payload = verify_session_token(token, request.app.state)
    return payload.get("sub", "admin")


async def require_ws_auth(
    ws: WebSocket,
) -> str:
    """WebSocket auth dependency — validates token during the WS handshake.

    Token source (checked in order):
      1. ``?token=…`` query parameter  (most common for browser WS clients)
      2. ``Authorization: Bearer …`` header

    On failure the connection is accepted then immediately closed with
    code 4003 so the client sees a meaningful close code instead of a
    raw HTTP 403/401 that the browser cannot inspect.
    """
    token = ws.query_params.get("token")
    if not token:
        auth_header = ws.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        raise WebSocketException(code=4003, reason="Missing token")

    try:
        payload = verify_session_token(token, ws.app.state)
    except HTTPException:
        raise WebSocketException(code=4003, reason="Invalid token") from None
    user = payload.get("sub", "admin")
    ws.state.user = user
    return user


class AuthRoutes(Routes):
    def __init__(self, app, lifecycle, access_token: str, dist_dir: Path, disable_auth: bool = False):
        super().__init__(app, lifecycle)
        self.access_token = access_token
        self.dist_dir = dist_dir
        self.disable_auth = disable_auth

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
                path="/api/auth/config",
                methods=["GET"],
                endpoint=self.get_auth_config,
                tags=["auth"],
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
            RouteDefinition(
                path="/api/onboarding/status",
                methods=["GET"],
                endpoint=self.get_onboarding_status,
                response_model=OnboardingStatusResponse,
                tags=["onboarding"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/onboarding/complete",
                methods=["POST"],
                endpoint=self.complete_onboarding,
                response_model=OnboardingStatusResponse,
                tags=["onboarding"],
                dependencies=[Depends(require_auth)],
            ),
            RouteDefinition(
                path="/api/onboarding/setup-token",
                methods=["POST"],
                endpoint=self.setup_onboarding_token,
                response_model=OnboardingTokenSetupResponse,
                tags=["onboarding"],
                dependencies=[Depends(require_auth)],
            ),
        ]

    def register_spa_fallback(self):
        """Register SPA fallback middleware. Must be called AFTER all other routes.

        Uses middleware instead of a catch-all route so that dynamically added
        routes (e.g. plugin pages registered via set_web_app) are tried first.
        The middleware only intercepts 404 responses for browser GET requests.
        """
        dist_dir = self.dist_dir
        sticker_dir = self._get_sticker_dir()

        class SPAStaticFallbackMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request, call_next):
                response = await call_next(request)
                if response.status_code != 404:
                    return response
                if request.method != "GET":
                    return response
                full_path = request.url.path.lstrip("/")
                if full_path.startswith(("api/", "assets/", "monacoeditorwork/", "page/")):
                    return response
                # sticker mount: only exclude if the requested file actually exists
                # /sticker/xxx.gif → file exists → let mount handle it
                # /sticker/ or /sticker → SPA route → serve index.html
                if full_path.startswith("sticker/"):
                    remaining = full_path[len("sticker/"):]
                    if remaining and ".." not in remaining and (sticker_dir / remaining).exists():
                        return response
                # Serve single-segment root files from dist (favicon.ico, etc.)
                if full_path and "/" not in full_path and ".." not in full_path:
                    candidate = dist_dir / full_path
                    try:
                        resolved = candidate.resolve()
                        dist_resolved = dist_dir.resolve()
                        if resolved.is_file() and resolved.is_relative_to(dist_resolved):
                            return FileResponse(resolved)
                    except (OSError, ValueError):
                        pass
                # Only browser navigations should fall back to the SPA shell.
                # Root-level files must be served regardless of the request's
                # Accept header, since image and other asset requests do not
                # include text/html.
                if "text/html" not in request.headers.get("accept", ""):
                    return response
                no_cache_headers = {
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                }
                spa_index = dist_dir / "index.html"
                if spa_index.exists():
                    return FileResponse(spa_index, media_type="text/html", headers=no_cache_headers)
                return HTMLResponse(
                    content="<h1>Frontend not built. Run <code>npm install &amp;&amp; npm run build</code> inside <code>webui/frontend/</code>.</h1>",
                    status_code=503,
                )

        self.app.add_middleware(SPAStaticFallbackMiddleware)

    @staticmethod
    def _get_sticker_dir() -> Path:
        from core.utils.path_utils import get_data_path
        return get_data_path() / "sticker"

    async def serve_spa(self, request: Request = None, full_path: str = ""):
        """Serve the Vue SPA.

        index.html is served for every browser navigation; vue-router then takes
        over client-side. Root-level files present in the dist (favicon.ico,
        robots.txt, etc.) are served directly so they are not hijacked by the
        HTML fallback. If the build is missing, returns a 503 hint pointing at
        the build command.
        """
        # Don't serve SPA for paths handled by dedicated mounts.
        if full_path.startswith(("api/", "assets/", "monacoeditorwork/", "page/")):
            raise HTTPException(status_code=404)
        # sticker mount: only exclude if the requested file actually exists
        if full_path.startswith("sticker/"):
            remaining = full_path[len("sticker/"):]
            if remaining and ".." not in remaining and (self._get_sticker_dir() / remaining).exists():
                raise HTTPException(status_code=404)
        # Serve single-segment root files from dist (favicon.ico, etc.).
        # Restrict to one path segment to avoid traversal.
        if full_path and "/" not in full_path and ".." not in full_path:
            candidate = self.dist_dir / full_path
            try:
                resolved = candidate.resolve()
                dist_resolved = self.dist_dir.resolve()
                # Use is_relative_to so a sibling like /app/dist_evil/file
                # doesn't slip past a string-prefix check on /app/dist.
                if resolved.is_file() and resolved.is_relative_to(dist_resolved):
                    return FileResponse(resolved)
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

    async def get_auth_config(self):
        return {"auth_enabled": not self.disable_auth}

    def _get_onboarding_config(self) -> dict:
        config = getattr(self.lifecycle, "kira_config", None) if self.lifecycle else None
        if not isinstance(config, dict) or not config:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Configuration not available")
        onboarding = config.get("onboarding", {})
        return onboarding if isinstance(onboarding, dict) else {}

    async def get_onboarding_status(self):
        onboarding = self._get_onboarding_config()
        completed = bool(onboarding.get("completed", False))
        return OnboardingStatusResponse(
            completed=completed,
            version=onboarding.get("version", 1),
            token_setup_required=(
                not self.disable_auth
                and not completed
                and not _is_token_setup_done()
            ),
        )

    async def setup_onboarding_token(self, payload: OnboardingTokenSetupRequest, request: Request):
        """First-run access-token setup: replace the auto-generated token or skip.

        One-shot and only reachable before onboarding completes — afterwards
        token changes must go through /settings/change-token which re-verifies
        the old token. Setting a token rotates it in webui.json + app.state and
        re-mints the session JWT (and cookie) so the current login survives
        the rotation.
        """
        if self.disable_auth:
            raise HTTPException(status_code=400, detail="Cannot change token when auth is disabled")
        if self._get_onboarding_config().get("completed", False):
            raise HTTPException(status_code=400, detail="Onboarding already completed")
        if _is_token_setup_done():
            raise HTTPException(status_code=400, detail="Token setup already completed")

        if not payload.token or not payload.token.strip():
            _mark_token_setup_done()
            return OnboardingTokenSetupResponse(skipped=True)

        new_token = payload.token.strip()
        if len(new_token) < 6:
            raise HTTPException(status_code=400, detail="New token must be at least 6 characters")
        if new_token == "disabled":
            raise HTTPException(status_code=400, detail="The token 'disabled' is reserved and cannot be used")

        _update_access_token(new_token)
        request.app.state.access_token = new_token
        _mark_token_setup_done()
        access_token = _create_jwt_token(
            data={
                "sub": "admin",
                "auth_mode": "enabled",
                "tv": _access_token_fingerprint(new_token),
            },
            expires_delta=timedelta(days=5),
        )
        resp = JSONResponse(
            content=OnboardingTokenSetupResponse(skipped=False, access_token=access_token).model_dump()
        )
        resp.set_cookie(
            key="kira_token",
            value=access_token,
            path="/",
            httponly=True,
            samesite="lax",
            max_age=5 * 24 * 3600,  # 5 days, matches JWT expiry
        )
        return resp

    async def complete_onboarding(self, payload: OnboardingCompleteRequest):
        onboarding = self._get_onboarding_config()
        config = self.lifecycle.kira_config
        locale = config.get("locale", {})
        locale = dict(locale) if isinstance(locale, dict) else {}
        locale["lang"] = payload.lang
        locale["TZ"] = payload.timezone
        config["locale"] = locale
        config["onboarding"] = {
            **onboarding,
            "completed": True,
            "version": onboarding.get("version", 1),
        }
        config.save_config()
        return OnboardingStatusResponse(completed=True, version=config["onboarding"]["version"])

    async def health(self):
        return {"status": "ok", "lifecycle_available": self.lifecycle is not None}

    async def get_version(self):
        return VersionResponse(version=VERSION)

    async def token_login(self, payload: TokenLoginRequest, request: Request):
        current_token = request.app.state.access_token
        if payload.access_token != current_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid access token",
            )
        # auth_mode claim lets require_auth reject JWTs issued under the opposite
        # mode after a restart (e.g. a sentinel JWT cached in localStorage from a
        # prior --disable-webui-auth run, when auth is now back on).
        access_token = _create_jwt_token(
            data={
                "sub": "admin",
                "auth_mode": "disabled" if self.disable_auth else "enabled",
                # Bind the session to the current access token; rotating the
                # token changes this fingerprint and invalidates old JWTs.
                "tv": _access_token_fingerprint(current_token),
            },
            expires_delta=timedelta(days=5),
        )
        response = LoginResponse(access_token=access_token)
        resp = JSONResponse(content=response.model_dump())
        resp.set_cookie(
            key="kira_token",
            value=access_token,
            path="/",
            httponly=True,
            samesite="lax",
            max_age=5 * 24 * 3600,  # 5 days, matches JWT expiry
        )
        return resp

    async def logout(self):
        resp = Response(status_code=204)
        resp.delete_cookie("kira_token", path="/")
        return resp
