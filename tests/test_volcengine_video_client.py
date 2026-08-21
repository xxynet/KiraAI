"""Regression tests for the Volcengine video client.

Covers the configurable polling budget replacing the hardcoded 30s cap and
reference images / aspect ratio actually reaching the task request body.
"""

import json

import httpx
import pytest

from core.chat.message_elements import Image
from core.provider import ModelInfo, ModelType
from core.provider.src.volcengine import model_clients as volcengine_clients
from core.provider.src.volcengine.model_clients import (
    DEFAULT_VIDEO_TIMEOUT,
    VolcengineVideoClient,
)

TASK_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"


def build_client(model_config: dict | None = None) -> VolcengineVideoClient:
    return VolcengineVideoClient(
        ModelInfo(
            model_type=ModelType.VIDEO,
            model_id="doubao-seedance-1-0-pro",
            provider_id="volcengine-test",
            provider_name="Volcengine Test",
            provider_config={"api_key": "test-key"},
            model_config=model_config or {},
        )
    )


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_poll_budget_defaults_to_minutes_and_is_configurable():
    assert DEFAULT_VIDEO_TIMEOUT >= 60
    assert build_client()._poll_timeout() == float(DEFAULT_VIDEO_TIMEOUT)
    assert build_client({"timeout": 600})._poll_timeout() == 600.0


@pytest.mark.parametrize("invalid", ["not-a-number", 0, -5, None])
def test_poll_budget_falls_back_on_invalid_values(invalid):
    assert build_client({"timeout": invalid})._poll_timeout() == float(
        DEFAULT_VIDEO_TIMEOUT
    )


@pytest.mark.anyio
async def test_create_task_sends_text_only_without_reference_images():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "task-1"})

    async with mock_client(handler) as client:
        task_id = await build_client()._create_task(
            client=client, text="a cat", duration=5
        )

    assert task_id == "task-1"
    assert bodies[0]["content"] == [{"type": "text", "text": "a cat"}]
    assert bodies[0]["ratio"] == "16:9"


@pytest.mark.anyio
async def test_create_task_serialises_single_reference_image():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "task-1"})

    async with mock_client(handler) as client:
        await build_client({"ratio": "9:16"})._create_task(
            client=client,
            text="a cat",
            ref=[Image(image="https://example.com/first.png")],
            duration=5,
        )

    assert bodies[0]["content"] == [
        {"type": "text", "text": "a cat"},
        {
            "type": "image_url",
            "image_url": {"url": "https://example.com/first.png"},
        },
    ]
    assert bodies[0]["ratio"] == "9:16"


@pytest.mark.anyio
async def test_create_task_marks_multiple_reference_images():
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "task-1"})

    async with mock_client(handler) as client:
        await build_client()._create_task(
            client=client,
            text="a cat",
            ref=[
                Image(image="https://example.com/first.png"),
                Image(image="data:image/png;base64,aGVsbG8="),
            ],
            duration=5,
        )

    image_parts = bodies[0]["content"][1:]
    assert [part["image_url"]["url"] for part in image_parts] == [
        "https://example.com/first.png",
        "data:image/png;base64,aGVsbG8=",
    ]
    assert {part["role"] for part in image_parts} == {"reference_image"}


@pytest.mark.anyio
async def test_generate_video_uses_configured_budget_for_http_client(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TASK_URL:
            return httpx.Response(200, json={"id": "task-1"})
        return httpx.Response(
            200,
            json={
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example.com/video.mp4"},
            },
        )

    real_async_client = httpx.AsyncClient

    def fake_async_client(*args, **kwargs):
        captured["timeout"] = kwargs.get("timeout")
        return real_async_client(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(volcengine_clients.httpx, "AsyncClient", fake_async_client)

    video = await build_client({"timeout": 600}).generate_video("a cat")

    assert captured["timeout"] == 600.0
    assert video.file == "https://cdn.example.com/video.mp4"
