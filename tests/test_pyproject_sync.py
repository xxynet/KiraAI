"""
Guard against drift between requirements.txt and pyproject.toml.

Both files list the runtime dependencies: requirements.txt is what pip / uv pip
and the Docker image consume, pyproject.toml is what ``uv sync`` / ``uv run``
consume.  A dependency added to only one of them breaks the other install path,
so keep them identical.
"""

from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    tomllib = pytest.importorskip("tomli")

from core.config import VERSION

ROOT = Path(__file__).resolve().parent.parent


def _read_requirements() -> set[str]:
    lines = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    return {
        line.strip()
        for line in lines
        if line.strip() and not line.lstrip().startswith("#")
    }


def _read_pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_dependencies_match_requirements():
    requirements = _read_requirements()
    declared = set(_read_pyproject()["project"]["dependencies"])

    missing_in_pyproject = requirements - declared
    missing_in_requirements = declared - requirements
    assert not missing_in_pyproject and not missing_in_requirements, (
        f"requirements.txt and pyproject.toml are out of sync — "
        f"missing in pyproject.toml: {sorted(missing_in_pyproject)}; "
        f"missing in requirements.txt: {sorted(missing_in_requirements)}"
    )


def test_project_version_matches_app_version():
    declared = _read_pyproject()["project"]["version"]
    assert declared == VERSION.lstrip("v"), (
        f"pyproject.toml version ({declared}) does not match "
        f"core.config.VERSION ({VERSION})"
    )


def test_requires_python_matches_supported_range():
    assert _read_pyproject()["project"]["requires-python"] == ">=3.10"


def test_python_version_pin_matches_docker_image():
    """.python-version drives uv; the Docker image must use the same interpreter."""
    pinned = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert f"FROM python:{pinned}-slim" in dockerfile, (
        f".python-version pins {pinned} but the Dockerfile base image differs"
    )
