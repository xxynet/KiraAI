from unittest.mock import AsyncMock
import base64
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from core.chat.message_elements import Image
from core.workflow.src.im.message_formatter import MessageFormatter
from core.workflow.src.im.workflow import DefaultIMWorkflow
from tests.im_workflow_helpers import make_workflow_context
from core.utils import media_refs


@pytest.mark.asyncio
async def test_session_media_reference_is_resolved_only_for_provider_request(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    source_data = b"test image bytes"
    image = Image(
        "data:image/png;base64," + base64.b64encode(source_data).decode("ascii")
    )

    reference = await media_refs.store_session_media(
        image, "adapter:dm:user", "message-1"
    )

    assert reference["type"] == media_refs.MEDIA_REF_TYPE
    assert reference["mime_type"] == "image/png"
    assert "base64" not in reference
    assert (tmp_path / reference["path"]).read_bytes() == source_data

    resolved = await media_refs.resolve_media_references(
        [
            {
                "role": "user",
                "content": [{"type": "text", "text": "inspect"}, reference],
            }
        ]
    )

    assert resolved[0]["content"][0] == {"type": "text", "text": "inspect"}
    assert resolved[0]["content"][1] == {
        "type": "image_url",
        "image_url": {
            "url": (
                "data:image/png;base64,"
                + base64.b64encode(source_data).decode("ascii")
            ),
            "detail": "high",
        },
    }


@pytest.mark.asyncio
async def test_store_session_media_sniffs_mime_from_raw_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    source = tmp_path / "extensionless_image"
    source.write_bytes(png_bytes)
    image = Image(str(source))
    assert image.mime is None

    reference = await media_refs.store_session_media(
        image, "adapter:dm:user", "message-1"
    )

    assert reference["mime_type"] == "image/png"
    assert reference["path"].endswith(".png")
    assert (tmp_path / reference["path"]).read_bytes() == png_bytes


@pytest.mark.asyncio
async def test_cleanup_session_media_removes_unreferenced_files(tmp_path, monkeypatch):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    image = Image("data:image/png;base64,aGVsbG8=")
    reference = await media_refs.store_session_media(
        image, "adapter:dm:user", "message-1"
    )

    media_refs.cleanup_session_media("adapter:dm:user", [])

    assert not (tmp_path / reference["path"]).exists()


@pytest.mark.asyncio
async def test_session_media_store_leaves_no_temporary_file(tmp_path, monkeypatch):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    image = Image("data:image/png;base64,aGVsbG8=")

    reference = await media_refs.store_session_media(
        image, "adapter:dm:user", "message-1"
    )

    assert (tmp_path / reference["path"]).read_bytes() == b"hello"
    assert not list((tmp_path / media_refs.MEDIA_ROOT_NAME).rglob("*.tmp"))


@pytest.mark.asyncio
async def test_native_mode_does_not_call_vlm_for_incoming_images():
    class NativeConfig:
        @staticmethod
        def get_config(key, default=None):
            if key == "bot_config.capabilities.image_recognition.mode":
                return "native"
            return default

    formatter = MessageFormatter(NativeConfig())

    result = await formatter.format_to_text(
        [Image("data:image/png;base64,aGVsbG8=")]
    )

    assert result == "[Image attached]"


@pytest.mark.asyncio
async def test_stopped_batch_does_not_persist_native_media(monkeypatch):
    class NativeConfig:
        @staticmethod
        def get_config(key, default=None):
            if key == "bot_config.capabilities.image_recognition.mode":
                return "native"
            if key == "bot_config.image_compression":
                return {"enabled": False}
            return default

    class StopHandler:
        async def exec_handler(self, event):
            event.is_stopped = True

    services = make_workflow_context(
        config=NativeConfig(),
        session_manager=SimpleNamespace(
            get_effective_capabilities=AsyncMock(side_effect=lambda sid, capabilities: capabilities),
        ),
    )
    workflow = DefaultIMWorkflow(services)
    persisted_messages = []

    async def record_persistence(message, _session):
        persisted_messages.append(message)
        return []

    services.message_media.build_native_content = record_persistence
    monkeypatch.setattr(
        "core.message_manager.event_handler_reg.get_handlers",
        lambda *_args, **_kwargs: [StopHandler()],
    )
    event = SimpleNamespace(
        session=SimpleNamespace(sid="adapter:dm:user"),
        messages=[
            SimpleNamespace(
                chain=[Image("data:image/png;base64,aGVsbG8=")],
                message_str=None,
            )
        ],
        event_id="event-1",
        adapter=SimpleNamespace(platform="test"),
        is_stopped=False,
    )

    await workflow.handle_batch_event(event)

    assert persisted_messages == []


def test_reference_collection_accepts_iterables_and_malformed_shapes():
    reference = {"type": "kira_image_ref", "path": "session_media/archive/retained"}
    memory = [[{"role": "user", "content": [reference]}]]
    expected = {reference["path"]}
    assert media_refs.collect_media_reference_paths(iter(memory)) == expected
    assert media_refs.collect_media_reference_paths({"memory": [None, reference]}) == expected
    for invalid in (None, 42, "invalid", b"invalid", {"memory": None}):
        assert media_refs.collect_media_reference_paths(invalid) == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["session_media/missing.png", "../outside.png", "", None])
async def test_invalid_image_reference_preserves_text_and_valid_images(tmp_path, monkeypatch, path):
    from copy import deepcopy

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    log = Mock()
    monkeypatch.setattr(media_refs, "logger", log)
    valid = await media_refs.store_session_media(
        Image("data:image/png;base64,aGVsbG8="), "adapter:dm:user", "valid",
    )
    invalid = {"type": media_refs.MEDIA_REF_TYPE, "path": path}
    messages = [
        {"role": "user", "content": [invalid]},
        {"role": "user", "content": [
            {"type": "text", "text": "Please reply"}, valid,
        ]},
    ]
    original = deepcopy(messages)

    resolved = await media_refs.resolve_media_references(messages)

    assert resolved[0]["content"] == [{"type": "text", "text": "[image unavailable]"}]
    assert resolved[1]["content"][0]["text"] == "Please reply"
    assert resolved[1]["content"][1]["image_url"]["url"] == "data:image/png;base64,aGVsbG8="
    assert messages == original
    log.warning.assert_called_once()
    diagnostic = log.warning.call_args.args
    assert diagnostic[1] == path
    assert diagnostic[2] == "ValueError"
    assert diagnostic[3]


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    FileNotFoundError("removed during read"), PermissionError("unreadable"),
])
async def test_image_read_failure_degrades_only_failed_part(tmp_path, monkeypatch, error):
    from pathlib import Path

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    reference = await media_refs.store_session_media(
        Image("data:image/png;base64,aGVsbG8="), "adapter:dm:user", "read-error",
    )

    def fail_read(_path):
        raise error

    monkeypatch.setattr(Path, "read_bytes", fail_read)
    resolved = await media_refs.resolve_media_references([
        {"role": "user", "content": [
            reference, {"type": "text", "text": "current text"},
        ]},
    ])
    assert resolved[0]["content"] == [
        {"type": "text", "text": "[image unavailable]"},
        {"type": "text", "text": "current text"},
    ]


@pytest.mark.asyncio
async def test_image_resolution_does_not_swallow_cancellation(monkeypatch):
    import asyncio

    monkeypatch.setattr(media_refs, "resolve_media_reference", AsyncMock(
        side_effect=asyncio.CancelledError,
    ))
    with pytest.raises(asyncio.CancelledError):
        await media_refs.resolve_media_references([
            {"role": "user", "content": [{"type": media_refs.MEDIA_REF_TYPE}]},
        ])


@pytest.mark.asyncio
async def test_cleanup_preserves_retained_pending_and_other_session_files(tmp_path, monkeypatch):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    image = Image("data:image/png;base64,aGVsbG8=")
    sid = "adapter:dm:user"
    removed = await media_refs.store_session_media(image, sid, "removed")
    retained = await media_refs.store_session_media(image, sid, "retained")
    other = await media_refs.store_session_media(image, "adapter:dm:other", "other")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"keep")

    async with media_refs.session_media_scope():
        pending = await media_refs.store_session_media(image, sid, "pending")
        media_refs.cleanup_session_media(sid, [retained])

        assert not (tmp_path / removed["path"]).exists()
        for reference in (retained, pending, other):
            assert (tmp_path / reference["path"]).read_bytes() == b"hello"
        assert outside.read_bytes() == b"keep"

    media_refs.cleanup_session_media(sid, [retained])
    assert not (tmp_path / pending["path"]).exists()
    assert (tmp_path / retained["path"]).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["openai", "deepseek", "anthropic"])
@pytest.mark.parametrize("streaming", [False, True])
async def test_provider_replies_with_missing_historical_image(
    tmp_path, monkeypatch, provider, streaming,
):
    from copy import deepcopy
    from unittest.mock import MagicMock

    from core.provider import LLMRequest, ModelInfo, ModelType
    from core.provider.openai_compatible import OpenAICompatibleLLMClient
    from core.provider.src.deepseek.model_clients import DeepSeekLLMClient
    from core.provider.src.anthropic.model_clients import AnthropicCompatibleLLMClient

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    log = Mock()
    monkeypatch.setattr(media_refs, "logger", log)
    client_type = {
        "openai": OpenAICompatibleLLMClient,
        "deepseek": DeepSeekLLMClient,
        "anthropic": AnthropicCompatibleLLMClient,
    }[provider]
    client = client_type(ModelInfo(
        model_type=ModelType.LLM, model_id="test", model_name="test",
        provider_id="test", provider_name=provider,
        provider_config={}, model_config={},
    ))
    request = LLMRequest(messages=[
        {"role": "user", "content": [
            {"type": media_refs.MEDIA_REF_TYPE, "path": "session_media/missing.png"},
        ]},
        {"role": "assistant", "content": "previous reply"},
        {"role": "user", "content": "current text"},
    ])
    original = deepcopy(request.messages)
    if provider == "anthropic":
        response = SimpleNamespace(to_dict=lambda: {
            "content": [{"type": "text", "text": "reply"}],
        })
        event = SimpleNamespace(to_dict=lambda: {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "text_delta", "text": "reply"},
        })
    else:
        response = SimpleNamespace(choices=[
            SimpleNamespace(message=SimpleNamespace(content="reply", tool_calls=None)),
        ], usage=None)
        event = SimpleNamespace(choices=[SimpleNamespace(
            delta=SimpleNamespace(content="reply", tool_calls=None),
            finish_reason="stop",
        )])

    async def events():
        yield event

    create = AsyncMock(return_value=events() if streaming else response)
    sdk = MagicMock()
    sdk.chat.completions.create = create
    sdk.messages.create = create
    sdk.__aenter__ = AsyncMock(return_value=sdk)
    sdk.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(client, "_build_client", lambda: sdk)

    if streaming:
        assert "".join([chunk.delta_text async for chunk in client.chat_stream(request)]) == "reply"
    else:
        assert (await client.chat(request)).text_response == "reply"

    payload = create.await_args.kwargs
    assert payload["messages"][0]["content"] == [{"type": "text", "text": "[image unavailable]"}]
    latest = payload["messages"][-1]["content"]
    assert latest == ([{"type": "text", "text": "current text"}] if provider == "anthropic" else "current text")
    assert "session_id" not in payload
    assert request.messages == original
    assert log.warning.call_args.args[1] == "session_media/missing.png"


@pytest.mark.asyncio
async def test_overlapping_turns_keep_shared_media_pinned_until_both_finish(tmp_path, monkeypatch):
    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    sid = "adapter:dm:user"
    image = Image("data:image/png;base64,aGVsbG8=")
    async with media_refs.session_media_scope():
        first = await media_refs.store_session_media(image, sid, "same-message")
        async with media_refs.session_media_scope():
            second = await media_refs.store_session_media(image, sid, "same-message")
            assert first == second
            media_refs.cleanup_session_media(sid, [])
            assert (tmp_path / first["path"]).exists()
        media_refs.cleanup_session_media(sid, [])
        assert (tmp_path / first["path"]).exists()
    media_refs.cleanup_session_media(sid, [])
    assert not (tmp_path / first["path"]).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("cancelled", [False, True])
async def test_scan_serializes_with_media_publication_and_cancelled_workers_finish(
    tmp_path, monkeypatch, cancelled,
):
    import asyncio
    import threading

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    sid = "adapter:dm:user"
    publishing = threading.Event()
    continue_write = threading.Event()
    scanning = threading.Event()
    stored = asyncio.Event()
    finish_turn = asyncio.Event()
    reference = None
    original_link = media_refs.os.link

    def delayed_link(source, target):
        publishing.set()
        if not continue_write.wait(timeout=5):
            raise TimeoutError("test did not release publication")
        original_link(source, target)

    monkeypatch.setattr(media_refs.os, "link", delayed_link)

    async def turn():
        nonlocal reference
        async with media_refs.session_media_scope():
            reference = await media_refs.store_session_media(
                Image("data:image/png;base64,aGVsbG8="), sid, "racing",
            )
            stored.set()
            await finish_turn.wait()

    def scan():
        scanning.set()
        media_refs.cleanup_session_media(sid, [])

    turn_task = asyncio.create_task(turn())
    scan_task = None
    try:
        assert await asyncio.to_thread(publishing.wait, 3)
        scan_task = asyncio.create_task(asyncio.to_thread(scan))
        assert await asyncio.to_thread(scanning.wait, 3)
        assert not scan_task.done()
        if cancelled:
            turn_task.cancel()
            await asyncio.sleep(0)
            assert not turn_task.done()
        continue_write.set()
        if cancelled:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(turn_task, timeout=3)
        else:
            await asyncio.wait_for(stored.wait(), timeout=3)
        await asyncio.wait_for(scan_task, timeout=3)
        if not cancelled:
            assert (tmp_path / reference["path"]).read_bytes() == b"hello"
            finish_turn.set()
            await asyncio.wait_for(turn_task, timeout=3)
    finally:
        continue_write.set()
        finish_turn.set()
        await asyncio.gather(turn_task, *([scan_task] if scan_task else []), return_exceptions=True)

    media_refs.cleanup_session_media(sid, [])
    assert not list((tmp_path / media_refs.MEDIA_ROOT_NAME).rglob("*.*"))
