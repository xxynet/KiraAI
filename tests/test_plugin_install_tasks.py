import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

import webui.routes.plugins as plugin_routes
from webui.models import PluginInstallGithubRequest
from webui.routes.plugins import PluginsRoutes


@pytest.mark.asyncio
async def test_background_plugin_install_task_can_be_cancelled(tmp_path, monkeypatch):
    started = asyncio.Event()

    async def blocked_install(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(plugin_routes, "install_from_github", blocked_install)
    plugin_manager = SimpleNamespace(plugin_dir=Path(tmp_path), has_plugin=lambda _: False)
    routes = PluginsRoutes(FastAPI(), SimpleNamespace(plugin_manager=plugin_manager))

    created = await routes.start_github_install_task(
        PluginInstallGithubRequest(repo_url="https://github.com/example/plugin")
    )
    await started.wait()

    await routes.cancel_install_task(created.task_id)
    await asyncio.wait_for(routes._plugin_task_worker, 2)

    result = await routes.get_install_task(created.task_id)
    assert result.status == "cancelled"
    assert result.stage == "cancelled"


@pytest.mark.asyncio
async def test_plugin_install_guard_rejects_concurrent_operations():
    routes = PluginsRoutes(FastAPI(), SimpleNamespace())

    async with routes._plugin_install_lock:
        with pytest.raises(HTTPException, match="already in progress"):
            routes._ensure_plugin_install_available()


def test_plugin_install_task_history_is_bounded():
    routes = PluginsRoutes(FastAPI(), SimpleNamespace())
    for index in range(plugin_routes.MAX_RETAINED_PLUGIN_TASKS):
        routes._plugin_tasks[str(index)] = {
            "task_id": str(index),
            "status": "completed",
            "completed_at": index,
        }

    newest_task = {"task_id": "newest", "status": "queued"}
    routes._plugin_tasks["newest"] = newest_task
    routes._finish_plugin_task(newest_task, status="completed", stage="completed")

    assert len(routes._plugin_tasks) == plugin_routes.MAX_RETAINED_PLUGIN_TASKS
    assert "0" not in routes._plugin_tasks
    assert "newest" in routes._plugin_tasks
