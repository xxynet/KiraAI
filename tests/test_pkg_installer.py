import sys

import pytest

from core.utils import pkg_installer
from core.utils.pkg_installer import (
    BACKEND_ENV_VAR,
    build_install_command,
    build_pip_shell_prefix,
    normalize_pypi_mirror,
    resolve_backend,
)

UV_PATH = "/usr/local/bin/uv"


@pytest.fixture(autouse=True)
def clear_backend_env(monkeypatch):
    """Keep a developer's own KIRA_PACKAGE_INSTALLER out of the tests."""
    monkeypatch.delenv(BACKEND_ENV_VAR, raising=False)


def use_pip_only(monkeypatch):
    monkeypatch.setattr(pkg_installer, "has_pip", lambda: True)
    monkeypatch.setattr(pkg_installer, "find_uv", lambda: None)


def use_uv_only(monkeypatch):
    monkeypatch.setattr(pkg_installer, "has_pip", lambda: False)
    monkeypatch.setattr(pkg_installer, "find_uv", lambda: UV_PATH)


def test_pip_is_preferred_when_available(monkeypatch):
    monkeypatch.setattr(pkg_installer, "has_pip", lambda: True)
    monkeypatch.setattr(pkg_installer, "find_uv", lambda: UV_PATH)
    assert resolve_backend() == ("pip", None)


def test_uv_used_when_pip_is_missing(monkeypatch):
    use_uv_only(monkeypatch)
    assert resolve_backend() == ("uv", UV_PATH)


def test_no_backend_raises(monkeypatch):
    monkeypatch.setattr(pkg_installer, "has_pip", lambda: False)
    monkeypatch.setattr(pkg_installer, "find_uv", lambda: None)
    with pytest.raises(RuntimeError, match="No package installer available"):
        resolve_backend()


def test_env_var_forces_uv(monkeypatch):
    monkeypatch.setattr(pkg_installer, "has_pip", lambda: True)
    monkeypatch.setattr(pkg_installer, "find_uv", lambda: UV_PATH)
    monkeypatch.setenv(BACKEND_ENV_VAR, "uv")
    assert resolve_backend() == ("uv", UV_PATH)


def test_env_var_forcing_missing_uv_raises(monkeypatch):
    use_pip_only(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "uv")
    with pytest.raises(RuntimeError, match="uv executable was not found"):
        resolve_backend()


def test_invalid_env_var_falls_back_to_detection(monkeypatch):
    use_pip_only(monkeypatch)
    monkeypatch.setenv(BACKEND_ENV_VAR, "poetry")
    assert resolve_backend() == ("pip", None)


def test_pip_install_command(monkeypatch):
    use_pip_only(monkeypatch)
    assert build_install_command(["-r", "requirements.txt"]) == [
        sys.executable, "-m", "pip", "install", "-r", "requirements.txt",
    ]


def test_pip_install_command_unbuffered(monkeypatch):
    use_pip_only(monkeypatch)
    cmd = build_install_command(["httpx"], unbuffered=True)
    assert cmd == [sys.executable, "-u", "-m", "pip", "install", "httpx"]


def test_uv_install_command_targets_current_interpreter(monkeypatch):
    use_uv_only(monkeypatch)
    assert build_install_command(["-r", "requirements.txt"]) == [
        UV_PATH, "pip", "install", "--python", sys.executable, "-r", "requirements.txt",
    ]


def test_uv_ignores_unbuffered_flag(monkeypatch):
    use_uv_only(monkeypatch)
    assert "-u" not in build_install_command(["httpx"], unbuffered=True)


@pytest.mark.parametrize("setup", [use_pip_only, use_uv_only])
def test_mirror_is_appended(monkeypatch, setup):
    setup(monkeypatch)
    cmd = build_install_command(["httpx"], "https://pypi.tuna.tsinghua.edu.cn/simple/")
    assert cmd[-2:] == ["--index-url", "https://pypi.tuna.tsinghua.edu.cn/simple/"]


@pytest.mark.parametrize("mirror", ["", None, "pypi.org/simple", "ftp://pypi.org/simple"])
def test_invalid_mirror_is_dropped(monkeypatch, mirror):
    use_pip_only(monkeypatch)
    assert normalize_pypi_mirror(mirror) is None
    assert "--index-url" not in build_install_command(["httpx"], mirror)


def test_mirror_is_stripped():
    assert normalize_pypi_mirror("  https://pypi.org/simple/  ") == "https://pypi.org/simple/"


def test_pip_shell_prefix(monkeypatch):
    use_pip_only(monkeypatch)
    prefix, env = build_pip_shell_prefix()
    assert prefix == f'"{sys.executable}" -m pip'
    assert env == {}


def test_uv_shell_prefix_pins_interpreter(monkeypatch):
    use_uv_only(monkeypatch)
    prefix, env = build_pip_shell_prefix()
    assert prefix == f'"{UV_PATH}" pip'
    assert env == {"UV_PYTHON": sys.executable}
