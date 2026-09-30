"""Decorator entry points for declaring plugin components and event hooks."""

from typing import Callable, Dict, Literal, Optional, Union

from . import registry
from .pages import PageMenu, PluginPage
from .handlers import EventType, Priority


class RegisterDeco:

    @staticmethod
    def tool(name: str, description: str, params: dict):
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            registry._ensure_components(plugin_id).register_tool(name, description, params, func)
            return func
        return decorator

    @staticmethod
    def tag(name: str, description: str, parent: Optional[str] = "msg"):
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            registry._ensure_components(plugin_id).register_tag(name, description, func, parent)
            return func
        return decorator

    @staticmethod
    def page(route: str, auth: bool = True, menu: Optional[Union[dict, "PageMenu"]] = None):
        """Register a plugin page endpoint.

        Accepts a ``PluginPage`` object or a function that returns one::

            @register.page("/dashboard", menu=PageMenu(label={"zh": "仪表盘", "en": "Dashboard"}, icon="Monitor"))
            def dashboard(self):
                return PluginPage.from_folder("./web")

        Args:
            route: URL path relative to plugin prefix, e.g. ``"/dashboard"``.
                   Final route: ``/page/plugin/{plugin_id}{route}``
            auth:  Require JWT auth (default ``True``).
            menu:  Optional sidebar menu config — a ``PageMenu`` object or a dict
                   with keys ``label`` (str or locale dict), ``icon``, ``order``.
        """
        def decorator(obj):
            plugin_id = registry.get_obj_plugin_id(obj)
            comp = registry._ensure_components(plugin_id)

            if isinstance(obj, PluginPage):
                comp.register_page(route, None, auth, menu, page_obj=obj)
                return obj

            # Function that returns PluginPage — defer call to init time
            # where the plugin instance is available.
            comp.register_page(route, obj, auth, menu, returns_plugin_page=True)
            comp.page_funcs[obj.__name__] = obj
            return obj
        return decorator

    @staticmethod
    def static(path: str, directory: str, html: bool = False):
        """Register a static file directory.

        path:      URL path prefix relative to plugin, e.g., "/assets"
                   Final URL: /static/plugin/{plugin_id}{path}
        directory: Local directory path relative to plugin root
        html:      Try to serve index.html for directory requests
        """
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            registry._ensure_components(plugin_id).register_static(path, directory, html)
            return func
        return decorator

    @staticmethod
    def api(method: str, path: str, auth: bool = True, **kwargs):
        """Register a plugin API endpoint.

        method: HTTP method, e.g. "GET", "POST"
        path:   Path relative to the plugin prefix, e.g. "/status"
                Final route: /api/plugin/{plugin_id}{path}
        auth:   Require JWT auth (default True)
        kwargs: Forwarded to FastAPI add_api_route (response_model, summary, …)
        """
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            registry._ensure_components(plugin_id).register_api(method, path, func, auth, **kwargs)
            return func
        return decorator

    @staticmethod
    def ws(path: str, auth: bool = True):
        """Register a plugin WebSocket endpoint.

        path: Path relative to the plugin prefix, e.g. "/stream"
              Final route: /ws/plugin/{plugin_id}{path}
        auth: Require JWT auth during the WS handshake (default True).
              When enabled, ``ws.state.user`` is set before the endpoint runs.
        """
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            registry._ensure_components(plugin_id).register_ws(path, func, auth)
            return func
        return decorator

    @staticmethod
    def widget(label: Union[str, Dict[str, str]], icon: str = "Box",
               color: Literal["blue", "green", "purple", "yellow", "red", "gray"] = "blue",
               order: int = 100,
               size: Literal["small", "wide"] = "small"):
        """Register a widget on the Overview dashboard page.

        The decorated function is called on each ``GET /api/overview`` request
        and should return a plain string:
        - For small widgets: the display value (e.g. ``"42"``)
        - For wide widgets: HTML content (e.g. ``"<table>...</table>"``)

        Args:
            label: Widget title — plain string or locale dict
                   (e.g. ``{"zh": "消息数", "en": "Messages"}``).
            icon:  Element Plus icon name (e.g. ``"ChatDotRound"``).
                   Ignored for wide widgets.
            color: Theme color — one of blue/green/purple/yellow/red/gray.
            order: Sort position in the widget grid (lower = higher).
            size:  ``"small"`` (default, stat card) or ``"wide"`` (full-width).
        """
        def decorator(func: Callable):
            plugin_id = registry.get_obj_plugin_id(func)
            widget_id = f"{plugin_id}:{func.__name__}"
            registry._ensure_components(plugin_id).register_widget(
                widget_id, label, icon, color, order, size, func)
            return func
        return decorator


class OnEventDeco:

    @staticmethod
    def _register_hook(func: Callable, priority: Union[Priority, int], event_type: EventType):
        plugin_id = registry.get_obj_plugin_id(func)
        registry._ensure_components(plugin_id).register_hook(func, priority, event_type)

    def im_message(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_IM_MESSAGE)
            return func
        return decorator

    def message_buffered(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_MESSAGE_BUFFERED)
            return func
        return decorator

    def im_batch_message(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_IM_BATCH_MESSAGE)
            return func
        return decorator

    def llm_request(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_LLM_REQUEST)
            return func
        return decorator

    def llm_response(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_LLM_RESPONSE)
            return func
        return decorator

    def tool_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_TOOL_RESULT)
            return func
        return decorator

    def after_xml_parse(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.AFTER_XML_PARSE)
            return func
        return decorator

    def message_sent(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_MESSAGE_SENT)
            return func
        return decorator

    def step_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_STEP_RESULT)
            return func
        return decorator

    def final_result(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_FINAL_RESULT)
            return func
        return decorator

    def loaded(self, priority: Union[Priority, int] = Priority.MEDIUM):
        """Fired once after ALL plugins have been loaded (system-level lifecycle)."""
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_LOADED)
            return func
        return decorator

    def shutdown(self, priority: Union[Priority, int] = Priority.MEDIUM):
        """Fired once before system shutdown begins (system-level lifecycle)."""
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_SHUTDOWN)
            return func
        return decorator

    def exception(self, priority: Union[Priority, int] = Priority.MEDIUM):
        def decorator(func: Callable):
            self._register_hook(func, priority, EventType.ON_EXCEPTION)
            return func
        return decorator

    def custom_event(self, priority: Union[Priority, int] = Priority.MEDIUM, event_name: Optional[str] = None):
        def decorator(func: Callable):
            if event_name is not None:
                func._custom_event_name = event_name
            self._register_hook(func, priority, EventType.ON_CUSTOM_EVENT)
            return func
        return decorator


register = RegisterDeco()
on = OnEventDeco()

register_tool = register.tool
