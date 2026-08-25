import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from webui.routes.system import SystemRoutes


@pytest.mark.anyio
async def test_shutdown_stops_the_lifecycle_and_schedules_normal_exit(monkeypatch):
    scheduled = []

    class Loop:
        def call_later(self, delay, callback, *args):
            scheduled.append((delay, callback, args))

    class Lifecycle:
        def __init__(self):
            self.stopped = False
            self.uvicorn_server = SimpleNamespace(should_exit=False)

        async def stop(self):
            self.stopped = True

    lifecycle = Lifecycle()
    monkeypatch.setattr(asyncio, "get_running_loop", lambda: Loop())
    routes = SystemRoutes(FastAPI(), lifecycle)

    response = await routes.shutdown()

    assert response == {"status": "shutting_down"}
    assert lifecycle.stopped is True
    assert lifecycle.uvicorn_server.should_exit is True
    assert scheduled == [(0.5, __import__("os")._exit, (0,))]
