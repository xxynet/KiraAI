import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import uvicorn
from fastapi import FastAPI

from core.logging_manager import LogCacheManager
from webui.routes.logs import LogsRoutes


@pytest.fixture
def log_stream(monkeypatch):
    cache = LogCacheManager()
    monkeypatch.setattr("webui.routes.logs.log_cache_manager", cache)
    app = FastAPI()
    server = uvicorn.Server(uvicorn.Config(app, log_config=None))
    routes = LogsRoutes(app, SimpleNamespace(uvicorn_server=server))
    return cache, server, routes


async def wait_for_subscribers(cache, count):
    async def wait():
        while len(cache.queues) != count:
            await asyncio.sleep(0)
    await asyncio.wait_for(wait(), timeout=2)


@pytest.mark.anyio
@pytest.mark.parametrize("clients", [1, 3])
async def test_uvicorn_shutdown_drains_idle_log_streams(log_stream, clients):
    cache, server, routes = log_stream
    server.servers = []
    server.lifespan = SimpleNamespace(shutdown=AsyncMock())
    responses = []
    tasks = []

    async def receive():
        await asyncio.Event().wait()

    for _ in range(clients):
        response = await routes.live_log()
        messages = []
        responses.append(messages)

        async def send(message, target=messages):
            target.append(message)

        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"}}
        task = asyncio.create_task(response(scope, receive, send))
        tasks.append(task)
        server.server_state.tasks.add(task)
        task.add_done_callback(server.server_state.tasks.discard)

    try:
        await wait_for_subscribers(cache, clients)
        server.should_exit = True
        await asyncio.wait_for(server.shutdown(), timeout=3)
        assert not cache.queues
        assert not server.server_state.tasks
        assert all(task.done() and not task.cancelled() for task in tasks)
        for messages in responses:
            assert messages[-1] == {"type": "http.response.body", "body": b"", "more_body": False}
        server.lifespan.shutdown.assert_awaited_once()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_log_stream_delivers_logs_and_releases_disconnected_subscriber(log_stream):
    cache, server, routes = log_stream
    response = await routes.live_log()
    stream = response.body_iterator
    pending = asyncio.create_task(anext(stream))
    try:
        await wait_for_subscribers(cache, 1)
        cache.emit("12:00:00", "INFO", "test", "hello", "blue")
        chunk = await asyncio.wait_for(pending, timeout=2)
        assert chunk.startswith("data: ") and chunk.endswith("\n\n")
        assert json.loads(chunk[6:])["message"] == "hello"
        assert not server.should_exit
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await stream.aclose()
    assert not cache.queues


@pytest.mark.anyio
async def test_log_stream_cancellation_releases_subscriber(log_stream):
    cache, _, routes = log_stream
    response = await routes.live_log()
    pending = asyncio.create_task(anext(response.body_iterator))
    await wait_for_subscribers(cache, 1)
    pending.cancel()
    await asyncio.gather(pending, return_exceptions=True)
    assert not cache.queues


@pytest.mark.anyio
async def test_log_stream_does_not_wait_for_logs_after_shutdown_started(log_stream):
    cache, server, routes = log_stream
    server.should_exit = True
    response = await routes.live_log()
    pending = asyncio.create_task(anext(response.body_iterator))
    try:
        done, _ = await asyncio.wait({pending}, timeout=2)
        assert pending in done
        with pytest.raises(StopAsyncIteration):
            pending.result()
        assert not cache.queues
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
