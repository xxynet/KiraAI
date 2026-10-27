import asyncio
import io
import json
import threading
import zipfile
from pathlib import Path

import pytest

from core.plugin import plugin_installer


def _plugin_archive(plugin_id: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("plugin-main/manifest.json", json.dumps({"plugin_id": plugin_id}))
        archive.writestr("plugin-main/main.py", "# plugin entry point\n")
    return buffer.getvalue()


def test_install_rejects_registered_plugin_before_extraction(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    with pytest.raises(plugin_installer.PluginAlreadyInstalledError):
        asyncio.run(
            plugin_installer.install_from_zip(
                _plugin_archive("existing-plugin"),
                tmp_path / "plugins",
                is_plugin_installed=lambda plugin_id: plugin_id == "existing-plugin",
            )
        )

    assert not (tmp_path / "plugins" / "existing-plugin").exists()
    assert not list((tmp_path / "temp").glob("extract_*"))


def test_update_replaces_legacy_plugin_directory(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    legacy_dir = plugins_dir / "repository-folder"
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "stale.txt").write_text("old plugin", encoding="utf-8")
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    installed_dir = asyncio.run(
        plugin_installer.install_from_zip(
            _plugin_archive("plugin-id"),
            plugins_dir,
            target_dir=legacy_dir,
        )
    )

    assert installed_dir == legacy_dir
    assert not (legacy_dir / "stale.txt").exists()
    assert not (plugins_dir / "plugin-id").exists()


def test_update_rejects_a_changed_plugin_id_before_replacing_files(tmp_path, monkeypatch):
    plugins_dir = tmp_path / "plugins"
    legacy_dir = plugins_dir / "repository-folder"
    legacy_dir.mkdir(parents=True)
    stale_file = legacy_dir / "stale.txt"
    stale_file.write_text("old plugin", encoding="utf-8")
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)

    with pytest.raises(ValueError, match="Plugin identity changed"):
        asyncio.run(
            plugin_installer.install_from_zip(
                _plugin_archive("different-plugin-id"),
                plugins_dir,
                target_dir=legacy_dir,
                expected_plugin_id="plugin-id",
            )
        )

    assert stale_file.read_text(encoding="utf-8") == "old plugin"
    assert not (legacy_dir / "main.py").exists()


def test_install_from_github_downloads_the_requested_commit(tmp_path, monkeypatch):
    downloaded_urls = []

    async def fake_download(url, target, proxy=None, max_bytes=None):
        downloaded_urls.append((url, max_bytes))
        Path(target).write_bytes(_plugin_archive("plugin-id"))

    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "download_file", fake_download)
    commit_sha = "a" * 40

    asyncio.run(
        plugin_installer.install_from_github(
            "https://github.com/example/plugin",
            tmp_path / "plugins",
            commit_sha=commit_sha,
        )
    )

    assert downloaded_urls == [(
        f"https://github.com/example/plugin/archive/{commit_sha}.zip",
        plugin_installer.MAX_PLUGIN_ARCHIVE_BYTES,
    )]


@pytest.mark.anyio
async def test_cancelled_upload_waits_for_writer_and_cleans_temp_file(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    started = threading.Event()
    release = threading.Event()
    original_write_bytes = Path.write_bytes

    def blocking_write_bytes(path: Path, data: bytes):
        if path.parent == tmp_path / "temp" and path.name.startswith("upload_"):
            started.set()
            release.wait()
        return original_write_bytes(path, data)

    monkeypatch.setattr(Path, "write_bytes", blocking_write_bytes)
    install_task = asyncio.create_task(
        plugin_installer.install_from_zip(_plugin_archive("plugin-id"), tmp_path / "plugins")
    )
    await asyncio.to_thread(started.wait)

    try:
        install_task.cancel()
        await asyncio.sleep(0)
        assert not install_task.done()
        install_task.cancel()
        await asyncio.sleep(0)
        assert not install_task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await install_task

    assert not list((tmp_path / "temp").glob("upload_*.zip"))


@pytest.mark.anyio
async def test_cancelled_extraction_waits_for_worker_after_repeated_cancellation(
    tmp_path, monkeypatch
):
    temp_zip = tmp_path / "temp" / "upload_test.zip"
    temp_zip.parent.mkdir(parents=True)
    temp_zip.write_bytes(b"archive")
    started = threading.Event()
    release = threading.Event()
    worker_finished = threading.Event()

    def blocking_extract(path: Path, *_args):
        started.set()
        try:
            release.wait()
        finally:
            path.unlink(missing_ok=True)
            worker_finished.set()

    monkeypatch.setattr(plugin_installer, "_extract_and_install_sync", blocking_extract)
    install_task = asyncio.create_task(
        plugin_installer._extract_and_install(temp_zip, tmp_path / "plugins")
    )
    await asyncio.to_thread(started.wait)

    try:
        install_task.cancel()
        await asyncio.sleep(0)
        assert not install_task.done()
        install_task.cancel()
        await asyncio.sleep(0)
        assert not install_task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await install_task

    assert worker_finished.is_set()
    assert not temp_zip.exists()


def test_install_from_zip_rejects_oversized_archive_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "MAX_PLUGIN_ARCHIVE_BYTES", 1)

    with pytest.raises(ValueError, match="size limit"):
        asyncio.run(plugin_installer.install_from_zip(b"PK", tmp_path / "plugins"))

    assert not (tmp_path / "temp").exists()


def test_install_from_zip_rejects_excessive_uncompressed_content(tmp_path, monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin-main/manifest.json", json.dumps({"plugin_id": "plugin-id"}))
        archive.writestr("plugin-main/main.py", "x" * 500)
        for index in range(10):
            archive.writestr(f"plugin-main/module_{index}.py", "x" * 500)
    zip_bytes = buffer.getvalue()

    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "MAX_PLUGIN_ARCHIVE_BYTES", len(zip_bytes) + 1)

    with pytest.raises(ValueError, match="uncompressed size limit"):
        asyncio.run(plugin_installer.install_from_zip(zip_bytes, tmp_path / "plugins"))

    assert not (tmp_path / "plugins").exists()


def test_install_rejects_excessive_zip_directory_before_extracting(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "MAX_PLUGIN_ARCHIVE_FILE_COUNT", 1)

    with pytest.raises(ValueError, match="file limit"):
        asyncio.run(plugin_installer.install_from_zip(_plugin_archive("plugin-id"), tmp_path / "plugins"))


def test_install_rejects_oversized_zip_central_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(plugin_installer, "get_data_path", lambda: tmp_path)
    monkeypatch.setattr(plugin_installer, "MAX_PLUGIN_ARCHIVE_CENTRAL_DIRECTORY_BYTES", 1)

    with pytest.raises(ValueError, match="central directory"):
        asyncio.run(plugin_installer.install_from_zip(_plugin_archive("plugin-id"), tmp_path / "plugins"))

@pytest.mark.asyncio
async def test_requirements_timeout_kills_and_reaps_the_process(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("example", encoding="utf-8")
    real_create = asyncio.create_subprocess_exec
    processes = []

    async def hanging_process(*args, **kwargs):
        proc = await real_create(
            plugin_installer.sys.executable, "-c", "import time; time.sleep(30)", **kwargs,
        )
        processes.append(proc)
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", hanging_process)
    monkeypatch.setattr(plugin_installer, "PLUGIN_REQUIREMENTS_TIMEOUT_SECONDS", 0.05)
    warnings = await asyncio.wait_for(plugin_installer.install_requirements(tmp_path), 5)
    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert warnings == ["Dependency installation timed out after 0.05s"]


@pytest.fixture
def requirements_install_slot(monkeypatch):
    # Each test represents a separate application event-loop lifetime.
    monkeypatch.setattr(plugin_installer, "_requirements_install_lock", asyncio.Lock())


class RequirementsProcess:
    def __init__(self, *, blocked=False, auto_reap=True, returncode=0):
        self.returncode = None
        self.exit_code = returncode
        self.release = asyncio.Event()
        self.killed = asyncio.Event()
        self.auto_reap = auto_reap
        if not blocked:
            self.release.set()

    async def communicate(self):
        await self.release.wait()
        self.returncode = -9 if self.killed.is_set() else self.exit_code
        return b"", b"dependency resolution failed" if self.returncode else b""

    def kill(self):
        self.killed.set()
        if self.auto_reap:
            self.release.set()


def requirements_directory(root, name):
    directory = root / name
    directory.mkdir()
    (directory / "requirements.txt").write_text("example", encoding="utf-8")
    return directory


@pytest.mark.anyio
async def test_requirements_from_different_entry_points_share_install_slot(
    tmp_path, monkeypatch, requirements_install_slot,
):
    from core.plugin.manager import install_requirements as manager_install
    from webui.routes.plugins import install_requirements as web_install
    from webui.routes.releases import install_requirements as release_install

    first = RequirementsProcess(blocked=True)
    processes, commands = [], []
    spawned = asyncio.Event()

    async def spawn(*args, **kwargs):
        assert all(proc.returncode is not None for proc in processes)
        proc = first if not processes else RequirementsProcess()
        processes.append(proc)
        commands.append(args)
        spawned.set()
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    paths = [requirements_directory(tmp_path, name) for name in (
        "vector_dependencies", "plugin_manager", "web_plugin", "application_update",
    )]
    tasks = [asyncio.create_task(plugin_installer.install_requirements(paths[0]))]
    await asyncio.wait_for(spawned.wait(), 1)
    tasks.extend(asyncio.create_task(call(path)) for call, path in zip(
        (manager_install, web_install, release_install), paths[1:],
    ))
    try:
        await asyncio.sleep(0)
        assert len(processes) == 1
    finally:
        first.release.set()
    assert await asyncio.wait_for(asyncio.gather(*tasks), 2) == [[], [], [], []]
    assert len(processes) == 4
    assert {command[5] for command in commands} == {str(path / "requirements.txt") for path in paths}
    assert not plugin_installer._requirements_install_lock.locked()


@pytest.mark.anyio
async def test_cancelled_queued_install_does_not_start_pip_or_unlock_another_install(
    tmp_path, monkeypatch, requirements_install_slot,
):
    path = requirements_directory(tmp_path, "plugin")
    first = RequirementsProcess(blocked=True)
    processes = []
    spawned = asyncio.Event()

    async def spawn(*args, **kwargs):
        assert all(proc.returncode is not None for proc in processes)
        proc = first if not processes else RequirementsProcess()
        processes.append(proc)
        spawned.set()
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    active = asyncio.create_task(plugin_installer.install_requirements(path))
    await asyncio.wait_for(spawned.wait(), 1)
    queued = asyncio.create_task(plugin_installer.install_requirements(path))
    await asyncio.sleep(0)
    queued.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued
    assert plugin_installer._requirements_install_lock.locked()
    assert len(processes) == 1
    following = asyncio.create_task(plugin_installer.install_requirements(path))
    first.release.set()
    assert await asyncio.wait_for(asyncio.gather(active, following), 2) == [[], []]
    assert len(processes) == 2


@pytest.mark.anyio
async def test_repeated_cancel_holds_install_slot_until_process_is_reaped(
    tmp_path, monkeypatch, requirements_install_slot,
):
    path = requirements_directory(tmp_path, "plugin")
    first = RequirementsProcess(blocked=True, auto_reap=False)
    processes = []
    spawned = asyncio.Event()

    async def spawn(*args, **kwargs):
        assert all(proc.returncode is not None for proc in processes)
        proc = first if not processes else RequirementsProcess()
        processes.append(proc)
        spawned.set()
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    active = asyncio.create_task(plugin_installer.install_requirements(path))
    await asyncio.wait_for(spawned.wait(), 1)
    following = asyncio.create_task(plugin_installer.install_requirements(path))
    active.cancel()
    await asyncio.wait_for(first.killed.wait(), 1)
    try:
        active.cancel()
        await asyncio.sleep(0)
        active.cancel()
        await asyncio.sleep(0)
        assert not active.done()
        assert len(processes) == 1 and plugin_installer._requirements_install_lock.locked()
    finally:
        first.release.set()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert await asyncio.wait_for(following, 1) == []
    assert len(processes) == 2 and first.returncode is not None


@pytest.mark.anyio
async def test_cancel_during_spawn_waits_for_process_then_stops_it_before_next_install(
    tmp_path, monkeypatch, requirements_install_slot,
):
    path = requirements_directory(tmp_path, "plugin")
    entered, release = asyncio.Event(), asyncio.Event()
    first = RequirementsProcess(blocked=True)
    processes = []

    async def spawn(*args, **kwargs):
        assert all(proc.returncode is not None for proc in processes)
        if not processes:
            entered.set()
            await release.wait()
            proc = first
        else:
            proc = RequirementsProcess()
        processes.append(proc)
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    active = asyncio.create_task(plugin_installer.install_requirements(path))
    await asyncio.wait_for(entered.wait(), 1)
    active.cancel()
    following = asyncio.create_task(plugin_installer.install_requirements(path))
    try:
        await asyncio.sleep(0)
        active.cancel()
        await asyncio.sleep(0)
        assert not active.done() and not processes
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await active
    assert first.killed.is_set() and first.returncode is not None
    assert await asyncio.wait_for(following, 1) == []


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["spawn", "pip", "timeout"])
async def test_install_failure_releases_slot_for_next_request(
    tmp_path, monkeypatch, requirements_install_slot, failure,
):
    path = requirements_directory(tmp_path, "plugin")
    processes, calls = [], 0

    async def spawn(*args, **kwargs):
        nonlocal calls
        assert all(proc.returncode is not None for proc in processes)
        calls += 1
        if calls == 1 and failure == "spawn":
            raise OSError("pip unavailable")
        proc = RequirementsProcess(
            blocked=calls == 1 and failure == "timeout",
            returncode=1 if calls == 1 and failure == "pip" else 0,
        )
        processes.append(proc)
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(plugin_installer, "PLUGIN_REQUIREMENTS_TIMEOUT_SECONDS", 0.02)
    warnings, success = await asyncio.wait_for(asyncio.gather(
        plugin_installer.install_requirements(path), plugin_installer.install_requirements(path),
    ), 2)
    assert len(warnings) == 1 and success == []
    assert calls == 2 and all(proc.returncode is not None for proc in processes)
    assert not plugin_installer._requirements_install_lock.locked()


@pytest.mark.anyio
async def test_missing_requirements_skip_queue_and_queued_file_removal_is_respected(
    tmp_path, monkeypatch, requirements_install_slot,
):
    first_path = requirements_directory(tmp_path, "first")
    queued_path = requirements_directory(tmp_path, "queued")
    first = RequirementsProcess(blocked=True)
    started = asyncio.Event()
    calls = []

    async def spawn(*args, **kwargs):
        calls.append(args)
        started.set()
        return first

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    active = asyncio.create_task(plugin_installer.install_requirements(first_path))
    await asyncio.wait_for(started.wait(), 1)
    assert await asyncio.wait_for(plugin_installer.install_requirements(tmp_path / "empty"), 0.2) == []
    queued = asyncio.create_task(plugin_installer.install_requirements(queued_path))
    try:
        await asyncio.sleep(0)
        (queued_path / "requirements.txt").unlink()
    finally:
        first.release.set()
    assert await asyncio.wait_for(asyncio.gather(active, queued), 2) == [[], []]
    assert len(calls) == 1


@pytest.mark.anyio
async def test_pip_timeout_does_not_include_queue_or_process_creation_time(
    tmp_path, monkeypatch, requirements_install_slot,
):
    path = requirements_directory(tmp_path, "plugin")
    entered, release = asyncio.Event(), asyncio.Event()
    processes = []

    async def spawn(*args, **kwargs):
        if not processes:
            entered.set()
            await release.wait()
        proc = RequirementsProcess()
        processes.append(proc)
        return proc

    monkeypatch.setattr(plugin_installer.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(plugin_installer, "PLUGIN_REQUIREMENTS_TIMEOUT_SECONDS", 0.01)
    active = asyncio.create_task(plugin_installer.install_requirements(path))
    await asyncio.wait_for(entered.wait(), 1)
    following = asyncio.create_task(plugin_installer.install_requirements(path))
    try:
        await asyncio.sleep(0.05)
        assert not active.done() and not following.done()
    finally:
        release.set()
    assert await asyncio.wait_for(asyncio.gather(active, following), 2) == [[], []]
