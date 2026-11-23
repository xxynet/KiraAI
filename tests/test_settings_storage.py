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


def test_file_symlinks_count_their_own_size(tmp_path):
    source = tmp_path / "libsample.so.1"
    source.write_bytes(b"x" * 4096)
    link = tmp_path / "libsample.so"
    dangling = tmp_path / "libmissing.so"
    try:
        link.symlink_to(source.name)
        dangling.symlink_to("libmissing.so.1")
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable on the test filesystem: {exc}")

    expected_size = source.stat().st_size + link.lstat().st_size + dangling.lstat().st_size
    assert settings._calc_dir_size(tmp_path) == (expected_size, 3)


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
    assert sum(entry["size_bytes"] for entry in info["usage_breakdown"]) == size + 2
    assert sum(entry["size_bytes"] > 0 for entry in info["usage_breakdown"]) == 2
    directories = {
        entry["name"]: (entry["size_bytes"], entry["file_count"])
        for entry in info["directories"]
    }
    assert directories == {"plugins": (size, 1), "tools": (size, 1)}


@pytest.fixture
def storage_app(tmp_path, monkeypatch):
    from core.utils import media_refs

    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: True
    return app


@pytest.mark.anyio
async def test_classified_cleanup_keeps_recent_files_and_other_categories(storage_app, tmp_path, monkeypatch):
    import time

    now = time.time() + 3 * 86400
    monkeypatch.setattr(settings, "time", lambda: now)
    for directory in ("temp", "session_media", "config", "plugin_data"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "old").write_bytes(b"old")
    recent = tmp_path / "temp" / "recent"
    recent.write_bytes(b"recent")
    os.utime(recent, (now, now))
    settings.SettingsRoutes(storage_app).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=storage_app), base_url="http://test"
    ) as client:
        info = (await client.get("/api/settings/storage")).json()
        categories = {item["id"]: item for item in info["categories"]}
        assert categories["temp"]["item_count"] == 2
        assert categories["temp"]["cleanable_count"] == 1
        assert categories["temp"]["cleanable_bytes"] == 3
        response = await client.post("/api/settings/storage/temp/cleanup")
        assert response.json() == {"deleted_count": 1, "deleted_bytes": 3, "failed_count": 0}
        assert (await client.post("/api/settings/storage/temp/cleanup")).json()["deleted_count"] == 0
        assert (await client.post("/api/settings/storage/config/cleanup")).status_code == 422
    assert recent.exists()
    assert not (tmp_path / "temp" / "old").exists()
    for directory in ("session_media", "config", "plugin_data"):
        assert (tmp_path / directory / "old").exists()


@pytest.mark.anyio
async def test_media_cleanup_preserves_active_turn_files(storage_app, tmp_path, monkeypatch):
    import time

    from core.utils import media_refs

    monkeypatch.setattr(settings, "time", lambda: time.time() + 3 * 86400)
    root = tmp_path / "session_media"
    archive = root / "archive"
    archive.mkdir(parents=True)
    pinned = root / "pinned.png"
    pinned.write_bytes(b"pinned")
    expired = archive / "old.png"
    expired.write_bytes(b"archive")
    monkeypatch.setattr(media_refs, "_protected_media_paths", {pinned.resolve(): 1})
    settings.SettingsRoutes(storage_app).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=storage_app), base_url="http://test"
    ) as client:
        response = await client.post("/api/settings/storage/session_media/cleanup")
    assert response.json()["deleted_count"] == 1
    assert pinned.exists()
    assert not expired.exists()


@pytest.mark.anyio
async def test_image_description_cleanup_is_scoped_to_cache(storage_app, session_db):
    await session_db.add_image_desc_cache("a" * 32, "图片 description", 1, 1)
    await session_db.add_image_desc_cache("b" * 32, "", 1, 1)
    settings.SettingsRoutes(storage_app, SimpleNamespace(db_service=session_db)).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=storage_app), base_url="http://test"
    ) as client:
        info = (await client.get("/api/settings/storage")).json()
        category = next(item for item in info["categories"] if item["id"] == "image_descriptions")
        assert category["size_bytes"] == len("图片 description".encode())
        assert category["cleanable_count"] == 2
        response = await client.post("/api/settings/storage/image_descriptions/cleanup")
        assert response.json()["deleted_count"] == 2
        assert await session_db.get_image_desc_cache_usage() == {"size_bytes": 0, "item_count": 0}


@pytest.mark.anyio
async def test_cleanup_requires_authentication(tmp_path):
    app = FastAPI()
    settings.SettingsRoutes(app).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post("/api/settings/storage/temp/cleanup")
    assert response.status_code in (401, 403)


def test_cleanup_does_not_follow_links_or_delete_link_targets(tmp_path):
    from core.utils.storage import inspect_files

    root = tmp_path / "temp"
    root.mkdir()
    outside = tmp_path / "config"
    outside.mkdir()
    target = outside / "keep"
    target.write_bytes(b"keep")
    try:
        (root / "directory-link").symlink_to(outside, target_is_directory=True)
        (root / "file-link").symlink_to(target)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable: {exc}")
    result = inspect_files(root, float("inf"), delete=True)
    assert result["deleted_count"] == 0
    assert target.read_bytes() == b"keep"
    assert inspect_files(root / "directory-link", float("inf"), delete=True)["deleted_count"] == 0


def test_cleanup_reports_locked_files_and_continues(tmp_path, monkeypatch):
    from core.utils.storage import inspect_files

    locked = tmp_path / "locked"
    locked.write_bytes(b"locked")
    (tmp_path / "available").write_bytes(b"available")
    original_unlink = Path.unlink

    def unlink(path, *args, **kwargs):
        if path == locked:
            raise PermissionError("File locked by another process")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", unlink)
    result = inspect_files(tmp_path, float("inf"), delete=True)
    assert result["deleted_count"] == 1
    assert result["failed_count"] == 1
    assert locked.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_cleanup_does_not_traverse_windows_junctions(tmp_path):
    import _winapi

    from core.utils.storage import inspect_files

    root = tmp_path / "temp"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "keep"
    target.write_bytes(b"keep")
    junction = root / "junction"
    _winapi.CreateJunction(str(outside), str(junction))
    try:
        assert inspect_files(root, float("inf"), delete=True)["deleted_count"] == 0
        assert inspect_files(junction, float("inf"), delete=True)["deleted_count"] == 0
        assert target.read_bytes() == b"keep"
    finally:
        junction.rmdir()


def test_cleanup_preserves_file_modified_after_scan(tmp_path, monkeypatch):
    from core.utils.storage import inspect_files

    target = tmp_path / "changed"
    target.write_bytes(b"old")
    original_lstat = Path.lstat
    calls = 0

    def lstat(path, *args, **kwargs):
        nonlocal calls
        if path == target:
            calls += 1
            if calls == 2:
                target.write_bytes(b"new content")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", lstat)
    result = inspect_files(tmp_path, float("inf"), delete=True)
    assert result["deleted_count"] == 0
    assert target.read_bytes() == b"new content"


@pytest.mark.anyio
async def test_cache_cleanup_reports_unavailable_service(storage_app):
    settings.SettingsRoutes(storage_app).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=storage_app), base_url="http://test"
    ) as client:
        response = await client.post("/api/settings/storage/image_descriptions/cleanup")
    assert response.status_code == 503


@pytest.mark.parametrize(("filename", "category"), [
    ("memory/memories.db", "sessions"),
    ("webchat/history.json", "sessions"),
    ("session_media/archive/image.png", "media"),
    ("files/upload.txt", "media"),
    ("sticker/smile.png", "media"),
    ("data.db", "database"),
    ("data.db-wal", "database"),
    ("data.db-shm", "database"),
    ("state.sqlite3-journal", "database"),
    ("plugin_data/memory/plugin.db", "plugins"),
    ("plugins/example/main.py", "plugins"),
    ("plugin_src/example.zip", "plugins"),
    ("tools/git/bin/git.exe", "runtime"),
    ("dist/index.html", "runtime"),
    ("updates/release.zip", "runtime"),
    ("backups/backup.zip", "backups"),
    ("temp/download.tmp", "temp"),
    ("logs/server.log", "logs"),
    ("log.log", "logs"),
    ("log.log.1", "logs"),
    ("server.log", "logs"),
    ("config/main.json", "other"),
    ("skills/tool/SKILL.md", "other"),
    ("unknown.bin", "other"),
])
def test_storage_usage_groups(filename, category):
    assert settings._storage_usage_group(Path(filename)) == category


@pytest.mark.anyio
async def test_instance_breakdown_accounts_for_all_data(storage_app, tmp_path):
    files = {
        "memory/session.json": b"session",
        "session_media/image.png": b"image",
        "data.db": b"database",
        "data.db-wal": b"wal",
        "plugin_data/tool/state.db": b"plugin",
        "tools/git.exe": b"runtime",
        "backups/backup.zip": b"backup",
        "temp/file.tmp": b"temp",
        "log.log.1": b"log",
        "config/main.json": b"config",
        "unknown.bin": b"other",
    }
    expected = dict.fromkeys(settings.STORAGE_USAGE_DIRECTORIES, 0)
    for name, content in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        expected[settings._storage_usage_group(Path(name))] += len(content)
    settings.SettingsRoutes(storage_app).register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=storage_app), base_url="http://test"
    ) as client:
        response = await client.get("/api/settings/storage")
    info = response.json()
    assert {item["id"]: item["size_bytes"] for item in info["usage_breakdown"]} == expected
    assert sum(expected.values()) == info["total_size_bytes"] == sum(map(len, files.values()))


def test_empty_instance_has_zero_usage_in_every_group(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    info = settings.SettingsRoutes(FastAPI())._collect_storage_info()
    assert info.total_size_bytes == 0
    assert len(info.usage_breakdown) == len(settings.STORAGE_USAGE_DIRECTORIES)
    assert all(item.size_bytes == 0 for item in info.usage_breakdown)
