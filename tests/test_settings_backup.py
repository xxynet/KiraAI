import asyncio
import threading
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from webui.routes import settings
from webui.routes.auth import require_auth


@pytest.fixture
def backup_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(settings.SettingsRoutes, "_maintenance_lock", asyncio.Lock())
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


def test_empty_backup_is_valid(backup_routes):
    routes, data_path = backup_routes
    result = routes._create_backup_sync()
    with zipfile.ZipFile(data_path / "backups" / result.filename) as archive:
        assert archive.namelist() == []


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
async def test_completed_archive_is_visible_and_downloadable(backup_routes, backup_clock):
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
