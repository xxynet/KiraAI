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


@pytest.mark.parametrize("result_path", ["final", "stopped", "tools"])
@pytest.mark.parametrize("use_fallback", [False, True])
@pytest.mark.anyio
async def test_agent_step_carries_identity_and_upstream_name(monkeypatch, use_fallback, result_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from core.agent.agent_executor import AgentExecutionContext, event_handler_reg, EventType
    from core.provider import LLMModelClient, LLMRequest, LLMResponse, ModelInfo, ModelType, ProviderAPIError

    async def stop_event(event, response):
        event.is_stopped = True

    def handlers(event_type):
        if result_path == "stopped" and event_type == EventType.ON_LLM_RESPONSE:
            return [SimpleNamespace(exec_handler=stop_event)]
        return []

    monkeypatch.setattr(event_handler_reg, "get_handlers", handlers)
    models = []
    for name in ("primary-upstream", "fallback-upstream"):
        model = LLMModelClient(ModelInfo(
            model_type=ModelType.LLM, model_id=f"internal-{name}", model_name=name,
            provider_id="provider", provider_name="Test Provider",
        ))
        response = LLMResponse("")
        if result_path == "tools":
            response.tool_calls = [{"id": "call-1", "type": "function",
                                    "function": {"name": "test", "arguments": "{}"}}]
        model.chat = AsyncMock(return_value=response)
        models.append(model)
    if use_fallback:
        models[0].chat.side_effect = ProviderAPIError("Simulated provider failure")

    async def execute_tool(event, response, **kwargs):
        response.tool_results = [{"role": "tool", "tool_call_id": "call-1", "name": "test", "content": ""}]

    context = AgentExecutionContext(
        event=SimpleNamespace(sid="test-session", is_stopped=False),
        request=LLMRequest(messages=[]), new_messages=[], model_group=models,
    )
    executor = AgentExecutor(SimpleNamespace(execute_tool=execute_tool))
    steps = [step async for step in executor.run(context, max_steps=1)]
    assert len(steps) == 1
    assert steps[0].state == ("stopped" if result_path == "stopped" else "success")
    expected_name = "fallback-upstream" if use_fallback else "primary-upstream"
    assert steps[0].model_id == f"internal-{expected_name}"
    assert steps[0].model_name == expected_name
    assert "final model call" in context.request.messages[0].content
    if result_path == "stopped":
        assert context.new_messages == []
        assert steps[0].assistant_message is None
    else:
        assert [message.role for message in context.new_messages] == (
            ["assistant", "tool"] if result_path == "tools" else ["assistant"]
        )
        assert len(context.request.messages) == len(context.new_messages) + 1
        assert all(request_message is memory_message for request_message, memory_message
                   in zip(context.request.messages[1:], context.new_messages))
        assert steps[0].assistant_message is context.new_messages[0]


@pytest.mark.anyio
async def test_failed_agent_step_reports_last_attempted_model_identity(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from core.agent.agent_executor import AgentExecutionContext, event_handler_reg
    from core.provider import LLMModelClient, LLMRequest, ModelInfo, ModelType, ProviderAPIError

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *args, **kwargs: [])
    models = []
    for name in ("primary-upstream", "fallback-upstream"):
        model = LLMModelClient(ModelInfo(
            model_type=ModelType.LLM, model_id=f"internal-{name}", model_name=name,
            provider_id="provider", provider_name="Test Provider",
        ))
        model.chat = AsyncMock(side_effect=ProviderAPIError("Simulated provider failure"))
        models.append(model)
    context = AgentExecutionContext(
        event=SimpleNamespace(sid="test-session", is_stopped=False),
        request=LLMRequest(messages=[]), new_messages=[], model_group=models,
    )
    steps = [step async for step in AgentExecutor(None).run(context, max_steps=1)]
    assert len(steps) == 1
    assert steps[0].state == "error"
    assert steps[0].model_id == "internal-fallback-upstream"
    assert steps[0].model_name == "fallback-upstream"
