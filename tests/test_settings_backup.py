import asyncio
import base64
import io
import json
import os
import sqlite3
import stat
import subprocess
import sys
import threading
import zipfile
from contextlib import closing, suppress
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from webui import utils as webui_utils
from webui.models import (
    ChangeTokenRequest,
    OnboardingCompleteRequest,
    OnboardingTokenSetupRequest,
)
from webui.routes import auth as auth_routes
from webui.routes import settings
from webui.routes.auth import require_auth


@pytest.fixture
def backup_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(webui_utils, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(settings.SettingsRoutes, "_maintenance_lock", asyncio.Lock())
    # File-backed assertions assume no env-supplied key; dedicated tests set it.
    monkeypatch.delenv("JWT_SECRET", raising=False)
    return settings.SettingsRoutes(FastAPI()), tmp_path


@pytest.fixture
def backup_clock(monkeypatch):
    class Clock:
        current = datetime(2026, 10, 14, 12, 30, 45)
        fromtimestamp = staticmethod(datetime.fromtimestamp)

        @classmethod
        def now(cls):
            return cls.current

        @classmethod
        def advance(cls):
            cls.current += timedelta(seconds=1)

    monkeypatch.setattr(settings, "datetime", Clock)
    return Clock


def test_backup_reports_progress_within_large_file_and_preserves_contents(backup_routes):
    routes, data_path = backup_routes
    content = b"backup data\n" * 300_000
    (data_path / "large.bin").write_bytes(content)
    (data_path / "empty.txt").touch()
    for name in ("backups", "dist", "__pycache__", "updates", "temp"):
        (data_path / name).mkdir(exist_ok=True)
        (data_path / name / "excluded.txt").write_text("excluded")
    nested = data_path / "plugins" / "example"
    nested.mkdir(parents=True)
    (nested / "config.json").write_text("{}")
    events = []

    result = routes._create_backup_sync(lambda stage, percent: events.append((stage, percent)))

    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert set(archive.namelist()) == {"large.bin", "empty.txt", "plugins/example/config.json"}
        assert archive.read("large.bin") == content
        assert archive.read("empty.txt") == b""
        assert archive.testzip() is None
        assert archive.getinfo("large.bin").compress_type == zipfile.ZIP_DEFLATED
    assert result.size_bytes == (data_path / "backups" / result.filename).stat().st_size
    assert events[0] == ("scanning", 0)
    assert events[-1] == ("finalizing", 99)
    percentages = [percent for _, percent in events]
    assert percentages == sorted(percentages)
    assert any(0 < percent < 90 for stage, percent in events if stage == "compressing")
    assert not list((data_path / "backups").glob("*.part"))


@pytest.mark.anyio
@pytest.mark.parametrize("parent", ["plugins/example", "plugin_data/example"])
@pytest.mark.parametrize("name", ["backups", "dist", "updates", "temp"])
async def test_backup_preserves_nested_application_directory_names_on_restore(
    backup_routes, parent, name
):
    routes, data_path = backup_routes
    root_directory = data_path / name
    root_directory.mkdir()
    excluded_file = root_directory / "excluded.txt"
    excluded_file.write_bytes(b"application-owned data")
    nested_file = data_path / parent / name / "nested" / "content.bin"
    nested_file.parent.mkdir(parents=True)
    original = b"persistent plugin data\x00\xff"
    nested_file.write_bytes(original)
    cache_file = data_path / parent / "__pycache__" / "module.pyc"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"disposable bytecode")

    result = routes._create_backup_sync()

    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert archive.namelist() == [nested_file.relative_to(data_path).as_posix()]
        assert archive.read(archive.namelist()[0]) == original
        assert archive.testzip() is None

    nested_file.write_bytes(b"changed after backup")
    restored = await routes.restore_from_backup(result.filename)

    assert restored.success
    assert nested_file.read_bytes() == original
    assert excluded_file.read_bytes() == b"application-owned data"


def test_empty_backup_is_valid(backup_routes):
    routes, data_path = backup_routes
    result = routes._create_backup_sync()
    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert archive.namelist() == []


@pytest.mark.parametrize("relative", ["data.db", "plugin_data/sample/store"])
def test_backup_captures_committed_wal_data_without_sidecars(backup_routes, relative, monkeypatch):
    routes, data_path = backup_routes
    monkeypatch.delattr(sqlite3, "SQLITE_BUSY", raising=False)
    monkeypatch.delattr(sqlite3, "SQLITE_LOCKED", raising=False)
    database = data_path / relative
    database.parent.mkdir(parents=True, exist_ok=True)
    unrelated = data_path / "archive-wal"
    unrelated.write_bytes(b"ordinary file with a WAL-like name")
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE messages (text TEXT)")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO messages VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO messages VALUES ('uncommitted')")
        assert database.with_name(database.name + "-wal").stat().st_size > 0

        result = routes._create_backup_sync()
        with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
            extracted = archive.extract(relative, data_path / "extracted")
            with closing(sqlite3.connect(extracted)) as snapshot:
                assert snapshot.execute("PRAGMA quick_check").fetchone() == ("ok",)
                assert snapshot.execute("SELECT text FROM messages").fetchall() == [("committed",)]
            assert set(archive.namelist()) == {relative, unrelated.name}
            assert archive.read(unrelated.name) == unrelated.read_bytes()
        assert writer.execute("SELECT text FROM messages").fetchall() == [
            ("committed",),
            ("uncommitted",),
        ]


@pytest.mark.skipif(os.name != "nt", reason="Windows extended paths require Windows")
@pytest.mark.parametrize("long_path", [False, True])
def test_backup_captures_wal_data_with_windows_extended_paths(backup_routes, monkeypatch, long_path):
    routes, tmp_path = backup_routes
    data_path = Path("\\\\?\\" + str(tmp_path / "data #100%"))
    if long_path:
        data_path = data_path.joinpath(*(["long-path-" * 5] * 4))
        assert len(str(data_path)) > 260
    data_path.mkdir(parents=True)
    monkeypatch.setattr(settings, "get_data_path", lambda: data_path)
    database = data_path / "data #100%.db"
    with closing(sqlite3.connect(database)) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE messages (text TEXT)")
        writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        writer.execute("INSERT INTO messages VALUES ('committed')")
        writer.commit()
        writer.execute("INSERT INTO messages VALUES ('uncommitted')")
        assert database.with_name(database.name + "-wal").stat().st_size > 0

        result = routes._create_backup_sync()

        with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
            assert archive.namelist() == [database.name]
            extracted = archive.extract(database.name, tmp_path / "extracted")
            with closing(sqlite3.connect(extracted)) as snapshot:
                assert snapshot.execute("PRAGMA quick_check").fetchone() == ("ok",)
                assert snapshot.execute("SELECT text FROM messages").fetchall() == [("committed",)]
        assert writer.execute("SELECT text FROM messages").fetchall() == [
            ("committed",),
            ("uncommitted",),
        ]
    assert not list((data_path / "backups").glob("*.part"))
    assert [path.name for path in (data_path / "backups").iterdir()] == [result.filename]


def test_backup_failure_for_unreadable_sqlite_does_not_publish_an_archive(backup_routes):
    routes, data_path = backup_routes
    (data_path / "data.db").write_bytes(b"SQLite format 3\0" + bytes(400))

    with pytest.raises(sqlite3.DatabaseError):
        routes._create_backup_sync()

    assert not list((data_path / "backups").iterdir())


def test_backup_aborts_when_a_sqlite_lock_does_not_clear(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    times = iter([0, 16])
    monkeypatch.setattr(settings, "monotonic", lambda: next(times))
    with closing(sqlite3.connect(data_path / "data.db")) as writer:
        writer.execute("CREATE TABLE messages (text TEXT)")
        writer.execute("BEGIN EXCLUSIVE")
        with pytest.raises(sqlite3.OperationalError, match="Timed out reading SQLite database"):
            routes._create_backup_sync()

    assert not list((data_path / "backups").iterdir())


def test_backup_and_restore_preserve_in_tree_symlinks(backup_routes, monkeypatch):
    routes, tmp_path = backup_routes
    data_path = tmp_path / "data"
    restored_path = tmp_path / "restored"
    restored_path.mkdir()
    monkeypatch.setattr(settings, "get_data_path", lambda: data_path)
    runtime = data_path / "git-runtime"
    runtime.mkdir(parents=True)
    library = runtime / "libsample.so.1"
    library.write_bytes(b"x" * 4096)
    with closing(sqlite3.connect(runtime / "local.db")) as database:
        assert database.execute("PRAGMA journal_mode=DELETE").fetchone() == ("delete",)
        database.execute("CREATE TABLE content (value TEXT)")
    (runtime / "empty").mkdir()
    (runtime / "nested").mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"outside the data directory")
    links = {
        "libsample.so": (library.name, False),
        "local.db-shm": (library.name, False),
        "libabsolute.so": (str(library), False),
        "libabsolute-chain.so": (str(runtime / "libsample.so"), False),
        "libmissing.so": ("libmissing.so.1", False),
        "nested/libsample.so": ("../libsample.so", False),
        "empty_link": ("empty", True),
        "outside_link": (str(outside), False),
    }
    try:
        for name, (target, is_directory) in links.items():
            (runtime / name).symlink_to(target, target_is_directory=is_directory)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable on the test filesystem: {exc}")

    result = routes._create_backup_sync()
    archive_path = data_path / "backups" / result.filename
    with zipfile.ZipFile(archive_path) as archive:
        assert "git-runtime/outside_link" not in archive.namelist()
        assert archive.read("git-runtime/libsample.so.1") == library.read_bytes()
        for name, target in {
            "libsample.so": library.name,
            "local.db-shm": library.name,
            "libabsolute.so": library.name,
            "libabsolute-chain.so": "libsample.so",
            "libmissing.so": "libmissing.so.1",
            "nested/libsample.so": "../libsample.so",
            "empty_link": "empty",
        }.items():
            entry = archive.getinfo(f"git-runtime/{name}")
            assert stat.S_ISLNK(entry.external_attr >> 16)
            assert archive.read(entry) == os.fsencode(target)

    monkeypatch.setattr(settings, "get_data_path", lambda: restored_path)
    assert routes._do_restore(archive_path).success
    assert routes._do_restore(archive_path).success
    runtime = restored_path / runtime.name
    assert (runtime / "libsample.so").is_symlink()
    assert (runtime / "libsample.so").read_bytes() == library.read_bytes()
    assert (runtime / "local.db-shm").is_symlink()
    assert (runtime / "local.db-shm").read_bytes() == library.read_bytes()
    assert (runtime / "libabsolute.so").resolve() == runtime / library.name
    assert (runtime / "nested" / "libsample.so").read_bytes() == library.read_bytes()
    assert (runtime / "libmissing.so").is_symlink()
    assert not (runtime / "libmissing.so").exists()
    assert (runtime / "empty_link").is_symlink()
    assert (runtime / "empty_link").is_dir()

    new_library = runtime / "libsample.so.2"
    new_library.write_bytes(b"new version")
    (runtime / "libsample.so").unlink()
    (runtime / "libsample.so").symlink_to(new_library.name)
    assert (runtime / "libabsolute-chain.so").read_bytes() == new_library.read_bytes()


@pytest.mark.parametrize("target", ["/absolute", "../out-of-tree"])
def test_restore_rejects_link_targets_outside_archive_root(backup_routes, target):
    routes, data_path = backup_routes
    archive_path = data_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ordinary.txt", "unchanged on failure")
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, target)

    with pytest.raises(HTTPException) as error:
        routes._do_restore(archive_path)
    assert error.value.status_code == 400
    assert not (data_path / "ordinary.txt").exists()


def test_restore_replaces_existing_file_symlink_without_writing_to_target(backup_routes):
    routes, data_path = backup_routes
    original = data_path / "original.txt"
    original.write_bytes(b"original")
    link = data_path / "restored.txt"
    try:
        link.symlink_to(original.name)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable on the test filesystem: {exc}")
    archive_path = data_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(link.name, b"restored data")

    assert routes._do_restore(archive_path).success
    assert not link.is_symlink()
    assert link.read_bytes() == b"restored data"
    assert original.read_bytes() == b"original"


def test_restore_rejects_writing_through_existing_directory_symlink(backup_routes):
    routes, data_path = backup_routes
    original = data_path / "original"
    original.mkdir()
    link = data_path / "linked_directory"
    try:
        link.symlink_to(original.name, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symbolic links unavailable on the test filesystem: {exc}")
    archive_path = data_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ordinary.txt", b"ordinary data")
        archive.writestr(f"{link.name}/nested.txt", b"nested data")

    with pytest.raises(HTTPException) as error:
        routes._do_restore(archive_path)
    assert error.value.status_code == 400
    assert link.is_symlink()
    assert not (original / "nested.txt").exists()
    assert not (data_path / "ordinary.txt").exists()


def test_failed_archive_write_removes_partial_backup(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "input.txt").write_text("data")

    def fail_write(*args, **kwargs):
        raise OSError("write failed")

    monkeypatch.setattr(zipfile._ZipWriteFile, "write", fail_write)
    with pytest.raises(OSError, match="write failed"):
        routes._create_backup_sync()
    assert list((data_path / "backups").iterdir()) == []


@pytest.mark.anyio
async def test_background_backup_returns_immediately_and_reuses_active_task(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "large.bin").write_bytes(b"x" * (3 * 1024 * 1024))
    entered = threading.Event()
    release = threading.Event()
    original = routes._create_backup_sync

    def blocked_backup(report):
        def blocked_report(stage, percent):
            report(stage, percent)
            if stage == "compressing" and 0 < percent < 99:
                entered.set()
                if not release.wait(timeout=5):
                    raise RuntimeError("test did not release worker")
        return original(blocked_report)

    monkeypatch.setattr(routes, "_create_backup_sync", blocked_backup)
    started = await routes.start_backup()
    try:
        assert started.status == "queued"
        assert await asyncio.to_thread(entered.wait, 3)
        progress = await routes.get_backup_progress(started.id)
        assert progress.status == "running"
        assert 0 < progress.percent < 99
        assert (await routes.start_backup()).id == started.id
        assert (await routes.get_active_backup()).id == started.id
        assert await routes.list_backups() == []
        archive_path, = (data_path / "backups").glob("*.zip")
        assert archive_path.with_suffix(".zip.part").exists()
        reloaded_routes = settings.SettingsRoutes(FastAPI())
        assert await reloaded_routes.list_backups() == []
        for endpoint in (
            routes.download_backup, routes.delete_backup, routes.restore_from_backup,
            reloaded_routes.download_backup,
        ):
            with pytest.raises(HTTPException) as error:
                await endpoint(archive_path.name)
            assert error.value.status_code == 409
        assert archive_path.exists()
    finally:
        release.set()
        await asyncio.wait_for(routes._backup_task, timeout=5)

    progress = await routes.get_backup_progress(started.id)
    assert progress.status == "completed"
    assert progress.percent == 100
    assert progress.result.filename in [item["filename"] for item in await routes.list_backups()]
    assert await routes.get_active_backup() is None


@pytest.mark.anyio
async def test_backup_waits_for_maintenance_lock_and_caller_cancel_does_not_stop_job(backup_routes):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("{}")
    async with routes._maintenance_lock:
        dispatched = asyncio.Event()

        async def request():
            started = await routes.start_backup()
            dispatched.set()
            await asyncio.Event().wait()
            return started

        caller = asyncio.create_task(request())
        await dispatched.wait()
        started = await routes.get_active_backup()
        caller.cancel()
        with pytest.raises(asyncio.CancelledError):
            await caller
        assert (await routes.get_backup_progress(started.id)).status == "queued"
        assert not (data_path / "backups").exists()
    await asyncio.wait_for(routes._backup_task, timeout=5)
    assert (await routes.get_backup_progress(started.id)).status == "completed"


@pytest.mark.anyio
async def test_failed_background_backup_has_no_success_result_and_can_retry(backup_routes, monkeypatch):
    routes, _ = backup_routes
    original = routes._create_backup_sync

    def fail(report):
        raise OSError("private configuration detail")

    monkeypatch.setattr(routes, "_create_backup_sync", fail)
    started = await routes.start_backup()
    await routes._backup_task
    progress = await routes.get_backup_progress(started.id)
    assert progress.status == "failed"
    assert progress.percent < 100
    assert progress.result is None
    assert "private configuration detail" not in progress.model_dump_json()

    monkeypatch.setattr(routes, "_create_backup_sync", original)
    retried = await routes.start_backup()
    await routes._backup_task
    assert retried.id != started.id
    assert (await routes.get_backup_progress(retried.id)).status == "completed"


@pytest.mark.anyio
async def test_backup_task_history_is_bounded_and_unknown_task_returns_404(backup_routes, backup_clock):
    routes, _ = backup_routes
    first_id = None
    for _ in range(21):
        started = await routes.start_backup()
        first_id = first_id or started.id
        await routes._backup_task
        assert (await routes.get_backup_progress(started.id)).status == "completed"
        backup_clock.advance()
    assert len(routes._backup_progress) == 20
    with pytest.raises(HTTPException) as error:
        await routes.get_backup_progress(first_id)
    assert error.value.status_code == 404


@pytest.mark.anyio
async def test_http_progress_routes(backup_routes, backup_clock):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("{}")
    routes.app.dependency_overrides[require_auth] = lambda: True
    routes.register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=routes.app), base_url="http://test"
    ) as client:
        async with routes._maintenance_lock:
            response = await client.post("/api/settings/backup/tasks")
            assert response.status_code == 200
            task_id = response.json()["id"]
            active = await client.get("/api/settings/backup/tasks/active")
            assert active.json()["id"] == task_id
            assert (await client.get(f"/api/settings/backup/tasks/{task_id}")).json()["percent"] == 0
            assert (await client.get("/api/settings/backup/tasks/missing")).status_code == 404
        await routes._backup_task
        completed = (await client.get(f"/api/settings/backup/tasks/{task_id}")).json()
        assert completed["status"] == "completed"
        assert completed["percent"] == 100
        assert (await client.get("/api/settings/backup/tasks/active")).json() is None
        assert set(completed["result"]) == {"filename", "size_bytes", "created_at"}
        assert (data_path / "backups" / completed["result"]["filename"]).exists()


@pytest.mark.anyio
async def test_backup_archive_can_be_restored_with_existing_restore_flow(backup_routes):
    routes, data_path = backup_routes
    nested = data_path / "plugins" / "example"
    nested.mkdir(parents=True)
    config = nested / "config.json"
    config.write_text('{"enabled": true}', encoding="utf-8")
    started = await routes.start_backup()
    await routes._backup_task
    completed = await routes.get_backup_progress(started.id)
    config.write_text('{"enabled": false}', encoding="utf-8")

    restored = await routes.restore_from_backup(completed.result.filename)

    assert restored.success
    assert config.read_text(encoding="utf-8") == '{"enabled": true}'
    assert (data_path / "backups" / completed.result.filename).exists()


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/settings/backup/tasks"),
        ("GET", "/api/settings/backup/tasks/active"),
        ("GET", "/api/settings/backup/tasks/missing"),
    ],
)
async def test_backup_task_endpoints_require_auth(backup_routes, method, path):
    routes, _ = backup_routes
    routes.register()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=routes.app), base_url="http://test"
    ) as client:
        assert (await client.request(method, path)).status_code == 401
    assert routes._backup_task is None


def test_same_second_backup_is_rejected_and_existing_archive_is_preserved(backup_routes, backup_clock):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("original")
    first = routes._create_backup_sync()
    assert first.filename == "backup_20261014_123045.zip"
    archive_path = data_path / "backups" / first.filename
    original_archive = archive_path.read_bytes()
    (data_path / "config.json").write_text("changed")
    events = []

    with pytest.raises(HTTPException) as error:
        routes._create_backup_sync(lambda stage, percent: events.append((stage, percent)))

    assert error.value.status_code == 409
    assert events == []
    assert archive_path.read_bytes() == original_archive
    assert list(archive_path.parent.iterdir()) == [archive_path]


def test_existing_partial_backup_is_not_overwritten_or_removed(backup_routes, backup_clock):
    routes, data_path = backup_routes
    backup_dir = data_path / "backups"
    backup_dir.mkdir()
    partial = backup_dir / "backup_20261014_123045.zip.part"
    partial.write_bytes(b"existing partial backup")

    with pytest.raises(HTTPException) as error:
        routes._create_backup_sync()

    assert error.value.status_code == 409
    assert partial.read_bytes() == b"existing partial backup"
    assert list(backup_dir.iterdir()) == [partial]


def test_exclusive_archive_creation_rejects_filename_race(backup_routes, backup_clock, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("{}")
    archive_path = data_path / "backups" / "backup_20261014_123045.zip"
    marker_path = archive_path.with_suffix(".zip.part")
    original_open = Path.open
    events = []

    def create_conflicting_archive(path, mode="r", *args, **kwargs):
        handle = original_open(path, mode, *args, **kwargs)
        if path == marker_path and mode == "xb":
            archive_path.write_bytes(b"concurrent backup")
        return handle

    monkeypatch.setattr(Path, "open", create_conflicting_archive)
    with pytest.raises(HTTPException) as error:
        routes._create_backup_sync(lambda stage, percent: events.append((stage, percent)))

    assert error.value.status_code == 409
    assert events == []
    assert archive_path.read_bytes() == b"concurrent backup"
    assert list(archive_path.parent.iterdir()) == [archive_path]


def test_marker_filename_race_does_not_remove_other_jobs_file(backup_routes, backup_clock, monkeypatch):
    routes, data_path = backup_routes
    marker_path = data_path / "backups" / "backup_20261014_123045.zip.part"
    original_open = Path.open
    events = []

    def create_conflicting_marker(path, mode="r", *args, **kwargs):
        if path == marker_path and mode == "xb":
            with original_open(path, "wb") as handle:
                handle.write(b"other job")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", create_conflicting_marker)
    with pytest.raises(HTTPException) as error:
        routes._create_backup_sync(lambda stage, percent: events.append((stage, percent)))

    assert error.value.status_code == 409
    assert events == []
    assert marker_path.read_bytes() == b"other job"
    assert list(marker_path.parent.iterdir()) == [marker_path]


@pytest.mark.anyio
async def test_background_collision_returns_reason_and_can_retry_next_second(backup_routes, backup_clock):
    routes, data_path = backup_routes
    first = routes._create_backup_sync()
    original_archive = (data_path / "backups" / first.filename).read_bytes()
    started = await routes.start_backup()
    await routes._backup_task

    failed = await routes.get_backup_progress(started.id)
    assert failed.status == "failed"
    assert failed.error == "backup_exists"
    assert failed.percent == 0
    assert failed.result is None
    assert (data_path / "backups" / first.filename).read_bytes() == original_archive

    backup_clock.advance()
    retried = await routes.start_backup()
    await routes._backup_task
    completed = await routes.get_backup_progress(retried.id)
    assert completed.status == "completed"
    assert completed.error is None
    assert completed.result.filename == "backup_20261014_123046.zip"


def test_backup_succeeds_when_hard_links_are_unavailable(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("{}")

    def unsupported_link(*args, **kwargs):
        raise OSError("Hard links are unsupported")

    monkeypatch.setattr(settings.os, "link", unsupported_link)
    result = routes._create_backup_sync()

    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert archive.read("config.json") == b"{}"
        assert archive.testzip() is None
    assert not list((data_path / "backups").glob("*.part"))


def test_scan_failure_removes_only_owned_archive_and_marker(backup_routes, monkeypatch):
    routes, data_path = backup_routes

    def fail_scan(*args, **kwargs):
        raise OSError("scan failed")

    monkeypatch.setattr(settings.os, "walk", fail_scan)
    with pytest.raises(OSError, match="scan failed"):
        routes._create_backup_sync()
    assert list((data_path / "backups").iterdir()) == []


@pytest.mark.anyio
async def test_marked_backup_is_hidden_and_blocked_after_routes_reload(backup_routes, backup_clock):
    _, data_path = backup_routes
    backup_dir = data_path / "backups"
    backup_dir.mkdir()
    archive_path = backup_dir / "backup_20261014_123045.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("config.json", "{}")
    marker_path = archive_path.with_suffix(".zip.part")
    marker_path.touch()
    original_archive = archive_path.read_bytes()
    routes = settings.SettingsRoutes(FastAPI())
    routes.app.dependency_overrides[require_auth] = lambda: True
    routes.register()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=routes.app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/settings/backup/list")).json() == []
        for method, path in (
            ("GET", f"/api/settings/backup/download/{archive_path.name}"),
            ("DELETE", f"/api/settings/backup/{archive_path.name}"),
            ("POST", f"/api/settings/backup/{archive_path.name}/restore"),
        ):
            response = await client.request(method, path)
            assert response.status_code == 409
            assert response.json()["detail"] == "Backup is still being created"

    assert archive_path.read_bytes() == original_archive
    assert marker_path.exists()


@pytest.mark.anyio
async def test_completed_archive_is_visible_and_operable(backup_routes, backup_clock):
    routes, data_path = backup_routes
    (data_path / "config.json").write_text("{}")
    started = await routes.start_backup()
    await routes._backup_task
    completed = await routes.get_backup_progress(started.id)
    routes.app.dependency_overrides[require_auth] = lambda: True
    routes.register()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=routes.app), base_url="http://test"
    ) as client:
        listed = (await client.get("/api/settings/backup/list")).json()
        assert [item["filename"] for item in listed] == [completed.result.filename]
        download = await client.get(f"/api/settings/backup/download/{completed.result.filename}")
        assert download.status_code == 200
        archive_path = data_path / "backups" / completed.result.filename
        assert download.content == archive_path.read_bytes()
        assert not archive_path.with_suffix(".zip.part").exists()

        (data_path / "config.json").write_text('{"changed": true}')
        restored = await client.post(f"/api/settings/backup/{completed.result.filename}/restore")
        assert restored.status_code == 200
        assert restored.json()["success"]
        assert (data_path / "config.json").read_text() == "{}"

        deleted = await client.delete(f"/api/settings/backup/{completed.result.filename}")
        assert deleted.status_code == 200
        assert deleted.json()["success"]
        assert not archive_path.exists()
        assert (await client.get("/api/settings/backup/list")).json() == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "path_template"),
    [
        ("GET", "/api/settings/backup/download/{filename}"),
        ("DELETE", "/api/settings/backup/{filename}"),
        ("POST", "/api/settings/backup/{filename}/restore"),
    ],
)
@pytest.mark.parametrize("target_name", ["backup_20261014_123045.zip.part", "notes.txt"])
async def test_backup_operations_reject_internal_and_non_zip_files(
    backup_routes, method, path_template, target_name
):
    routes, data_path = backup_routes
    backup_dir = data_path / "backups"
    backup_dir.mkdir()
    archive_path = backup_dir / "backup_20261014_123045.zip"
    archive_path.write_bytes(b"unfinished archive")
    marker_path = archive_path.with_suffix(".zip.part")
    marker_path.touch()
    target_path = backup_dir / target_name
    if target_path != marker_path:
        target_path.write_bytes(b"internal data")
    original_archive = archive_path.read_bytes()
    original_target = target_path.read_bytes()
    routes.app.dependency_overrides[require_auth] = lambda: True
    routes.register()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=routes.app), base_url="http://test"
    ) as client:
        response = await client.request(method, path_template.format(filename=target_name))
        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid filename"
        assert target_path.read_bytes() == original_target
        assert marker_path.exists()
        assert archive_path.read_bytes() == original_archive
        assert (await client.get("/api/settings/backup/list")).json() == []
        assert (
            await client.get(f"/api/settings/backup/download/{archive_path.name}")
        ).status_code == 409


def test_restore_preserves_active_access_token_and_signing_key(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(
        json.dumps({"access_token": "current-token", "host": "127.0.0.1", "port": 5267}),
        encoding="utf-8",
    )
    (data_path / ".jwt_secret").write_text("current-secret", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "webui.json",
            json.dumps({"access_token": "archived-token", "port": 6000, "custom": True}),
        )
        archive.writestr(".jwt_secret", "archived-secret")
        archive.writestr("plugin_data/example/item.txt", "restored")

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert restored_config["port"] == 6000
    assert restored_config["custom"] is True
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "current-secret"
    assert (data_path / "plugin_data" / "example" / "item.txt").read_text(encoding="utf-8") == "restored"


def test_restore_live_credentials_overwrites_applied_credential_files(backup_routes):
    # Path-alias tricks end as writes to the canonical files, so the guard must
    # restore them from the snapshot regardless of how the archive got there.
    _, data_path = backup_routes
    (data_path / "webui.json").write_text(
        json.dumps({"access_token": "archived-token", "port": 6000}), encoding="utf-8"
    )
    (data_path / ".jwt_secret").write_text("archived-secret", encoding="utf-8")

    settings._restore_live_credentials(
        data_path,
        "current-token",
        True,
        {"access_token": "current-token", "token_setup_done": True},
        b"current-secret",
        app_state=None,
    )

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert restored_config["token_setup_done"] is True
    assert restored_config["port"] == 6000
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "current-secret"


def test_restore_falls_back_to_in_memory_token_when_config_has_no_token(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text('{"port": 5267}', encoding="utf-8")
    routes.app.state.access_token = "runtime-token"
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token", "port": 6000}))

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "runtime-token"
    assert restored_config["port"] == 6000


def test_restore_adopts_archive_token_but_keeps_running_signing_key(backup_routes):
    routes, data_path = backup_routes
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".jwt_secret", "archived-secret")

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "archived-token"
    # A session minted by this process must survive the restart, and an archive
    # must not be able to substitute a signing key it knows.
    assert (data_path / ".jwt_secret").read_bytes() == webui_utils._JWT_SECRET.encode("utf-8")


def test_restore_reports_failure_when_credentials_cannot_be_preserved(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    (data_path / ".jwt_secret").write_text("current-secret", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".jwt_secret", "archived-secret")
        archive.writestr("ordinary.txt", "restored")

    real_write = settings._write_bytes_atomic

    def deny_credential_write(path, data):
        if path.name in ("webui.json", ".jwt_secret"):
            raise PermissionError("file is locked")
        real_write(path, data)

    monkeypatch.setattr(settings, "_write_bytes_atomic", deny_credential_write)

    result = routes._do_restore(archive_path)

    assert result.success is False
    assert "active credentials could not be preserved" in result.message
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


def test_rejected_archive_does_not_rewrite_live_credentials(backup_routes):
    routes, data_path = backup_routes
    routes.app.state.access_token = "stale-token"
    live_config = json.dumps({"access_token": "edited-token", "port": 5267})
    (data_path / "webui.json").write_text(live_config, encoding="utf-8")

    with pytest.raises(HTTPException) as exc_info:
        routes._do_restore(io.BytesIO(b"not a zip"))

    assert exc_info.value.status_code == 400
    assert (data_path / "webui.json").read_text(encoding="utf-8") == live_config


@pytest.mark.anyio
async def test_change_access_token_persists_and_updates_runtime_token(backup_routes, monkeypatch):
    routes, _ = backup_routes
    routes.app.state.access_token = "current-token"
    routes.app.state.disable_auth = False
    saved = []
    monkeypatch.setattr(settings, "_update_webui_config", lambda **changes: saved.append(changes))
    request = SimpleNamespace(app=routes.app)

    assert await routes.change_access_token(
        ChangeTokenRequest(old_token="current-token", new_token="  new-token  "), request
    ) == {"success": True}
    assert saved == [{"access_token": "new-token"}]
    assert routes.app.state.access_token == "new-token"

    with pytest.raises(HTTPException) as exc_info:
        await routes.change_access_token(
            ChangeTokenRequest(old_token="current-token", new_token="another-token"), request
        )
    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_change_access_token_returns_409_when_maintenance_lock_is_held(backup_routes, monkeypatch):
    routes, _ = backup_routes
    routes.app.state.access_token = "current-token"
    routes.app.state.disable_auth = False
    monkeypatch.setattr(settings, "MAINTENANCE_LOCK_TIMEOUT_SECONDS", 0.05)
    saved = []
    monkeypatch.setattr(settings, "_update_webui_config", lambda **changes: saved.append(changes))
    request = SimpleNamespace(app=routes.app)

    await routes._maintenance_lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc_info:
            # Fail fast if the lock wait regresses into blocking forever.
            await asyncio.wait_for(
                routes.change_access_token(
                    ChangeTokenRequest(old_token="current-token", new_token="new-token"), request
                ),
                timeout=2,
            )
        assert exc_info.value.status_code == 409
        assert routes.app.state.access_token == "current-token"
        assert saved == []
        assert routes._maintenance_lock.locked()
    finally:
        routes._maintenance_lock.release()

    # Once the restore finishes, the token change goes through.
    assert await routes.change_access_token(
        ChangeTokenRequest(old_token="current-token", new_token="new-token"), request
    ) == {"success": True}
    assert routes.app.state.access_token == "new-token"


@pytest.mark.anyio
async def test_change_access_token_waits_for_in_flight_restore(backup_routes, monkeypatch):
    routes, _ = backup_routes
    routes.app.state.access_token = "current-token"
    routes.app.state.disable_auth = False
    monkeypatch.setattr(settings, "MAINTENANCE_LOCK_TIMEOUT_SECONDS", 1.0)
    monkeypatch.setattr(settings, "_update_webui_config", lambda **changes: None)
    request = SimpleNamespace(app=routes.app)

    await routes._maintenance_lock.acquire()
    released = asyncio.Event()

    async def finish_restore():
        await asyncio.sleep(0.05)
        released.set()
        routes._maintenance_lock.release()

    restore = asyncio.create_task(finish_restore())
    try:
        assert await routes.change_access_token(
            ChangeTokenRequest(old_token="current-token", new_token="new-token"), request
        ) == {"success": True}
        # Without taking the lock the token change would finish before the
        # in-flight restore task ever runs.
        assert released.is_set()
        assert routes.app.state.access_token == "new-token"
    finally:
        await restore


@pytest.mark.anyio
async def test_onboarding_token_setup_returns_409_while_restore_runs(backup_routes, monkeypatch):
    routes, _ = backup_routes
    updates = []
    monkeypatch.setattr(auth_routes, "_load_webui_config", lambda: {"token_setup_done": False})
    monkeypatch.setattr(auth_routes, "_update_webui_config", lambda **changes: updates.append(changes))
    monkeypatch.setattr(settings, "MAINTENANCE_LOCK_TIMEOUT_SECONDS", 0.05)
    auth = auth_routes.AuthRoutes(
        FastAPI(), SimpleNamespace(kira_config={"onboarding": {}}), "token", Path(".")
    )
    request = SimpleNamespace(app=auth.app)
    request.app.state.access_token = "old-token"

    await routes._maintenance_lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc_info:
            # Fail fast instead of hanging the setup form behind a restore.
            await asyncio.wait_for(
                auth.setup_onboarding_token(OnboardingTokenSetupRequest(token="new-token"), request),
                timeout=2,
            )
        assert exc_info.value.status_code == 409
        assert updates == []
        assert request.app.state.access_token == "old-token"
        assert routes._maintenance_lock.locked()
    finally:
        routes._maintenance_lock.release()

    # Once the restore finishes, the rotation goes through and updates any
    # stale rollback marker so it cannot revert the new token later.
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(json.dumps({"access_token": "old-token"}), encoding="utf-8")
    response = await auth.setup_onboarding_token(
        OnboardingTokenSetupRequest(token="new-token"), request
    )
    assert json.loads(response.body)["skipped"] is False
    assert updates == [{"access_token": "new-token", "token_setup_done": True}]
    assert request.app.state.access_token == "new-token"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["access_token"] == "new-token"
    # The endpoint must release the shared lock, not just the test's hold.
    assert not routes._maintenance_lock.locked()


class _OnboardingConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save_config(self):
        self.save_calls += 1


@pytest.mark.anyio
async def test_onboarding_completion_returns_409_while_restore_runs(backup_routes, monkeypatch):
    routes, _ = backup_routes
    monkeypatch.setattr(settings, "MAINTENANCE_LOCK_TIMEOUT_SECONDS", 0.05)
    config = _OnboardingConfig({"onboarding": {}})
    auth = auth_routes.AuthRoutes(FastAPI(), SimpleNamespace(kira_config=config), "token", Path("."))

    await routes._maintenance_lock.acquire()
    try:
        with pytest.raises(HTTPException) as exc_info:
            await asyncio.wait_for(
                auth.complete_onboarding(OnboardingCompleteRequest(lang="en", timezone="UTC")),
                timeout=2,
            )
        assert exc_info.value.status_code == 409
        assert config == {"onboarding": {}}
        assert config.save_calls == 0
        assert routes._maintenance_lock.locked()
    finally:
        routes._maintenance_lock.release()

    response = await auth.complete_onboarding(OnboardingCompleteRequest(lang="en", timezone="UTC"))
    assert response.completed is True
    assert config["onboarding"]["completed"] is True
    assert config["locale"]["lang"] == "en"
    assert config.save_calls == 1
    assert not routes._maintenance_lock.locked()


def test_restore_drops_archive_signing_key_when_env_supplies_it(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    monkeypatch.setenv("JWT_SECRET", "env-secret")
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".jwt_secret", "archived-secret")
        archive.writestr("ordinary.txt", "restored")

    assert routes._do_restore(archive_path).success

    # The env key wins at runtime, and backups must never capture it or the
    # archive's substitute.
    assert not (data_path / ".jwt_secret").exists()
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


def test_restore_drops_archive_signing_key_directory_when_env_supplies_it(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    monkeypatch.setenv("JWT_SECRET", "env-secret")
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(".jwt_secret/", b"")
        archive.writestr("ordinary.txt", "restored")

    result = routes._do_restore(archive_path)

    assert result.success
    # A directory left at this path would block key persistence on every
    # later start that has no JWT_SECRET.
    assert not (data_path / ".jwt_secret").exists()
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


def test_restore_replaces_archive_signing_key_directory_with_running_key(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(".jwt_secret/", b"")
        archive.writestr("ordinary.txt", "restored")

    assert routes._do_restore(archive_path).success

    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == webui_utils._JWT_SECRET
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes only")
def test_restore_keeps_identical_credentials_owner_only(backup_routes):
    routes, data_path = backup_routes
    routes.app.state.access_token = "current-token"
    config = json.dumps({"access_token": "current-token", "token_setup_done": True})
    (data_path / "webui.json").write_text(config, encoding="utf-8")
    (data_path / ".jwt_secret").write_text("current-secret", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", config)
        archive.writestr(".jwt_secret", "current-secret")

    assert routes._do_restore(archive_path).success

    # copy2 keeps the staged (usually 0644) mode when the values are equal;
    # credential files must stay owner-only anyway.
    for name in ("webui.json", ".jwt_secret"):
        assert stat.S_IMODE(os.stat(data_path / name).st_mode) == 0o600


def test_restore_repairs_config_with_unencodable_archived_field(backup_routes):
    routes, data_path = backup_routes
    routes.app.state.access_token = "current-token"
    (data_path / "webui.json").write_text(
        json.dumps({"access_token": "current-token", "token_setup_done": True}), encoding="utf-8"
    )
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "webui.json", '{"access_token": "archived-token", "note": "\\ud800"}'
        )
        archive.writestr("ordinary.txt", "restored")

    result = routes._do_restore(archive_path)

    assert result.success
    restored = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored["access_token"] == "current-token"
    assert restored["token_setup_done"] is True
    assert restored["note"] == "\ud800"


def test_restore_preserves_preexisting_directory_at_signing_key_path(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    secret_dir = data_path / ".jwt_secret"
    secret_dir.mkdir()
    (secret_dir / "user_notes.txt").write_text("keep me", encoding="utf-8")
    # The archive never touches the credential path, so nothing may delete it.
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ordinary.txt", "restored")

    result = routes._do_restore(archive_path)

    assert result.success is False
    assert "active credentials could not be preserved" in result.message
    assert (secret_dir / "user_notes.txt").read_text(encoding="utf-8") == "keep me"


def test_restore_preserves_preexisting_directory_at_live_config_path(backup_routes):
    routes, data_path = backup_routes
    routes.app.state.access_token = "current-token"
    config_dir = data_path / "webui.json"
    config_dir.mkdir()
    (config_dir / "user_notes.txt").write_text("keep me", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("ordinary.txt", "restored")

    result = routes._do_restore(archive_path)

    assert result.success is False
    assert "active credentials could not be preserved" in result.message
    assert (config_dir / "user_notes.txt").read_text(encoding="utf-8") == "keep me"


class _SimulatedCrash(BaseException):
    pass


def _crash_before_reassert(monkeypatch):
    real_write = settings._write_restore_marker

    def write_then_crash(credentials):
        handle = real_write(credentials)
        # A dead process releases its OS lock but leaves the marker behind.
        handle.close()
        return handle

    monkeypatch.setattr(settings, "_write_restore_marker", write_then_crash)

    def crash(*args, **kwargs):
        raise _SimulatedCrash

    monkeypatch.setattr(settings, "_restore_live_credentials", crash)


def test_restore_removes_marker_after_success(backup_routes):
    routes, data_path = backup_routes
    routes.app.state.access_token = "current-token"
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr("ordinary.txt", "restored")

    assert routes._do_restore(archive_path).success

    assert not webui_utils._restore_marker_path().exists()


def test_interrupted_restore_marker_restores_credentials_on_next_start(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    (data_path / ".jwt_secret").write_text("current-secret", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".jwt_secret", "archived-secret")
        archive.writestr("ordinary.txt", "restored")
    marker_path = webui_utils._restore_marker_path()

    _crash_before_reassert(monkeypatch)
    with pytest.raises(_SimulatedCrash):
        routes._do_restore(archive_path)

    # The archived credentials went live, but the marker still holds the old ones.
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "archived-token"
    assert (data_path / ".jwt_secret").read_bytes() == b"archived-secret"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["access_token"] == "current-token"

    monkeypatch.setattr(webui_utils, "get_data_path", lambda: data_path)
    webui_utils._recover_interrupted_restore()

    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"
    assert (data_path / ".jwt_secret").read_bytes() == b"current-secret"
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"
    assert not marker_path.exists()


def test_interrupted_restore_removes_archived_key_when_env_supplies_it(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    monkeypatch.setenv("JWT_SECRET", "env-secret")
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".jwt_secret", "archived-secret")

    _crash_before_reassert(monkeypatch)
    with pytest.raises(_SimulatedCrash):
        routes._do_restore(archive_path)
    assert (data_path / ".jwt_secret").exists()
    marker = json.loads(webui_utils._restore_marker_path().read_text(encoding="utf-8"))
    # An env-supplied key must never be written to disk, marker included.
    assert marker["jwt_secret"] is None
    assert marker["jwt_secret_from_env"] is True

    webui_utils._recover_interrupted_restore()

    # The env key must not leak into the file the archive created.
    assert not (data_path / ".jwt_secret").exists()
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"
    assert not webui_utils._restore_marker_path().exists()


def test_interrupted_restore_keeps_marker_when_rollback_fails(backup_routes, monkeypatch):
    _, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "archived-token"}), encoding="utf-8")
    secret_dir = data_path / ".jwt_secret"
    secret_dir.mkdir()
    (secret_dir / "user_notes.txt").write_text("keep me", encoding="utf-8")
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "access_token": "current-token",
                "token_setup_done": False,
                "jwt_secret": base64.b64encode(b"current-secret").decode("ascii"),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(webui_utils, "get_data_path", lambda: data_path)
    webui_utils._recover_interrupted_restore()

    # The config is repaired, but the key path stays blocked, so the marker
    # stays for the next start instead of discarding the rollback data.
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"
    assert (secret_dir / "user_notes.txt").read_text(encoding="utf-8") == "keep me"
    assert marker_path.exists()


def test_backup_and_restore_ignore_restore_marker(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    (data_path / "keep.txt").write_text("keep", encoding="utf-8")

    result = routes._create_backup_sync()

    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert set(archive.namelist()) == {"keep.txt", "webui.json"}

    archive_path = data_path / "planted.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(webui_utils.RESTORE_MARKER_NAME, json.dumps({"access_token": "planted-token"}))
        archive.writestr(f"{webui_utils.RESTORE_MARKER_NAME}.", json.dumps({"access_token": "planted-token"}))
        archive.writestr(
            f"{webui_utils.BACKUP_DIR_NAME}/{webui_utils.RESTORE_MARKER_NAME}",
            json.dumps({"access_token": "planted-token"}),
        )
        archive.writestr("ordinary.txt", "restored")

    # Stop before the re-assert so the live marker is the one that survives.
    _crash_before_reassert(monkeypatch)
    with pytest.raises(_SimulatedCrash):
        routes._do_restore(archive_path)

    # An archive must not plant a marker that a later restart would trust.
    assert json.loads(marker_path.read_text(encoding="utf-8"))["access_token"] == "current-token"
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


@pytest.mark.skipif(os.name != "nt", reason="Windows name aliasing")
def test_restore_rejects_archive_that_aliases_the_backup_directory(backup_routes):
    routes, data_path = backup_routes
    archive_path = data_path / "alias.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        # Win32 strips the trailing dot, so this lands in data/backups/.
        archive.writestr(
            f"{webui_utils.BACKUP_DIR_NAME}./{webui_utils.RESTORE_MARKER_NAME}",
            json.dumps({"access_token": "planted-token"}),
        )

    with pytest.raises(HTTPException) as exc_info:
        routes._do_restore(archive_path)

    assert exc_info.value.status_code == 400


@pytest.mark.anyio
async def test_change_access_token_keeps_pending_key_rollback(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    routes.app.state.access_token = "old-token"
    routes.app.state.disable_auth = False
    (data_path / "webui.json").write_text(json.dumps({"access_token": "old-token"}), encoding="utf-8")
    (data_path / ".jwt_secret").write_text("archived-secret", encoding="utf-8")
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "access_token": "old-token",
                "token_setup_done": False,
                "jwt_secret": base64.b64encode(b"current-secret").decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "_update_webui_config", lambda **changes: None)

    assert await routes.change_access_token(
        ChangeTokenRequest(old_token="old-token", new_token="new-token"),
        SimpleNamespace(app=routes.app),
    ) == {"success": True}

    # The rotation is recorded, but the key repair stays pending.
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["access_token"] == "new-token"
    assert marker["jwt_secret"] == base64.b64encode(b"current-secret").decode("ascii")

    webui_utils._recover_interrupted_restore()

    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "new-token"
    assert (data_path / ".jwt_secret").read_bytes() == b"current-secret"
    assert not marker_path.exists()


@pytest.mark.anyio
async def test_change_access_token_fails_when_marker_cannot_be_updated(backup_routes, monkeypatch):
    routes, _ = backup_routes
    routes.app.state.access_token = "old-token"
    routes.app.state.disable_auth = False
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(json.dumps({"access_token": "old-token"}), encoding="utf-8")
    saved = []
    monkeypatch.setattr(settings, "_update_webui_config", lambda **changes: saved.append(changes))

    def deny_marker_write(path, data):
        if Path(path).name == webui_utils.RESTORE_MARKER_NAME:
            raise PermissionError("marker is read-only")
        return real_write(path, data)

    real_write = settings._write_bytes_atomic
    monkeypatch.setattr(settings, "_write_bytes_atomic", deny_marker_write)

    with pytest.raises(HTTPException) as exc_info:
        await routes.change_access_token(
            ChangeTokenRequest(old_token="old-token", new_token="new-token"),
            SimpleNamespace(app=routes.app),
        )

    # Rotating without updating the marker would let a restart revert the token.
    assert exc_info.value.status_code == 500
    assert saved == []
    assert routes.app.state.access_token == "old-token"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["access_token"] == "old-token"


def test_recovery_leaves_marker_locked_by_a_live_restore(backup_routes):
    _, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "archived-token"}), encoding="utf-8")
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")

    with marker_path.open("r+b") as handle:
        assert webui_utils._try_lock_restore_marker(handle)
        # Another process importing mid-restore must not roll it back.
        webui_utils._recover_interrupted_restore()
        assert marker_path.exists()
        assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "archived-token"

    # Closing the handle releases the lock, as a dying process would.
    webui_utils._recover_interrupted_restore()

    assert not marker_path.exists()
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"


def test_unreadable_restore_marker_is_kept(backup_routes):
    _, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "archived-token"}), encoding="utf-8")
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_bytes(b"\x00truncated")

    webui_utils._recover_interrupted_restore()

    # Without readable rollback data the safe move is to keep the marker.
    assert marker_path.exists()
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "archived-token"


def test_recovery_replaces_directories_at_credential_paths(backup_routes):
    _, data_path = backup_routes
    (data_path / "webui.json").mkdir()
    (data_path / ".jwt_secret").mkdir()
    marker_path = webui_utils._restore_marker_path()
    marker_path.parent.mkdir(parents=True)
    marker_path.write_text(
        json.dumps(
            {
                "access_token": "current-token",
                "token_setup_done": False,
                "jwt_secret": base64.b64encode(b"current-secret").decode("ascii"),
            }
        ),
        encoding="utf-8",
    )

    webui_utils._recover_interrupted_restore()

    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"
    assert (data_path / ".jwt_secret").read_bytes() == b"current-secret"
    assert not marker_path.exists()


def test_startup_recovery_runs_before_secret_load(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    data_path = tmp_path / "data"
    marker_path = data_path / webui_utils.BACKUP_DIR_NAME / webui_utils.RESTORE_MARKER_NAME
    marker_path.parent.mkdir(parents=True)
    (data_path / "webui.json").write_text(json.dumps({"access_token": "archived-token"}), encoding="utf-8")
    (data_path / ".jwt_secret").write_text("archived-secret", encoding="utf-8")
    marker_path.write_text(
        json.dumps(
            {
                "access_token": "current-token",
                "token_setup_done": True,
                "jwt_secret": base64.b64encode(b"current-secret").decode("ascii"),
            }
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo_root) + os.pathsep + env.get("PYTHONPATH", "")
    env.pop("JWT_SECRET", None)

    result = subprocess.run(
        [sys.executable, "-c", "import webui.utils as u; print(u._JWT_SECRET)"],
        check=False,
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    # The rollback must happen before the module key is loaded, or this
    # process would sign sessions with the archive's key.
    assert result.stdout.strip() == "current-secret"
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "current-secret"
    config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert config["access_token"] == "current-token"
    assert config["token_setup_done"] is True
    assert not marker_path.exists()


def test_restore_keeps_credentials_when_copy_fails_midway(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", json.dumps({"access_token": "archived-token"}))

    real_copy2 = settings.shutil.copy2

    def copy_then_fail(src, dst, *args, **kwargs):
        real_copy2(src, dst, *args, **kwargs)
        if Path(dst).name == "webui.json":
            raise OSError("disk full")

    monkeypatch.setattr(settings.shutil, "copy2", copy_then_fail)

    result = routes._do_restore(archive_path)

    assert result.success is False
    assert json.loads((data_path / "webui.json").read_text(encoding="utf-8"))["access_token"] == "current-token"


def test_restore_keeps_setup_flag_without_live_token(backup_routes):
    routes, data_path = backup_routes
    routes.lifecycle = SimpleNamespace(kira_config={"onboarding": {"completed": True}})
    (data_path / "webui.json").write_text(json.dumps({"port": 5267}), encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "webui.json",
            json.dumps({"access_token": "archived-token", "token_setup_done": False, "port": 6000}),
        )

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "archived-token"
    assert restored_config["token_setup_done"] is True
    assert restored_config["port"] == 6000


@pytest.mark.anyio
async def test_restore_holds_lock_until_worker_finishes(backup_routes, monkeypatch):
    routes, data_path = backup_routes
    backup_dir = data_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "sample.zip").write_bytes(b"zip")
    started = threading.Event()
    release = threading.Event()

    def fake_restore(_source):
        started.set()
        release.wait(timeout=10)
        return settings.RestoreResponse(success=True, message="ok")

    monkeypatch.setattr(routes, "_do_restore", fake_restore)
    task = asyncio.create_task(routes.restore_from_backup("sample.zip"))
    try:
        deadline = asyncio.get_running_loop().time() + 5
        while not started.is_set():
            if task.done():
                # Surface the original failure instead of polling forever.
                await task
                pytest.fail("restore returned before the worker started")
            if asyncio.get_running_loop().time() > deadline:
                pytest.fail("restore worker did not start in time")
            await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.sleep(0.05)

        # Cancelling the request must not release the maintenance gate while the
        # restore thread still runs, or a token change could be overwritten.
        assert routes._maintenance_lock.locked()
    finally:
        release.set()
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not routes._maintenance_lock.locked()


def test_restore_forces_token_setup_done_after_completed_onboarding(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(settings.SettingsRoutes, "_maintenance_lock", asyncio.Lock())
    lifecycle = SimpleNamespace(kira_config={"onboarding": {"completed": True}})
    routes = settings.SettingsRoutes(FastAPI(), lifecycle)
    (tmp_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    archive_path = tmp_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "webui.json",
            json.dumps({"access_token": "archived-token", "token_setup_done": False}),
        )

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((tmp_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert restored_config["token_setup_done"] is True


def test_read_live_credentials_prefers_disk_token_over_disabled_sentinel(backup_routes):
    _, data_path = backup_routes
    (data_path / "webui.json").write_text(json.dumps({"access_token": "disk-token"}), encoding="utf-8")

    token, _, _, _, _ = settings._read_live_credentials(data_path, SimpleNamespace(access_token="disabled"))

    assert token == "disk-token"


def test_restore_keeps_credentials_despite_case_variant_entry_names(backup_routes):
    routes, data_path = backup_routes
    probe = data_path / "case_probe"
    probe.write_text("", encoding="utf-8")
    try:
        case_insensitive = (data_path / "CASE_PROBE").exists()
    finally:
        probe.unlink()
    if not case_insensitive:
        pytest.skip("needs a case-insensitive filesystem to alias the credential paths")
    (data_path / "webui.json").write_text(json.dumps({"access_token": "current-token"}), encoding="utf-8")
    (data_path / ".jwt_secret").write_text("current-secret", encoding="utf-8")
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("WEBUI.JSON", json.dumps({"access_token": "archived-token"}))
        archive.writestr(".JWT_SECRET", "archived-secret")
        archive.writestr("ordinary.txt", "restored")

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert (data_path / ".jwt_secret").read_text(encoding="utf-8") == "current-secret"
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"


def test_restore_keeps_token_setup_done_from_live_config(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(
        json.dumps({"access_token": "current-token", "token_setup_done": True}),
        encoding="utf-8",
    )
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr(
            "webui.json",
            json.dumps({"access_token": "archived-token", "token_setup_done": False, "port": 6000}),
        )

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert restored_config["token_setup_done"] is True
    assert restored_config["port"] == 6000


def test_restore_replaces_invalid_archived_webui_config(backup_routes):
    routes, data_path = backup_routes
    (data_path / "webui.json").write_text(
        json.dumps({"access_token": "current-token", "port": 5267}), encoding="utf-8"
    )
    archive_path = data_path / "restore.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("webui.json", b"{not json")
        archive.writestr("ordinary.txt", "restored")

    assert routes._do_restore(archive_path).success

    restored_config = json.loads((data_path / "webui.json").read_text(encoding="utf-8"))
    assert restored_config["access_token"] == "current-token"
    assert restored_config["port"] == 5267
    assert (data_path / "ordinary.txt").read_text(encoding="utf-8") == "restored"
