import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

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
    await asyncio.gather(routes._install_tasks[created.task_id]["task"], return_exceptions=True)

    result = await routes.get_install_task(created.task_id)
    assert result.status == "cancelled"
    assert result.stage == "cancelled"
