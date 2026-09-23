import asyncio
import os
import stat
import time
from pathlib import Path

import pytest

from core import temp_monitor
from core.temp_monitor import AsyncTempMonitor


class FakeConfig:
    def __init__(self, cache_config):
        self.cache_config = cache_config

    def get_config(self, key, default=None):
        if key == "bot_config.cache":
            return self.cache_config
        return default


def make_monitor(tmp_path, **cache_overrides):
    cache_config = {
        "max_size_mb": 50,
        "max_files": 50,
        "max_age_hours": 24,
    }
    cache_config.update(cache_overrides)
    return AsyncTempMonitor(
        str(tmp_path),
        FakeConfig(cache_config),
        check_interval=0,
        file_protection_seconds=0,
    )


@pytest.mark.asyncio
async def test_delete_file_retries_once_after_permission_error(tmp_path, monkeypatch):
    target = tmp_path / "readonly.bin"
    target.write_bytes(b"content")
    original_unlink = Path.unlink
    original_chmod = Path.chmod
    unlink_calls = 0
    chmod_modes = []

    def flaky_unlink(path, *args, **kwargs):
        nonlocal unlink_calls
        if path == target:
            unlink_calls += 1
            if unlink_calls == 1:
                raise PermissionError("read-only")
        return original_unlink(path, *args, **kwargs)

    def record_chmod(path, mode, *args, **kwargs):
        if path == target:
            chmod_modes.append(mode)
        return original_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    monkeypatch.setattr(Path, "chmod", record_chmod)

    monitor = make_monitor(tmp_path)
    status, deleted_size, error = await monitor._delete_file(str(target))

    assert status == "deleted"
    assert deleted_size == len(b"content")
    assert error is None
    assert unlink_calls == 2
    assert len(chmod_modes) == 1
    assert chmod_modes[0] & stat.S_IWRITE
    assert not target.exists()


@pytest.mark.asyncio
async def test_cleanup_retries_failed_file_after_size_returns_below_limit(
    tmp_path, monkeypatch
):
    locked = tmp_path / "locked.bin"
    removable = tmp_path / "removable.bin"
    locked.write_bytes(b"a" * 600)
    removable.write_bytes(b"b" * 600)
    old_time = time.time() - 3600
    os.utime(locked, (old_time, old_time))
    os.utime(removable, (old_time + 10, old_time + 10))

    monitor = make_monitor(tmp_path, max_size_mb=0.001)
    original_delete = monitor._delete_file
    delete_calls = []

    async def fail_locked(path_str, expected_version=None):
        delete_calls.append(path_str)
        if path_str == str(locked):
            if delete_calls.count(path_str) == 1:
                os.utime(locked, None)
            return "failed", 0, "PermissionError: locked"
        return await original_delete(path_str, expected_version)

    warnings = []
    monkeypatch.setattr(monitor, "_delete_file", fail_locked)
    monkeypatch.setattr(temp_monitor.logger, "warning", warnings.append)

    await monitor.cleanup()

    assert locked.exists()
    assert not removable.exists()
    assert monitor.total_size < monitor.max_size_bytes
    assert str(locked) in monitor._pending_retries
    assert len(warnings) == 1

    await monitor.cleanup()

    assert delete_calls.count(str(locked)) == 2
    assert len(warnings) == 2
    assert "next cleanup cycle" in warnings[-1]


@pytest.mark.asyncio
async def test_cleanup_removes_nested_empty_directories_in_one_cycle(tmp_path):
    nested_dir = tmp_path / "job" / "repo" / ".git" / "objects"
    nested_dir.mkdir(parents=True)
    target = nested_dir / "old.bin"
    target.write_bytes(b"content")
    old_time = time.time() - 3600
    os.utime(target, (old_time, old_time))
    for directory in [
        nested_dir,
        nested_dir.parent,
        nested_dir.parent.parent,
        tmp_path / "job",
    ]:
        os.utime(directory, (old_time, old_time))

    monitor = make_monitor(tmp_path, max_age_hours=0)
    await monitor.cleanup()

    assert not target.exists()
    assert not (tmp_path / "job").exists()
    assert tmp_path.exists()


@pytest.mark.asyncio
async def test_configured_check_interval_updates_at_runtime(tmp_path):
    config = FakeConfig(
        {
            "max_size_mb": 50,
            "max_files": 50,
            "max_age_hours": 24,
            "check_interval_minutes": 5,
        }
    )
    monitor = AsyncTempMonitor(str(tmp_path), config, check_interval=60)

    assert monitor.check_interval == 5 * 60

    config.cache_config["check_interval_minutes"] = 2
    monitor.notify_config_changed()

    assert monitor.check_interval == 2 * 60
    assert monitor._config_changed_event.is_set()

    config.cache_config["check_interval_minutes"] = 0.01
    monitor.notify_config_changed()

    assert monitor.check_interval == 1


@pytest.mark.asyncio
async def test_cleanup_preserves_recent_empty_directories(tmp_path):
    recent_dir = tmp_path / "recent"
    old_dir = tmp_path / "old"
    recent_dir.mkdir()
    old_dir.mkdir()
    old_time = time.time() - 120
    os.utime(old_dir, (old_time, old_time))

    monitor = AsyncTempMonitor(
        str(tmp_path),
        FakeConfig({}),
        file_protection_seconds=60,
    )
    await monitor.cleanup()

    assert recent_dir.exists()
    assert not old_dir.exists()


@pytest.mark.asyncio
async def test_cleanup_rescans_files_created_after_startup(tmp_path):
    monitor = make_monitor(tmp_path, max_size_mb=0)
    await monitor.cleanup()

    target = tmp_path / "new.bin"
    target.write_bytes(b"content")

    await monitor.cleanup()

    assert not target.exists()
    assert monitor.file_cache == {}
    assert monitor.total_size == 0


@pytest.mark.asyncio
async def test_cleanup_skips_file_changed_after_scan(tmp_path, monkeypatch):
    target = tmp_path / "changing.bin"
    target.write_bytes(b"old")
    monitor = make_monitor(tmp_path, max_size_mb=0)
    original_scan = monitor._scan_folder

    async def scan_then_change():
        directory_candidates = await original_scan()
        target.write_bytes(b"replacement")
        return directory_candidates

    monkeypatch.setattr(monitor, "_scan_folder", scan_then_change)

    await monitor.cleanup()

    assert target.read_bytes() == b"replacement"
    assert str(target) not in monitor._pending_retries


@pytest.mark.asyncio
async def test_stop_monitoring_wakes_periodic_scheduler(tmp_path):
    monitor = AsyncTempMonitor(
        str(tmp_path),
        FakeConfig({"check_interval_minutes": 5}),
    )
    task = asyncio.create_task(monitor._periodic_cleanup_loop())
    await asyncio.sleep(0)

    await monitor.stop_monitoring()
    await asyncio.wait_for(task, timeout=1)

    assert task.done()
