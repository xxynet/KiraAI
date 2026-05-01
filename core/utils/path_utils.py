from pathlib import Path
from typing import Optional

# ─── Path overrides (set once via init_paths at startup) ─────────────────────
_data_dir: Optional[Path] = None
_webui_dir: Optional[Path] = None


def init_paths(
    data_dir: Optional[str] = None,
    webui_dir: Optional[str] = None,
) -> None:
    """
    Set path overrides from CLI arguments.  Must be called once at startup,
    before any other module reads paths.
    """
    global _data_dir, _webui_dir
    if data_dir is not None:
        _data_dir = Path(data_dir).resolve()
    if webui_dir is not None:
        _webui_dir = Path(webui_dir).resolve()


def get_root_path() -> Path:
    return Path().cwd().resolve()


def get_data_path() -> Path:
    """Return the data directory.  Defaults to ``<cwd>/data``."""
    return _data_dir if _data_dir is not None else get_root_path() / "data"


def get_webui_dist_path() -> Path:
    """Return the frontend dist directory.

    Defaults to ``<data_dir>/dist``.  Can be overridden with
    ``--webui-dir``
    """
    return _webui_dir if _webui_dir is not None else get_data_path() / "dist"


def get_config_path() -> Path:
    return get_data_path() / "config"
