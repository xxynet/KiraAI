"""Component declarations collected for each plugin."""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Literal, Optional, Union

from .pages import PageMenu, PluginPage
from .plugin_handlers import EventHandler, EventType, Priority


@dataclass
class PluginComponents:
    """Typed container for all components registered by a single plugin."""
    tools: Dict[str, dict] = field(default_factory=dict)
    tool_funcs: Dict[str, Callable] = field(default_factory=dict)
    tags: List[dict] = field(default_factory=list)
    tag_funcs: Dict[str, Callable] = field(default_factory=dict)
    hooks: List[EventHandler] = field(default_factory=list)
    pages: List[dict] = field(default_factory=list)
    page_funcs: Dict[str, Callable] = field(default_factory=dict)
    api_routes: List[dict] = field(default_factory=list)
    api_route_funcs: Dict[str, Callable] = field(default_factory=dict)
    ws_routes: List[dict] = field(default_factory=list)
    ws_route_funcs: Dict[str, Callable] = field(default_factory=dict)
    static_dirs: List[dict] = field(default_factory=list)
    widgets: List[dict] = field(default_factory=list)
    widget_funcs: Dict[str, Callable] = field(default_factory=dict)

    providers: Dict[str, dict] = field(default_factory=dict)
    adapters: Dict[str, dict] = field(default_factory=dict)
    def has_any(self) -> bool:
        return bool(self.tools or self.tags or self.hooks or self.pages
                    or self.api_routes or self.ws_routes or self.static_dirs or self.widgets or self.providers or self.adapters)

    def register_tool(self, name: str, description: str, params: dict, func: Callable):
        self.tools[name] = {
            "name": name,
            "description": description,
            "parameters": params,
            "func": func,
        }
        self.tool_funcs[name] = func

    def register_tag(self, name: str, description: str, func: Callable, parent: Optional[str] = "msg"):
        self.tags.append({"name": name, "description": description, "parent": parent})
        self.tag_funcs[name] = func

    def register_hook(self, handler: Callable, priority: Union[Priority, int],
                      event_type: EventType):
        eh = EventHandler(
            event_type=event_type,
            priority=priority,
            handler=handler,
            desc=handler.__doc__,
        )
        self.hooks.append(eh)

    def register_page(self, route: str, func: Callable, auth: bool = True,
                      menu: Optional[Union[dict, "PageMenu"]] = None,
                      page_obj: Optional["PluginPage"] = None,
                      returns_plugin_page: bool = False):
        if isinstance(menu, dict):
            menu = PageMenu(**menu)
        self.pages.append({
            "route": route,
            "func": func,
            "auth": auth,
            "menu": menu,
            "page": page_obj,
            "returns_plugin_page": returns_plugin_page,
        })
        if func is not None:
            self.page_funcs[func.__name__] = func

    def register_static(self, path: str, directory: str, html: bool = False):
        self.static_dirs.append({
            "path": path,
            "directory": directory,
            "html": html,
        })

    def register_api(self, method: str, path: str, func: Callable,
                     auth: bool = True, **kwargs):
        self.api_routes.append({
            "method": method.upper(),
            "path": path,
            "func": func,
            "auth": auth,
            "kwargs": kwargs,
        })
        self.api_route_funcs[func.__name__] = func

    def register_ws(self, path: str, func: Callable, auth: bool = True):
        self.ws_routes.append({
            "path": path,
            "func": func,
            "auth": auth,
        })
        self.ws_route_funcs[func.__name__] = func

    def register_widget(self, widget_id: str, label: Union[str, Dict[str, str]],
                        icon: str,
                        color: Literal["blue", "green", "purple", "yellow", "red", "gray"],
                        order: int,
                        size: Literal["small", "wide"],
                        func: Callable):
        self.widgets.append({
            "widget_id": widget_id,
            "label": label,
            "icon": icon,
            "color": color,
            "order": order,
            "size": size,
        })
        self.widget_funcs[widget_id] = func
    def register_provider(self, provider_format: str, metadata: dict) -> None:
        self.providers[provider_format] = metadata

    def unregister_provider(self, provider_format: str) -> Optional[dict]:
        return self.providers.pop(provider_format, None)

    def register_adapter(self, platform: str, metadata: dict) -> None:
        self.adapters[platform] = metadata

    def unregister_adapter(self, platform: str) -> Optional[dict]:
        return self.adapters.pop(platform, None)
