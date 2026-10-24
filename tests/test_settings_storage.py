import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from webui.routes import settings
from webui.routes.auth import require_auth


def make_hard_link(source, target):
    try:
        os.link(source, target)
    except OSError as exc:
        pytest.skip(f"Hard links unavailable on the test filesystem: {exc}")


@pytest.mark.parametrize("missing", [False, True])
def test_empty_or_missing_directory(tmp_path, missing):
    path = tmp_path / "missing" if missing else tmp_path
    assert settings._calc_dir_size(path) == (0, 0)


def test_hard_links_are_counted_once_across_nested_directories(tmp_path):
    source = tmp_path / "git.exe"
    source.write_bytes(b"portable git runtime")
    nested = tmp_path / "libexec" / "git-core"
    nested.mkdir(parents=True)
    make_hard_link(source, tmp_path / "git-clone.exe")
    make_hard_link(source, nested / "git-fetch.exe")
    (nested / "independent.exe").write_bytes(source.read_bytes())
    (nested / "empty.txt").touch()

    expected = (len(source.read_bytes()) * 2, 3)
    assert settings._calc_dir_size(tmp_path) == expected
    assert settings._calc_dir_size(tmp_path) == expected
    assert settings._calc_dir_size(nested) == expected


@pytest.mark.parametrize(
    ("identities", "expected"),
    [
        ([(1, 42), (1, 42)], (10, 1)),
        ([(1, 42), (2, 42)], (20, 2)),
        ([(1, 42), (1, 43)], (20, 2)),
        ([(1, 0), (1, 0)], (20, 2)),
    ],
)
def test_hard_link_identity_includes_device_and_requires_valid_inode(
    tmp_path, monkeypatch, identities, expected
):
    files = [tmp_path / "first", tmp_path / "second"]
    for path in files:
        path.touch()
    stats = {
        path: SimpleNamespace(st_dev=device, st_ino=inode, st_nlink=2, st_size=10)
        for path, (device, inode) in zip(files, identities)
    }
    original_stat = Path.stat

    def file_stat(path, *args, **kwargs):
        if path in stats:
            return stats[path]
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", file_stat)
    assert settings._calc_dir_size(tmp_path) == expected


def test_unstatable_file_does_not_abort_directory_scan(tmp_path, monkeypatch):
    unavailable = tmp_path / "unavailable"
    unavailable.touch()
    (tmp_path / "readable").write_bytes(b"data")
    original_stat = Path.stat

    def file_stat(path, *args, **kwargs):
        if path == unavailable:
            raise OSError("File disappeared during scan")
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", file_stat)
    assert settings._calc_dir_size(tmp_path) == (4, 1)


@pytest.mark.anyio
async def test_storage_endpoint_deduplicates_directory_and_data_totals(tmp_path, monkeypatch):
    tools = tmp_path / "tools"
    tools.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    source = tools / "git.exe"
    source.write_bytes(b"portable git runtime")
    make_hard_link(source, tools / "git-clone.exe")
    make_hard_link(source, plugins / "git.exe")
    (tmp_path / "config.json").write_bytes(b"{}")
    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    settings.SettingsRoutes(app).register()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/settings/storage")

    assert response.status_code == 200
    info = response.json()
    size = len(source.read_bytes())
    assert info["total_size_bytes"] == size + 2
    directories = {
        entry["name"]: (entry["size_bytes"], entry["file_count"])
        for entry in info["directories"]
    }
    assert directories == {"plugins": (size, 1), "tools": (size, 1)}
