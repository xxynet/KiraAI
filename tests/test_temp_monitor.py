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
async def test_cleanup_summarizes_failures_once_and_retries_next_cycle(
    tmp_path, monkeypatch
):
    target = tmp_path / "locked.bin"
    target.write_bytes(b"content")
    old_time = time.time() - 3600
    os.utime(target, (old_time, old_time))

    monitor = make_monitor(tmp_path, max_size_mb=0, max_age_hours=0)
    await monitor._build_cache()

    delete_calls = []

    async def fail_delete(path_str):
        delete_calls.append(path_str)
        return "failed", 0, "PermissionError: locked"

    warnings = []
    monkeypatch.setattr(monitor, "_delete_file", fail_delete)
    monkeypatch.setattr(temp_monitor.logger, "warning", warnings.append)

    await monitor.cleanup()

    assert delete_calls == [str(target)]
    assert len(warnings) == 1
    assert "1 deletion failure(s)" in warnings[0]
    assert "next cleanup cycle" in warnings[0]
    assert str(target) in monitor.file_cache

    monitor.last_check_time = 0
    await monitor.cleanup()

    assert delete_calls == [str(target), str(target)]
    assert len(warnings) == 2


@pytest.mark.asyncio
async def test_cleanup_removes_empty_directories(tmp_path):
    nested_dir = tmp_path / "job" / "repo" / ".git" / "objects"
    nested_dir.mkdir(parents=True)
    target = nested_dir / "old.bin"
    target.write_bytes(b"content")
    old_time = time.time() - 3600
    os.utime(target, (old_time, old_time))

    monitor = make_monitor(tmp_path, max_age_hours=0)
    await monitor._build_cache()
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
