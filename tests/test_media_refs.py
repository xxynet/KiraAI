import base64
from types import SimpleNamespace

import pytest

from core.chat.message_elements import Image
from core.message_manager import MessageProcessor
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

    manager = object.__new__(MessageProcessor)
    manager.kira_config = NativeConfig()

    result = await manager.message_format_to_text(
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

    manager = object.__new__(MessageProcessor)
    manager.kira_config = NativeConfig()
    persisted_messages = []

    async def record_persistence(message, _session):
        persisted_messages.append(message)
        return []

    manager._build_native_content = record_persistence
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
        is_stopped=False,
    )

    await manager.handle_im_batch_message(event)

    assert persisted_messages == []
