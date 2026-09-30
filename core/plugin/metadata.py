"""Plugin metadata and display state."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class PluginInfo:
    plugin_id: str
    display_name: str
    version: str = ""
    author: str = ""
    description: str = ""
    repo: Optional[str] = None
    locales: Dict[str, Dict[str, str]] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    core_version: Optional[str] = None
    icon: Optional[Path] = None
    icon_dark: Optional[Path] = None
    builtin: bool = False
    uninstallable: bool = False
    hidden: bool = False
    error: Optional[str] = None
    status: str = "pending"  # "pending" | "installing" | "loading" | "ready" | "disabled" | "error"
