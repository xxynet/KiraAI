"""Plugin metadata and display state."""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class PluginInfo:
    plugin_id: str
    display_name: str
    version: str = ""
    author: str = ""
    description: str = ""
    repo: str | None = None
    locales: dict[str, dict[str, str]] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)
    core_version: str | None = None
    icon: Path | None = None
    icon_dark: Path | None = None
    builtin: bool = False
    uninstallable: bool = False
    hidden: bool = False
    error: str | None = None
    status: str = "pending"  # "pending" | "installing" | "loading" | "ready" | "disabled" | "error"
