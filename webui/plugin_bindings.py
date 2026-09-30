"""Bind plugin WebUI declarations to a specific FastAPI application."""

import asyncio
import inspect
from functools import partial
from typing import Callable, List, Optional, TYPE_CHECKING

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.requests import Request

from core.logging_manager import get_logger
from core.plugin.pages import PluginPage, PluginPageSource
from core.utils.path_utils import is_within_directory

if TYPE_CHECKING:
    from core.plugin.plugin_registry import PluginManager


logger = get_logger("plugin_manager", "cyan")


class PluginPageStaticFiles(StaticFiles):
    """Serve a folder page with per-page auth, plugin state, and no-store."""

    def __init__(self, directory: str, is_enabled: Callable[[], bool],
                 need_auth: bool):
        super().__init__(directory=directory, html=True)
        self._is_enabled = is_enabled
        self._need_auth = need_auth

    async def __call__(self, scope, receive, send):
        async def send_with_no_store(message):
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["cache-control"] = "no-store"
            await send(message)

        if scope["type"] == "http":
            from webui.utils import verify_session_token

            request = Request(scope)
            if not self._is_enabled():
                response = HTMLResponse(
                    content='{"detail":"Plugin disabled"}', status_code=404,
                )
                await response(scope, receive, send_with_no_store)
                return
            if self._need_auth:
                token = None
                auth_header = request.headers.get("authorization", "")
                if auth_header.startswith("Bearer "):
                    token = auth_header.split(" ", 1)[1]
                if not token:
                    token = request.cookies.get("kira_token")
                if not token:
                    response = HTMLResponse(
                        content='{"detail":"Not authenticated"}', status_code=401,
                    )
                    await response(scope, receive, send_with_no_store)
                    return
                try:
                    verify_session_token(token, request.app.state)
                except Exception:
                    response = HTMLResponse(
                        content='{"detail":"Invalid token"}', status_code=401,
                    )
                    await response(scope, receive, send_with_no_store)
                    return
        await super().__call__(scope, receive, send_with_no_store)


class PluginStaticFiles(StaticFiles):
    """Serve static assets while their owning plugin is enabled."""

    def __init__(self, directory: str, is_enabled: Callable[[], bool],
                 html: bool = False):
        super().__init__(directory=directory, html=html)
        self._is_enabled = is_enabled

    async def __call__(self, scope, receive, send):
        if not self._is_enabled():
            raise HTTPException(status_code=404, detail="Plugin disabled")
        await super().__call__(scope, receive, send)


class PluginWebBindings:
    """Own Web route registrations without owning plugin declarations."""

    def __init__(self, manager: "PluginManager", app: Optional[FastAPI]):
        self.manager = manager
        self.app = app
        self._api_registered: set[str] = set()
        self._ws_registered: set[str] = set()
        self._pages_registered: set[str] = set()
        self._static_registered: set[str] = set()
        if app is not None:
            # WS endpoints resolve the manager here to avoid dependency deepcopy.
            app.state.plugin_manager = manager

    def register_apis(self, plugin_id: str) -> None:
        if self.app is None:
            return
        comp = self.manager.get_plugin_components().get(plugin_id)
        if not comp or not comp.api_routes:
            return

        # Routes already in FastAPI: the dynamic_endpoint always looks up the
        # current instance at call time, so re-init requires no action here.
        if plugin_id in self._api_registered:
            return

        import typing
        from fastapi import Depends, HTTPException
        from webui.routes.auth import require_auth

        self._api_registered.add(plugin_id)
        mgr = self.manager

        def _make_plugin_check(pid: str):
            async def check():
                if not mgr.is_plugin_enabled(pid):
                    raise HTTPException(status_code=404, detail="Plugin disabled")
            return check

        registered: List[str] = []

        for route in comp.api_routes:
            func = route["func"]
            func_name = func.__name__
            full_path = f"/api/plugin/{plugin_id}/{route['path'].lstrip('/')}"

            # Resolve annotations eagerly using the plugin module's own globals,
            # so `from __future__ import annotations` in plugins is handled correctly.
            try:
                resolved_hints = typing.get_type_hints(func, globalns=func.__globals__)
            except Exception:
                resolved_hints = {}

            params = [
                p.replace(annotation=resolved_hints.get(name, p.annotation))
                for name, p in inspect.signature(func).parameters.items()
                if name != "self"
            ]

            # Capture loop variables via default args to avoid closure issues.
            async def dynamic_endpoint(
                _pid=plugin_id, _fname=func_name, _mgr=mgr, **kwargs
            ):
                inst = _mgr.get_plugin_inst(_pid)
                if inst is None:
                    raise HTTPException(status_code=503, detail="Plugin not available")
                return await getattr(inst, _fname)(**kwargs)

            dynamic_endpoint.__signature__ = inspect.Signature(params)

            dependencies = [Depends(_make_plugin_check(plugin_id))]
            if route["auth"]:
                dependencies.append(Depends(require_auth))

            self.app.add_api_route(
                path=full_path,
                endpoint=dynamic_endpoint,
                methods=[route["method"]],
                dependencies=dependencies,
                tags=[f"plugin:{plugin_id}"],
                **route["kwargs"],
            )
            registered.append(full_path)

        if registered:
            logger.info(f"Registered {len(registered)} API routes from {plugin_id}: {registered}")

    def register_ws(self, plugin_id: str) -> None:
        """Register plugin WebSocket routes on the FastAPI app.

        Note: unlike HTTP endpoints, WS endpoints cannot use Depends with
        closures that capture non-picklable objects (e.g. PluginManager),
        because FastAPI deepcopies dependencies during WS dependency resolution.
        Instead, the manager is accessed via ``ws.app.state.plugin_manager``.
        """
        if self.app is None:
            return
        comp = self.manager.get_plugin_components().get(plugin_id)
        if not comp or not comp.ws_routes:
            return
        if plugin_id in self._ws_registered:
            return

        from fastapi import Depends, WebSocket
        from webui.routes.auth import require_ws_auth

        self._ws_registered.add(plugin_id)

        registered: List[str] = []

        for route in comp.ws_routes:
            func = route["func"]
            func_name = func.__name__
            pid = plugin_id
            full_path = f"/ws/plugin/{plugin_id}/{route['path'].lstrip('/')}"

            async def dynamic_endpoint(ws: WebSocket, _pid=pid, _fname=func_name):
                mgr = ws.app.state.plugin_manager
                if not mgr.is_plugin_enabled(_pid):
                    await ws.close(code=1011, reason="Plugin disabled")
                    return
                inst = mgr.get_plugin_inst(_pid)
                if inst is None:
                    await ws.close(code=1011, reason="Plugin not available")
                    return
                await getattr(inst, _fname)(ws)

            dependencies = []
            if route["auth"]:
                dependencies.append(Depends(require_ws_auth))

            self.app.add_api_websocket_route(
                path=full_path,
                endpoint=dynamic_endpoint,
                dependencies=dependencies,
            )
            registered.append(full_path)

        if registered:
            logger.info(f"Registered {len(registered)} WS routes from {plugin_id}: {registered}")

    def register_pages(self, plugin_id: str) -> None:
        """Resolve both page declaration forms before mounting them."""
        if self.app is None:
            return
        comp = self.manager.get_plugin_components().get(plugin_id)
        if not comp or not comp.pages or plugin_id in self._pages_registered:
            return
        self._pages_registered.add(plugin_id)
        registered: List[str] = []
        for page in comp.pages:
            page_obj = self._resolve_page(plugin_id, page)
            if page_obj is None:
                continue
            route_path = page["route"].lstrip('/')
            full_path = f"/page/plugin/{plugin_id}/{route_path}"
            if '{' in route_path and ':path}' in route_path:
                full_path = f"/page/plugin/{plugin_id}/" + "{path:path}"
            if self._mount_page(
                plugin_id, full_path, route_path, page_obj, page["auth"],
                deferred=page.get("page") is None,
            ):
                registered.append(full_path)
        if registered:
            logger.info(f"Registered {len(registered)} page routes from {plugin_id}: {registered}")

    def _resolve_page(self, plugin_id: str, page: dict) -> Optional[PluginPage]:
        page_obj = page.get("page")
        if page_obj is not None:
            return page_obj
        if not page.get("returns_plugin_page"):
            return None
        func = page["func"]
        inst = self.manager.get_plugin_inst(plugin_id)
        if inst is None:
            logger.error(f"Plugin {plugin_id}: instance not available for {func.__name__}")
            return None
        try:
            page_obj = getattr(inst, func.__name__)()
            if asyncio.iscoroutine(page_obj) or asyncio.isfuture(page_obj):
                logger.error(
                    f"Plugin {plugin_id}: {func.__name__}() is async but "
                    f"returns PluginPage — use sync def for from_folder"
                )
                if asyncio.iscoroutine(page_obj):
                    page_obj.close()
                return None
        except Exception as e:
            logger.error(f"Plugin {plugin_id}: failed to call {func.__name__}(): {e}")
            return None
        if not isinstance(page_obj, PluginPage):
            logger.error(f"Plugin {plugin_id}: {func.__name__}() did not return PluginPage")
            return None
        return page_obj

    def _mount_page(self, plugin_id: str, full_path: str, route_path: str,
                    page: PluginPage, need_auth: bool, deferred: bool) -> bool:
        from fastapi import Depends
        from starlette.responses import RedirectResponse
        from webui.routes.auth import require_auth

        if page.source == PluginPageSource.FOLDER:
            plugin_root = self.manager.get_plugin_module_path(plugin_id)
            if plugin_root is None:
                logger.error(f"Plugin {plugin_id}: no plugin root, cannot serve folder page")
                return False
            try:
                folder_path = (plugin_root / page.source_value).resolve()
                if not is_within_directory(plugin_root, folder_path):
                    logger.error(
                        f"Plugin {plugin_id}: folder path '{page.source_value}' "
                        f"escapes plugin root — rejected"
                    )
                    return False
            except (OSError, ValueError) as e:
                logger.error(f"Plugin {plugin_id}: invalid folder path: {e}")
                return False
            if not folder_path.is_dir():
                logger.error(f"Plugin {plugin_id}: folder not found: {page.source_value}")
                return False
            try:
                self.app.mount(
                    full_path,
                    PluginPageStaticFiles(
                        directory=str(folder_path),
                        is_enabled=partial(self.manager.is_plugin_enabled, plugin_id),
                        need_auth=need_auth,
                    ),
                    name=f"plugin:{plugin_id}:page:{route_path}",
                )
            except Exception as e:
                logger.error(f"Plugin {plugin_id}: failed to mount folder page: {e}")
                return False
            return True

        dependencies = [Depends(require_auth)] if need_auth else []
        if page.source == PluginPageSource.URL:
            async def redirect_endpoint(_url=page.source_value):
                return RedirectResponse(url=_url)
            endpoint = redirect_endpoint
        elif page.source == PluginPageSource.HTML:
            async def html_endpoint(_html=page.source_value):
                return HTMLResponse(content=_html)
            endpoint = html_endpoint
        else:
            return False
        # Preserve operation names used by the existing OpenAPI schema.
        if deferred:
            endpoint.__name__ = f"deferred_{endpoint.__name__}"
        self.app.add_api_route(
            path=full_path, endpoint=endpoint, methods=["GET"],
            dependencies=dependencies, tags=[f"plugin:{plugin_id}"],
        )
        return True

    def register_static(self, plugin_id: str) -> None:
        """Mount static assets using the existing plugin state policy."""
        if self.app is None:
            return
        comp = self.manager.get_plugin_components().get(plugin_id)
        if not comp or not comp.static_dirs or plugin_id in self._static_registered:
            return
        self._static_registered.add(plugin_id)
        plugin_root = self.manager.get_plugin_module_path(plugin_id)
        if not plugin_root:
            return
        registered: List[str] = []
        for static in comp.static_dirs:
            path_prefix = static["path"].lstrip('/')
            full_path = f"/static/plugin/{plugin_id}/{path_prefix}"
            dir_path = plugin_root / static["directory"]
            if not dir_path.exists() or not dir_path.is_dir():
                continue
            try:
                self.app.mount(
                    full_path,
                    PluginStaticFiles(
                        directory=str(dir_path),
                        is_enabled=partial(self.manager.is_plugin_enabled, plugin_id),
                        html=static.get("html", False),
                    ),
                    name=f"plugin_{plugin_id}_static_{path_prefix}",
                )
                registered.append(full_path)
            except Exception as e:
                logger.error(f"Failed to mount static dir {dir_path} for plugin {plugin_id}: {e}")
        if registered:
            logger.info(f"Registered {len(registered)} static directories from {plugin_id}: {registered}")

    def get_all_widgets(self) -> list:
        """Collect widget data from all enabled plugins (called per API request)."""
        from webui.models import OverviewWidget
        widgets = []
        for pid, comp in self.manager.get_plugin_components().items():
            if not self.manager.is_plugin_enabled(pid):
                continue
            inst = self.manager.get_plugin_inst(pid)
            if not inst:
                continue
            for meta in comp.widgets:
                wid = meta["widget_id"]
                func = comp.widget_funcs.get(wid)
                if not func:
                    continue
                try:
                    result = getattr(inst, func.__name__)()
                    content = str(result) if result is not None else ""
                    widgets.append(OverviewWidget(
                        widget_id=wid,
                        label=meta["label"],
                        content=content,
                        icon=meta["icon"],
                        color=meta["color"],
                        order=meta["order"],
                        size=meta["size"],
                    ))
                except Exception as e:
                    logger.error(f"Widget {wid} failed: {e}")
        widgets.sort(key=lambda w: w.order)
        return widgets

    def remove_routes(self, plugin_id: str) -> None:
        """Remove all FastAPI routes and mounts registered by a plugin.

        Cleans up API routes, page routes, and static file mounts from
        the web app, and resets the tracking sets so re-registration works.
        """
        self._api_registered.discard(plugin_id)
        self._ws_registered.discard(plugin_id)
        self._pages_registered.discard(plugin_id)
        self._static_registered.discard(plugin_id)

        if self.app is None:
            return

        tag_prefix = f"plugin:{plugin_id}"
        page_prefix = f"/page/plugin/{plugin_id}/"
        static_prefix = f"/static/plugin/{plugin_id}/"
        ws_prefix = f"/ws/plugin/{plugin_id}/"

        routes = self.app.routes
        filtered_routes = []
        removed = 0
        for route in routes:
            should_remove = False

            # API / page routes registered via add_api_route
            if hasattr(route, 'tags') and tag_prefix in (route.tags or []):
                should_remove = True
            # Page catch-all routes, static mounts, or WS routes
            elif hasattr(route, 'path') and (
                route.path.startswith(page_prefix)
                or route.path.startswith(static_prefix)
                or route.path.startswith(ws_prefix)
            ):
                should_remove = True

            if should_remove:
                removed += 1
            else:
                filtered_routes.append(route)

        if removed:
            routes.clear()
            routes.extend(filtered_routes)
            # Invalidate the OpenAPI schema cache so it gets regenerated
            self.app.openapi_schema = None
            logger.debug(f"Removed {removed} route(s) for plugin {plugin_id}")
