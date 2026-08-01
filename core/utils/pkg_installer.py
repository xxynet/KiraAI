"""
Package installer backend resolution — supports both pip and uv.

Runtime dependency installs (plugin requirements, WebUI manual installs,
post-update dependency sync) used to shell out to ``sys.executable -m pip``
directly.  Environments created by ``uv venv`` ship without pip, so that call
fails with "No module named pip".  This module resolves whichever backend is
actually available and builds the matching command:

  * pip -> ``[sys.executable, "-m", "pip", "install", ...]``
  * uv  -> ``[<uv>, "pip", "install", "--python", sys.executable, ...]``

``--python sys.executable`` makes uv target the interpreter KiraAI is running
under, so packages land in the same environment either way.

pip is preferred when it is importable, so existing installations keep their
current behaviour (pip.conf mirrors, extra index URLs).  Set the environment
variable ``KIRA_PACKAGE_INSTALLER`` to ``uv`` or ``pip`` to force a backend.
"""

import os
import shutil
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from core.logging_manager import get_logger

logger = get_logger("pkg_installer", "blue")

BACKEND_ENV_VAR = "KIRA_PACKAGE_INSTALLER"

PIP = "pip"
UV = "uv"


@lru_cache(maxsize=1)
def find_uv() -> Optional[str]:
    """Return the path to the uv executable, or None if uv is unavailable.

    Looks in the current interpreter's script directory first (uv installed
    into the virtual environment via ``pip install uv``), then on PATH.
    """
    scripts_dir = Path(sys.executable).parent
    return shutil.which(UV, path=str(scripts_dir)) or shutil.which(UV)


@lru_cache(maxsize=1)
def has_pip() -> bool:
    """Return True if pip is importable from the current interpreter."""
    import importlib.util

    try:
        return importlib.util.find_spec(PIP) is not None
    except (ImportError, ValueError):
        return False


def resolve_backend() -> Tuple[str, Optional[str]]:
    """
    Pick the installer backend.

    Returns a ``(backend, uv_path)`` tuple where backend is ``"pip"`` or
    ``"uv"``; uv_path is only set for the uv backend.

    Raises RuntimeError if neither pip nor uv can be found.
    """
    forced = os.environ.get(BACKEND_ENV_VAR, "").strip().lower()
    uv_path = find_uv()

    if forced == UV:
        if not uv_path:
            raise RuntimeError(f"{BACKEND_ENV_VAR}=uv but the uv executable was not found")
        return UV, uv_path
    if forced == PIP:
        if not has_pip():
            raise RuntimeError(f"{BACKEND_ENV_VAR}=pip but pip is not available in {sys.executable}")
        return PIP, None
    if forced:
        logger.warning(f"Ignoring invalid {BACKEND_ENV_VAR} value: {forced}")

    if has_pip():
        return PIP, None
    if uv_path:
        return UV, uv_path
    raise RuntimeError(
        "No package installer available: pip is not importable and uv was not "
        "found on PATH. Install uv (https://docs.astral.sh/uv/) or add pip to "
        "the environment."
    )


def describe_backend() -> str:
    """Human-readable backend description for logs.  Never raises."""
    try:
        backend, uv_path = resolve_backend()
    except RuntimeError as e:
        return f"unavailable ({e})"
    return f"uv ({uv_path})" if backend == UV else f"pip ({sys.executable})"


def normalize_pypi_mirror(pypi_mirror: Optional[str]) -> Optional[str]:
    """Validate a PyPI mirror URL, returning None (with a warning) if invalid."""
    if not pypi_mirror:
        return None
    mirror = pypi_mirror.strip()
    if not mirror.startswith(("http://", "https://")):
        logger.warning(
            f"Ignoring invalid pypi_mirror (must start with http:// or https://): {pypi_mirror}"
        )
        return None
    return mirror


def build_pip_shell_prefix() -> Tuple[str, dict]:
    """
    Build a shell prefix that replaces a bare ``pip`` in a user-supplied command,
    plus the extra environment variables it needs.

    Returns ``(prefix, env)`` — e.g. ``('"C:/py/python.exe" -m pip', {})`` for
    the pip backend, or ``('"C:/bin/uv.exe" pip', {"UV_PYTHON": ...})`` for uv.
    ``UV_PYTHON`` pins uv to the running interpreter, which is what
    ``--python`` does for the non-shell path.

    Raises RuntimeError if no backend is available.
    """
    backend, uv_path = resolve_backend()
    if backend == UV:
        return f'"{uv_path}" pip', {"UV_PYTHON": sys.executable}
    return f'"{sys.executable}" -m {PIP}', {}


def build_install_command(
    args: Sequence[str],
    pypi_mirror: Optional[str] = None,
    *,
    unbuffered: bool = False,
) -> List[str]:
    """
    Build an install command for the available backend.

    ``args`` are the install targets, e.g. ``["-r", "requirements.txt"]`` or a
    list of package specs.  ``unbuffered`` requests line-buffered output for
    callers that stream the subprocess (only meaningful for pip; uv always
    streams).

    Raises RuntimeError if no backend is available.
    """
    backend, uv_path = resolve_backend()
    if backend == UV:
        cmd = [str(uv_path), "pip", "install", "--python", sys.executable]
    else:
        cmd = [sys.executable]
        if unbuffered:
            cmd.append("-u")
        cmd += ["-m", PIP, "install"]

    cmd.extend(args)

    mirror = normalize_pypi_mirror(pypi_mirror)
    if mirror:
        cmd += ["--index-url", mirror]
    return cmd
