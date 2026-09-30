"""Plugin page sources and sidebar menu declarations."""

from enum import Enum
from typing import Dict, Optional, Union


class PageMenu:
    """Sidebar menu configuration for a plugin page.

    Args:
        label: Display text — a plain string or a dict of locale→translation
               (e.g. ``{"zh": "仪表盘", "en": "Dashboard"}``).
        icon:  Element Plus icon component name (e.g. ``"Monitor"``), or a
               path to an SVG file (``.svg``) relative to the plugin root
               (e.g. ``"assets/icon.svg"``) for a custom icon.
        order: Sort order in the sidebar (lower = higher, default 100).
    """

    def __init__(self, label: Union[str, Dict[str, str]], icon: Optional[str] = None,
                 order: int = 100):
        if not isinstance(label, (str, dict)):
            raise TypeError(f"label must be a str or dict, got {type(label).__name__}")
        if isinstance(label, str):
            if not label.strip():
                raise ValueError("label string must not be empty or whitespace")
        if isinstance(label, dict):
            for k, v in label.items():
                if not isinstance(k, str) or not isinstance(v, str):
                    raise TypeError(f"label dict keys and values must be strings, "
                                    f"got {type(k).__name__}: {type(v).__name__}")
                if not v.strip():
                    raise ValueError(f"label dict value for '{k}' must not be empty or whitespace")
        if icon is not None and not isinstance(icon, str):
            raise TypeError(f"icon must be a string if provided, got {type(icon).__name__}")
        if not isinstance(order, int) or isinstance(order, bool):
            raise TypeError(f"order must be an integer, got {type(order).__name__}")
        self.label: Union[str, Dict[str, str]] = label
        self.icon: Optional[str] = icon
        self.order: int = order

    def dict(self) -> dict:
        return {"label": self.label, "icon": self.icon, "order": self.order}


class PluginPageSource(Enum):
    FOLDER = "folder"
    URL = "url"
    HTML = "html"


class PluginPage:
    """Flexible plugin page descriptor.

    Use factory methods to create instances:

    - ``PluginPage.from_folder("./web")`` — serve a directory of static files
      (recommended for pre-built SPAs or plain HTML).
    - ``PluginPage.from_url("https://example.com")`` — redirect to an external URL.
    - ``PluginPage.from_html("<h1>Hello</h1>")`` — serve inline HTML.

    Use ``@register.page()`` decorator parameters to control *auth* and *menu*.
    """

    def __init__(self, source: PluginPageSource, source_value: str):
        self.source = source
        self.source_value = source_value

    @classmethod
    def from_folder(cls, path: str) -> "PluginPage":
        """Serve static files from a directory relative to the plugin root.

        Only files *inside* the plugin directory are accessible — any path
        that resolves outside the plugin root is rejected at registration time.

        Args:
            path: Directory path relative to the plugin root, e.g. ``"./web"``.
        """
        return cls(PluginPageSource.FOLDER, path)

    @classmethod
    def from_url(cls, url: str) -> "PluginPage":
        """Redirect the iframe to an external URL.

        Args:
            url: Full URL to redirect to, e.g. ``"https://example.com"``.
        """
        return cls(PluginPageSource.URL, url)

    @classmethod
    def from_html(cls, html: str) -> "PluginPage":
        """Serve a static HTML string.

        Args:
            html: Raw HTML content.
        """
        return cls(PluginPageSource.HTML, html)
