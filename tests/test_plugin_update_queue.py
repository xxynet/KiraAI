import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException

import webui.routes.plugins as plugin_routes
from webui.models import (
    PluginInstallResult,
    PluginUpdateQueueRequest,
    PluginUpdateRequest,
)
from webui.routes.auth import require_auth
from webui.routes.plugins import PluginsRoutes


def queue_request(*ids, commit_sha=None, gh_proxy=None):
    return PluginUpdateQueueRequest(items=[
        {"plugin_id": plugin_id, "commit_sha": commit_sha, "gh_proxy": gh_proxy}
        for plugin_id in ids
    ])


def install_result(plugin_id, **kwargs):
    return PluginInstallResult(
        id=plugin_id, name=plugin_id, version="2.0", author="", description="",
        enabled=False, warnings=[], **kwargs,
    )


@pytest.fixture
def routes(tmp_path, monkeypatch):
    infos = {
        plugin_id: SimpleNamespace(
            builtin=False, repo=f"https://github.com/example/{plugin_id}", display_name=plugin_id,
        )
        for plugin_id in ("a", "b", "c")
    }
    manager = SimpleNamespace(
        plugin_dir=tmp_path, get_plugin_info=infos.get,
        get_plugin_module_path=lambda plugin_id: tmp_path / plugin_id if plugin_id in infos else None,
    )
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(plugin_manager=manager))

    async def update(plugin_id, payload, manager, on_stage=None):
        return install_result(plugin_id)

    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    return routes


@pytest.mark.asyncio
async def test_fifo_deduplicates_queued_and_running_updates(routes, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def update(plugin_id, payload, manager, on_stage=None):
        assert routes._plugin_install_lock.locked()
        calls.append((plugin_id, payload.commit_sha, payload.gh_proxy))
        on_stage("installing_dependencies")
        if plugin_id == "a":
            started.set()
            await release.wait()
        return install_result(plugin_id)

    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    await routes._plugin_install_lock.acquire()
    first = await routes.enqueue_plugin_updates(queue_request("a", "b", "a", commit_sha="a" * 40, gh_proxy="auto"))
    duplicate = await routes.enqueue_plugin_updates(queue_request("b", commit_sha="b" * 40))
    worker = routes._plugin_task_worker
    assert len(first) == 2
    assert duplicate[0].task_id == first[1].task_id
    assert duplicate[0].commit_sha == "a" * 40
    assert all(task.status == "queued" for task in await routes.list_update_tasks())
    routes._plugin_install_lock.release()

    try:
        await asyncio.wait_for(started.wait(), 2)
        duplicate = await routes.enqueue_plugin_updates(queue_request("a", "c"))
        assert duplicate[0].task_id == first[0].task_id
        assert routes._plugin_tasks[first[0].task_id]["stage"] == "installing_dependencies"
        assert len(calls) == 1
    finally:
        release.set()
        await asyncio.wait_for(worker, 2)

    assert calls == [("a", "a" * 40, "auto"), ("b", "a" * 40, "auto"), ("c", None, None)]
    assert all(task.status == "completed" for task in await routes.list_update_tasks())


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http", "exception", "initialization"])
async def test_failure_does_not_stop_queue_and_failed_item_can_be_retried(routes, monkeypatch, failure):
    calls = []

    async def update(plugin_id, payload, manager, on_stage=None):
        calls.append(plugin_id)
        if plugin_id == "a" and calls.count("a") == 1:
            if failure == "http":
                raise HTTPException(status_code=422, detail="Download failed")
            if failure == "exception":
                raise RuntimeError("Reload failed")
            return install_result(plugin_id, error="Initialization failed", status="error")
        return install_result(plugin_id)

    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    first = await routes.enqueue_plugin_updates(queue_request("a", "b"))
    await asyncio.wait_for(routes._plugin_task_worker, 2)
    tasks = await routes.list_update_tasks()
    assert [task.status for task in tasks] == ["failed", "completed"]
    assert tasks[0].error
    retried = await routes.enqueue_plugin_updates(queue_request("a"))
    assert retried[0].task_id != first[0].task_id
    await asyncio.wait_for(routes._plugin_task_worker, 2)
    assert calls == ["a", "b", "a"]
    assert (await routes.list_update_tasks())[-1].status == "completed"


@pytest.mark.asyncio
async def test_cancel_only_waiting_items_and_continue_after_cancel(routes, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def update(plugin_id, payload, manager, on_stage=None):
        calls.append(plugin_id)
        if plugin_id == "a":
            started.set()
            await release.wait()
        return install_result(plugin_id)

    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    tasks = await routes.enqueue_plugin_updates(queue_request("a", "b", "c"))
    worker = routes._plugin_task_worker
    try:
        await asyncio.wait_for(started.wait(), 2)
        with pytest.raises(HTTPException) as error:
            await routes.cancel_update_task(tasks[0].task_id)
        assert error.value.status_code == 409
        cancelled = await routes.cancel_update_task(tasks[1].task_id)
        assert cancelled.status == "cancelled"
        assert (await routes.cancel_update_task(tasks[1].task_id)).status == "cancelled"
        with pytest.raises(HTTPException) as error:
            await routes.cancel_update_task("missing")
        assert error.value.status_code == 404
    finally:
        release.set()
        await asyncio.wait_for(worker, 2)
    assert calls == ["a", "c"]


@pytest.mark.asyncio
async def test_update_waits_for_installation_and_protects_runtime_mutations(routes):
    await routes._plugin_install_lock.acquire()
    tasks = await routes.enqueue_plugin_updates(queue_request("a"))
    worker = routes._plugin_task_worker
    try:
        await asyncio.sleep(0)
        assert (await routes.list_update_tasks())[0].status == "queued"
        mutations = [
            lambda: routes.reload_plugin("a"),
            lambda: routes.delete_plugin("a", False, False),
            lambda: routes.set_plugin_enabled("a", {"enabled": True}),
        ]
        for mutate in mutations:
            with pytest.raises(HTTPException) as error:
                await mutate()
            assert error.value.status_code == 409
    finally:
        routes._plugin_install_lock.release()
        await asyncio.wait_for(worker, 2)
    assert routes._plugin_tasks[tasks[0].task_id]["status"] == "completed"


@pytest.mark.asyncio
async def test_batch_validation_is_atomic_and_capacity_does_not_drop_work(routes, monkeypatch):
    with pytest.raises(HTTPException) as error:
        await routes.enqueue_plugin_updates(queue_request("a", "missing"))
    assert error.value.status_code == 404
    assert not routes._plugin_tasks
    assert routes._plugin_task_worker is None
    monkeypatch.setattr(plugin_routes, "MAX_PENDING_PLUGIN_TASKS", 1)
    await routes._plugin_install_lock.acquire()
    try:
        first = await routes.enqueue_plugin_updates(queue_request("a"))
        with pytest.raises(HTTPException) as error:
            await routes.enqueue_plugin_updates(queue_request("b"))
        assert error.value.status_code == 409
        assert (await routes.enqueue_plugin_updates(queue_request("a")))[0].task_id == first[0].task_id
    finally:
        routes._plugin_install_lock.release()
        await asyncio.wait_for(routes._plugin_task_worker, 2)


@pytest.mark.asyncio
async def test_history_is_bounded_without_evicting_pending_tasks(routes, monkeypatch):
    monkeypatch.setattr(plugin_routes, "MAX_RETAINED_PLUGIN_TASKS", 2)
    for index in range(5):
        routes._plugin_tasks[str(index)] = {"task_id": str(index), "status": "queued"}
    for index in range(4):
        routes._finish_plugin_task(routes._plugin_tasks[str(index)], status="completed", stage="completed")
    assert set(routes._plugin_tasks) == {"2", "3", "4"}
    assert routes._plugin_tasks["4"]["status"] == "queued"


@pytest.mark.asyncio
async def test_queue_api_returns_immediately_and_can_restore_tasks(routes):
    routes.register()
    routes.app.dependency_overrides[require_auth] = lambda: "test-user"
    await routes._plugin_install_lock.acquire()
    transport = httpx.ASGITransport(app=routes.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/plugins/updates/tasks", json={
                "items": [{"plugin_id": "a", "commit_sha": "A" * 40, "gh_proxy": "auto"}],
            })
            assert response.status_code == 200
            task = response.json()[0]
            assert task["status"] == "queued"
            assert task["commit_sha"] == "a" * 40
            assert "payload" not in task
            restored = await client.get("/api/plugins/updates/tasks")
            assert restored.json() == [task]
            invalid = await client.post("/api/plugins/updates/tasks", json={"items": []})
            assert invalid.status_code == 422
            cancelled = await client.post(f"/api/plugins/updates/tasks/{task['task_id']}/cancel")
            assert cancelled.json()["status"] == "cancelled"
    finally:
        routes._plugin_install_lock.release()
        await asyncio.wait_for(routes._plugin_task_worker, 2)


@pytest.mark.asyncio
async def test_real_update_reports_stages_and_keeps_requested_commit(tmp_path, monkeypatch):
    stages = []
    calls = []
    info = SimpleNamespace(builtin=False, repo="https://github.com/example/a", display_name="A")
    path = tmp_path / "legacy-a"

    async def download(repo, plugin_dir, **kwargs):
        calls.append(kwargs)
        return path

    async def requirements(plugin_dir, **kwargs):
        assert plugin_dir == path
        return ["Dependency warning"]

    async def prepare(plugin_id):
        stages.append("reload")

    async def load(plugin_dir):
        assert plugin_dir == path
        return "a"

    manager = SimpleNamespace(
        plugin_dir=tmp_path, get_plugin_info=lambda _: info,
        get_plugin_module_path=lambda _: path,
        prepare_plugin_reload=prepare, load_plugin_from_dir=load,
    )
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(plugin_manager=manager))
    monkeypatch.setattr(plugin_routes, "install_from_github", download)
    monkeypatch.setattr(plugin_routes, "install_requirements", requirements)
    monkeypatch.setattr(routes, "_build_install_result", lambda manager, plugin_id, warnings: SimpleNamespace(warnings=warnings))
    result = await routes._update_plugin_locked(
        "a", PluginUpdateRequest(commit_sha="a" * 40, gh_proxy="auto"), manager, on_stage=stages.append,
    )
    assert stages == ["installing_dependencies", "loading", "reload"]
    assert calls == [{"gh_proxy": "auto", "commit_sha": "a" * 40, "target_dir": path, "expected_plugin_id": "a"}]
    assert result.warnings == ["Dependency warning"]


@pytest.mark.asyncio
async def test_clear_finished_records_preserves_running_and_queued_updates(routes, monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def update(plugin_id, payload, manager, on_stage=None):
        calls.append(plugin_id)
        if plugin_id == "b":
            started.set()
            await release.wait()
        return install_result(plugin_id)

    monkeypatch.setattr(routes, "_update_plugin_locked", update)
    tasks = await routes.enqueue_plugin_updates(queue_request("a", "b", "c"))
    worker = routes._plugin_task_worker
    try:
        await asyncio.wait_for(started.wait(), 2)
        finished = routes._plugin_tasks[tasks[0].task_id]
        for status in ("failed", "cancelled"):
            record = {**finished, "task_id": status, "status": status, "stage": status}
            routes._plugin_tasks[status] = record
        remaining = await routes.clear_finished_update_tasks()
        assert [(task.plugin_id, task.status) for task in remaining] == [("b", "running"), ("c", "queued")]
        assert set(routes._plugin_tasks) == {tasks[1].task_id, tasks[2].task_id}
        assert routes._plugin_task_worker is worker
        assert [(task.plugin_id, task.status) for task in await routes.clear_finished_update_tasks()] == [
            ("b", "running"), ("c", "queued"),
        ]
    finally:
        release.set()
        await asyncio.wait_for(worker, 2)

    assert calls == ["a", "b", "c"]
    assert [(task.plugin_id, task.status) for task in await routes.list_update_tasks()] == [
        ("b", "completed"), ("c", "completed"),
    ]
    assert await routes.clear_finished_update_tasks() == []
    assert await routes.clear_finished_update_tasks() == []


@pytest.mark.asyncio
async def test_clear_history_api_requires_auth_and_stays_cleared_after_refresh(routes):
    routes.register()
    created = await routes.enqueue_plugin_updates(queue_request("a"))
    await asyncio.wait_for(routes._plugin_task_worker, 2)
    transport = httpx.ASGITransport(app=routes.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unauthorized = await client.delete("/api/plugins/updates/tasks")
        assert unauthorized.status_code == 401
        assert created[0].task_id in routes._plugin_tasks
        routes.app.dependency_overrides[require_auth] = lambda: "test-user"
        cleared = await client.delete("/api/plugins/updates/tasks")
        assert cleared.status_code == 200
        assert cleared.json() == []
        assert (await client.get("/api/plugins/updates/tasks")).json() == []
        assert (await client.delete("/api/plugins/updates/tasks")).json() == []
        new_tasks = await routes.enqueue_plugin_updates(queue_request("a"))
        await asyncio.wait_for(routes._plugin_task_worker, 2)
        restored = (await client.get("/api/plugins/updates/tasks")).json()
        assert len(restored) == 1
        assert restored[0]["task_id"] == new_tasks[0].task_id
        assert restored[0]["task_id"] != created[0].task_id
