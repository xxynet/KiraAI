import pytest

from core.agent.agent_executor import AgentExecutor
from core.utils.media_refs import MEDIA_REF_TYPE


def _image_ref(path: str = "session_media/a/b.png") -> dict:
    return {"type": MEDIA_REF_TYPE, "path": path, "mime_type": "image/png", "detail": "high"}


def test_build_tool_messages_keeps_plain_results_unchanged():
    results = [
        {"role": "tool", "tool_call_id": "call-1", "name": "grep", "content": "no matches"},
        {"role": "tool", "tool_call_id": "call-2", "name": "read_file", "content": "hello"},
    ]

    messages = AgentExecutor._build_tool_messages(results)

    assert [m.role for m in messages] == ["tool", "tool"]
    assert messages[0].content == "no matches"
    assert messages[1].content == "hello"


def test_build_tool_messages_relocates_media_refs_into_user_message():
    ref = _image_ref()
    results = [
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": [
                {"type": "text", "text": "Image file: data/files/photo.png"},
                ref,
            ],
        },
    ]

    messages = AgentExecutor._build_tool_messages(results)

    assert [m.role for m in messages] == ["tool", "user"]
    tool_message, user_message = messages
    # The tool message collapses back to its plain-text output.
    assert tool_message.tool_call_id == "call-1"
    assert tool_message.content == "Image file: data/files/photo.png"
    # The media rides in a user message right after the tool results.
    assert user_message.content == [
        {"type": "text", "text": "Media returned by tool call(s): read_file"},
        ref,
    ]


def test_build_tool_messages_groups_media_from_multiple_tools_into_one_user_message():
    results = [
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": [{"type": "text", "text": "first"}, _image_ref("session_media/a/1.png")],
        },
        {"role": "tool", "tool_call_id": "call-2", "name": "grep", "content": "plain"},
        {
            "role": "tool",
            "tool_call_id": "call-3",
            "name": "read_file",
            "content": [{"type": "text", "text": "second"}, _image_ref("session_media/a/2.png")],
        },
    ]

    messages = AgentExecutor._build_tool_messages(results)

    assert [m.role for m in messages] == ["tool", "tool", "tool", "user"]
    assert messages[0].content == "first"
    assert messages[2].content == "second"
    user_message = messages[3]
    assert user_message.content[0] == {
        "type": "text",
        "text": "Media returned by tool call(s): read_file",
    }
    assert [part["path"] for part in user_message.content[1:]] == [
        "session_media/a/1.png",
        "session_media/a/2.png",
    ]


@pytest.mark.anyio
async def test_tool_media_user_message_is_resolved_for_the_provider(tmp_path, monkeypatch):
    from core.utils import media_refs

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    stored = tmp_path / "session_media" / "a" / "b.png"
    stored.parent.mkdir(parents=True, exist_ok=True)
    stored.write_bytes(b"\x89PNG\r\n\x1a\nfake-png-bytes")
    results = [
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "name": "read_file",
            "content": [
                {"type": "text", "text": "Image file: data/files/photo.png"},
                _image_ref(),
            ],
        },
    ]

    messages = AgentExecutor._build_tool_messages(results)
    request_messages = [m.to_dict() for m in messages]
    resolved = await media_refs.resolve_media_references(request_messages)

    tool_content = resolved[0]["content"]
    assert isinstance(tool_content, str)
    assert tool_content == "Image file: data/files/photo.png"
    user_parts = resolved[1]["content"]
    assert user_parts[0] == {"type": "text", "text": "Media returned by tool call(s): read_file"}
    assert user_parts[1]["type"] == "image_url"
    assert user_parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
