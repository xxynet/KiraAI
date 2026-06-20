import zipfile
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


# ─── Archive extraction safety (Zip-Slip guard) ──────────────────────────────

def is_within_directory(directory: Path, target: Path) -> bool:
    """Return True if ``target`` resolves to a path inside ``directory``.

    Guards against Zip-Slip / path traversal when extracting archives: a member
    named e.g. ``../../etc/passwd`` resolves outside the extraction root and must
    be rejected. Both paths are resolved (``..`` normalized) before comparison,
    so it does not require the target to exist.
    """
    directory = Path(directory).resolve()
    target = Path(target).resolve()
    return target == directory or directory in target.parents


def safe_extract_zip(zip_file: zipfile.ZipFile, dest_dir: Path) -> None:
    """Extract every member of ``zip_file`` into ``dest_dir`` safely.

    Validates each member with :func:`is_within_directory` before extracting and
    raises ``ValueError`` on the first member whose resolved path would escape
    ``dest_dir``. Use this instead of ``ZipFile.extractall`` on untrusted input.

    Note: this validates member *names* only. It does not follow symlink
    *targets*, but Python's ``zipfile`` does not materialize symlink members on
    extraction (it writes the link target as regular file content), so no
    symlink-based escape is possible via this path.
    """
    dest_dir = Path(dest_dir).resolve()
    for member in zip_file.namelist():
        target = dest_dir / member
        if not is_within_directory(dest_dir, target):
            raise ValueError(f"Unsafe path in archive (zip-slip blocked): {member}")
    zip_file.extractall(dest_dir)
