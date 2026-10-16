import asyncio
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, UploadFile

import webui.routes.plugins as plugin_routes
from webui.models import PluginInstallGithubRequest, PluginInstallResult, PluginUpdateQueueRequest, PluginUpdateRequest
from webui.routes.auth import require_auth
from webui.routes.plugins import PluginsRoutes


def result(plugin_id, **values):
    return PluginInstallResult(id=plugin_id, name=plugin_id, version="1.0", author="", description="", enabled=False, **values)


def github(name="new", **values):
    return PluginInstallGithubRequest(repo_url=f"https://github.com/example/{name}", **values)


def updates(*ids):
    return PluginUpdateQueueRequest(items=[{"plugin_id": plugin_id} for plugin_id in ids])


def upload(data=b"archive", name="plugin.zip"):
    return UploadFile(file=BytesIO(data), filename=name)


@pytest.fixture
def routes(tmp_path, monkeypatch):
    info = SimpleNamespace(builtin=False, repo="https://github.com/example/existing", display_name="Existing")
    manager = SimpleNamespace(plugin_dir=tmp_path, get_plugin_info=lambda _: info, get_plugin_module_path=lambda _: tmp_path / "existing")
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(plugin_manager=manager))
    routes.calls = []

    async def install(payload, manager, on_stage=None):
        routes.calls.append(("install", payload.repo_url))
        on_stage("installing_dependencies")
        return result(payload.repo_url.rsplit("/", 1)[-1])

    async def update(plugin_id, payload, manager, on_stage=None):
        routes.calls.append(("update", plugin_id))
        return result(plugin_id)

    async def install_upload(data, manager, on_stage=None):
        routes.calls.append(("upload", data))
        return result("uploaded")

    monkeypatch.setattr(routes, "_install_from_github_locked", install)
    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    monkeypatch.setattr(routes, "_install_from_upload_locked", install_upload)
    return routes


@pytest.mark.asyncio
@pytest.mark.parametrize("first", ["install", "update", "upload"])
async def test_mixed_tasks_share_fifo_and_only_one_executes(routes, monkeypatch, first):
    started, release = asyncio.Event(), asyncio.Event()
    execute = routes._execute_plugin_task
    active = 0

    async def blocked(task):
        nonlocal active
        active += 1
        assert active == 1
        assert routes._plugin_install_lock.locked()
        if not started.is_set():
            started.set()
            await release.wait()
        try:
            return await execute(task)
        finally:
            active -= 1

    monkeypatch.setattr(routes, "_execute_plugin_task", blocked)
    enqueue = {
        "install": lambda: routes.enqueue_github_install(github()),
        "update": lambda: routes.enqueue_task_updates(updates("existing")),
        "upload": lambda: routes.enqueue_upload_install(upload()),
    }
    order = [first, *(name for name in enqueue if name != first)]
    await enqueue[first]()
    worker = routes._plugin_task_worker
    try:
        await asyncio.wait_for(started.wait(), 2)
        for name in order[1:]:
            await enqueue[name]()
        tasks = await routes.list_plugin_tasks()
        assert [task.status for task in tasks] == ["running", "queued", "queued"]
        assert len(routes.calls) == 0
    finally:
        release.set()
        await asyncio.wait_for(worker, 2)
    assert [call[0] for call in routes.calls] == order
    assert all(task.status == "completed" for task in await routes.list_plugin_tasks())
    assert (await routes.list_plugin_tasks())[-1].plugin_id


@pytest.mark.asyncio
async def test_shared_capacity_deduplication_and_cancel_release_upload(routes, monkeypatch):
    monkeypatch.setattr(plugin_routes, "MAX_PENDING_PLUGIN_TASKS", 3)
    async with routes._plugin_install_lock:
        install = await routes.enqueue_github_install(github(commit_sha="a" * 40))
        duplicate = await routes.enqueue_github_install(github(commit_sha="b" * 40))
        assert duplicate.task_id == install.task_id
        assert duplicate.commit_sha == "a" * 40
        archive = await routes.enqueue_upload_install(upload())
        await routes.enqueue_task_updates(updates("existing"))
        with pytest.raises(HTTPException) as error:
            await routes.enqueue_github_install(github("other"))
        assert error.value.status_code == 409
        assert (await routes.cancel_plugin_task(archive.task_id)).status == "cancelled"
        assert "payload" not in routes._plugin_tasks[archive.task_id]
        await routes.enqueue_github_install(github("other"))
        remaining = await routes.clear_finished_plugin_tasks()
        assert len(remaining) == 3
        assert all(task.status == "queued" for task in remaining)
        worker = routes._plugin_task_worker
    await asyncio.wait_for(worker, 2)
    assert [call[0] for call in routes.calls] == ["install", "update", "install"]


@pytest.mark.asyncio
async def test_cancel_running_install_keeps_queue_alive_and_cleans_directory(tmp_path, monkeypatch):
    started = asyncio.Event()
    install_dir = tmp_path / "new"
    install_dir.mkdir()
    manager = SimpleNamespace(plugin_dir=tmp_path, has_plugin=lambda _: False)
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(plugin_manager=manager))

    async def download(*args, **kwargs):
        return install_dir

    async def dependencies(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    async def later(*args, **kwargs):
        return result("later")

    monkeypatch.setattr(plugin_routes, "install_from_github", download)
    monkeypatch.setattr(plugin_routes, "install_requirements", dependencies)
    task = await routes.enqueue_github_install(github())
    worker = routes._plugin_task_worker
    await asyncio.wait_for(started.wait(), 2)
    await routes.cancel_plugin_task(task.task_id)
    await routes.cancel_plugin_task(task.task_id)
    await routes.enqueue_upload_install(upload())
    monkeypatch.setattr(routes, "_install_from_upload_locked", later)
    await asyncio.wait_for(worker, 2)
    assert not install_dir.exists()
    assert [task.status for task in await routes.list_plugin_tasks()] == ["cancelled", "completed"]


@pytest.mark.asyncio
async def test_loading_install_cannot_be_cancelled(routes, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def load(*args, on_stage=None, **kwargs):
        on_stage("loading")
        started.set()
        await release.wait()
        return result("new")

    monkeypatch.setattr(routes, "_install_from_github_locked", load)
    task = await routes.enqueue_github_install(github())
    worker = routes._plugin_task_worker
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(HTTPException) as error:
            await routes.cancel_plugin_task(task.task_id)
        assert error.value.status_code == 409
    finally:
        release.set()
        await asyncio.wait_for(worker, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "initialization"])
async def test_install_failure_continues_queue_and_retry_keeps_commit(routes, monkeypatch, failure):
    install = routes._install_from_github_locked
    attempts = []

    async def fail_once(payload, manager, on_stage=None):
        attempts.append(payload)
        if len(attempts) == 1:
            if failure == "exception":
                raise HTTPException(422, "Download failed")
            return result("new", error="Initialization failed", status="error")
        return await install(payload, manager, on_stage)

    monkeypatch.setattr(routes, "_install_from_github_locked", fail_once)
    first = await routes.enqueue_github_install(github(commit_sha="a" * 40, gh_proxy="auto"))
    await routes.enqueue_upload_install(upload())
    await routes.enqueue_task_updates(updates("existing"))
    await asyncio.wait_for(routes._plugin_task_worker, 2)
    tasks = await routes.list_plugin_tasks()
    assert [task.status for task in tasks] == ["failed", "completed", "completed"]
    retried = await routes.retry_plugin_task(first.task_id)
    assert retried.task_id != first.task_id
    await asyncio.wait_for(routes._plugin_task_worker, 2)
    assert (await routes.list_plugin_tasks())[-1].status == "completed"
    assert attempts[1].commit_sha == "a" * 40
    assert attempts[1].gh_proxy == "auto"
    assert (await routes.list_update_tasks())[0].plugin_id == "existing"


@pytest.mark.asyncio
async def test_upload_byte_budget_and_retry_requires_file(routes, monkeypatch):
    monkeypatch.setattr(plugin_routes, "MAX_PLUGIN_ARCHIVE_BYTES", 4)
    async with routes._plugin_install_lock:
        first = await routes.enqueue_upload_install(upload(b"1234"))
        await routes.enqueue_upload_install(upload(b"5678"))
        with pytest.raises(HTTPException) as error:
            await routes.enqueue_upload_install(upload(b"9"))
        assert error.value.status_code == 409
        with pytest.raises(HTTPException) as error:
            await routes.enqueue_upload_install(upload(b"12345"))
        assert error.value.status_code == 413
        await routes.cancel_plugin_task(first.task_id)
        with pytest.raises(HTTPException) as error:
            await routes.retry_plugin_task(first.task_id)
        assert error.value.status_code == 409
        await routes.enqueue_upload_install(upload(b"9"))
        worker = routes._plugin_task_worker
    await asyncio.wait_for(worker, 2)
    assert all("payload" not in task for task in routes._plugin_tasks.values())


@pytest.mark.asyncio
async def test_unified_api_auth_restore_cancel_retry_and_private_fields(routes):
    routes.register()
    transport = httpx.ASGITransport(app=routes.app)
    async with routes._plugin_install_lock:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            requests = [
                ("GET", "/api/plugins/tasks", {}), ("DELETE", "/api/plugins/tasks", {}),
                ("POST", "/api/plugins/tasks/install/github", {"json": github().model_dump()}),
                ("POST", "/api/plugins/tasks/install/upload", {"files": {"file": ("p.zip", b"data")}}),
                ("POST", "/api/plugins/tasks/updates", {"json": updates("existing").model_dump()}),
                ("POST", "/api/plugins/tasks/missing/cancel", {}),
                ("POST", "/api/plugins/tasks/missing/retry", {}),
            ]
            for method, path, kwargs in requests:
                assert (await client.request(method, path, **kwargs)).status_code == 401
            routes.app.dependency_overrides[require_auth] = lambda: "test-user"
            installed = await client.post("/api/plugins/tasks/install/github", json=github(commit_sha="A" * 40).model_dump())
            assert installed.status_code == 200
            task = installed.json()
            assert task["operation"] == "install" and task["status"] == "queued"
            assert task["commit_sha"] == "a" * 40
            assert not {"payload", "done", "task", "result"}.intersection(task)
            updated = await client.post("/api/plugins/tasks/updates", json=updates("existing").model_dump())
            archive = await client.post("/api/plugins/tasks/install/upload", files={"file": ("p.zip", b"data")})
            assert archive.status_code == 200
            restored = (await client.get("/api/plugins/tasks")).json()
            assert [item["operation"] for item in restored] == ["install", "update", "install"]
            legacy = (await client.get("/api/plugins/updates/tasks")).json()
            assert len(legacy) == 1 and legacy[0]["task_id"] == updated.json()[0]["task_id"]
            assert (await client.post(f"/api/plugins/tasks/{task['task_id']}/cancel")).json()["status"] == "cancelled"
            retry = await client.post(f"/api/plugins/tasks/{task['task_id']}/retry")
            assert retry.status_code == 200 and retry.json()["task_id"] != task["task_id"]
            remaining = (await client.delete("/api/plugins/tasks")).json()
            assert len(remaining) == 3
            worker = routes._plugin_task_worker
    await asyncio.wait_for(worker, 2)
    assert [call[0] for call in routes.calls] == ["update", "upload", "install"]


@pytest.mark.asyncio
async def test_legacy_synchronous_endpoints_join_shared_queue(routes, monkeypatch):
    upload_queued = asyncio.Event()
    enqueue_upload = routes.enqueue_upload_install

    async def signal_upload(file):
        task = await enqueue_upload(file)
        upload_queued.set()
        return task

    monkeypatch.setattr(routes, "enqueue_upload_install", signal_upload)
    async with routes._plugin_install_lock:
        first = await routes.start_github_install_task(github("first"))
        assert first.status == "installing"
        legacy = asyncio.create_task(routes.install_from_github(github("second")))
        await asyncio.sleep(0)
        legacy_upload = asyncio.create_task(routes.install_from_upload(upload()))
        await asyncio.wait_for(upload_queued.wait(), 2)
        legacy_update = asyncio.create_task(routes.update_plugin("existing", PluginUpdateRequest()))
        await asyncio.sleep(0)
        assert len(await routes.list_plugin_tasks()) == 4
        worker = routes._plugin_task_worker
    installed, archived, updated = await asyncio.wait_for(asyncio.gather(legacy, legacy_upload, legacy_update), 2)
    await asyncio.wait_for(worker, 2)
    assert [installed.id, archived.id, updated.id] == ["second", "uploaded", "existing"]
    assert [call[0] for call in routes.calls] == ["install", "install", "upload", "update"]
    assert (await routes.get_install_task(first.task_id)).status == "completed"


@pytest.mark.asyncio
async def test_legacy_result_preserves_initialization_error_and_http_status(routes, monkeypatch):
    async def failed_load(*args, **kwargs):
        return result("new", status="error", error="Initialization failed")

    monkeypatch.setattr(routes, "_install_from_github_locked", failed_load)
    installed = await routes.install_from_github(github())
    assert installed.status == "error" and installed.error == "Initialization failed"
    assert (await routes.list_plugin_tasks())[0].status == "failed"

    async def failed_download(*args, **kwargs):
        raise HTTPException(422, "Download failed")

    monkeypatch.setattr(routes, "_install_from_github_locked", failed_download)
    with pytest.raises(HTTPException) as error:
        await routes.install_from_github(github("other"))
    assert error.value.status_code == 422
