import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.agent.tool import ToolSet
from core.chat.message_elements import Text
from core.chat.message_utils import (
    KiraIMMessage, KiraIMSentResult, KiraMessageBatchEvent, MessageChain,
)
from core.chat.session import Session, User
from core.message_manager import MessageProcessor
from core.plugin.handlers import EventType, event_handler_reg
from core.prompt_manager import Prompt
from core.provider import LLMResponse


def batch(user="user"):
    return KiraMessageBatchEvent(
        supported_elements=["text"], timestamp=1,
        adapter=AdapterInfo(True, "test", "adapter", "test"),
        session=Session("adapter", "dm", user),
        messages=[KiraIMMessage(
            message_id=user, self_id="bot", timestamp=1,
            chain=MessageChain([Text(user)]), sender=User(user),
        )],
    )


@pytest.fixture
def processor(monkeypatch):
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda *a, **kw: [])
    instance = object.__new__(MessageProcessor)
    instance.event_bus = None
    instance.kira_config = SimpleNamespace(
        get_config=lambda key, default=None: (
            {"bot_config.agent.max_tool_loop": 2, "bot_config.bot.min_message_delay": 0, "bot_config.bot.max_message_delay": 0}.get(key, default)
        )
    )
    instance.session_manager = SimpleNamespace(
        get_effective_capabilities=lambda sid, default: default,
        get_session_info=lambda sid: SimpleNamespace(session_title="Chat"),
        fetch_memory=lambda sid: [],
        update_memory=Mock(),
    )
    instance.prompt_manager = SimpleNamespace(get_agent_prompt=AsyncMock(return_value=[]))
    instance.skills_manager = SimpleNamespace(skills_info=[])
    instance.mcp_manager = SimpleNamespace(get_tool_server_map=lambda: {})
    instance.tool_manager = SimpleNamespace(build_tool_set=ToolSet)
    instance.db = SimpleNamespace(add_telemetry_llm_usage=AsyncMock())
    instance.message_history = SimpleNamespace(
        record_incoming_safely=AsyncMock(side_effect=lambda msg, *_: msg.message_id),
        link_incoming_messages=AsyncMock(),
    )
    instance.session_locks = {}
    instance.message_delivery.parse_xml = AsyncMock(return_value=[MessageChain([Text("reply")])])
    instance.message_delivery.send_message_chain = AsyncMock(return_value=KiraIMSentResult("sent-id"))
    instance.message_media.build_native_content = AsyncMock(return_value=[])
    model = SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_id="test", model_name="test"),
        chat=AsyncMock(side_effect=lambda request: LLMResponse("<msg><text>reply</text></msg>")),
    )
    instance.provider_mgr = SimpleNamespace(get_default_llm=lambda: model)
    return instance, model


@pytest.mark.anyio
@pytest.mark.parametrize("stop_at", [
    None, EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST,
    EventType.AFTER_XML_PARSE, EventType.ON_STEP_RESULT, EventType.ON_FINAL_RESULT,
])
async def test_plugin_stop_preserves_stage_boundaries_and_finalization(processor, monkeypatch, stop_at):
    instance, model = processor
    observed = []
    final_results = []

    def handlers(event_type):
        async def handle(event, *args):
            observed.append(event_type)
            if event_type == EventType.ON_FINAL_RESULT:
                final_results.append(args[0])
            if event_type == stop_at:
                event.stop()
        return [SimpleNamespace(exec_handler=handle)]

    monkeypatch.setattr(event_handler_reg, "get_handlers", handlers)
    await instance.handle_im_batch_message(batch())

    order = [
        EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST,
        EventType.ON_LLM_RESPONSE, EventType.AFTER_XML_PARSE,
        EventType.ON_MESSAGE_SENT, EventType.ON_STEP_RESULT, EventType.ON_FINAL_RESULT,
    ]
    if stop_at in (EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST):
        assert observed == order[:order.index(stop_at) + 1]
        model.chat.assert_not_awaited()
        instance.session_manager.update_memory.assert_not_called()
        instance.message_history.link_incoming_messages.assert_not_awaited()
    else:
        expected = order
        if stop_at == EventType.AFTER_XML_PARSE:
            expected = order[:4] + [EventType.ON_FINAL_RESULT]
            instance.message_delivery.send_message_chain.assert_not_awaited()
        else:
            instance.message_delivery.send_message_chain.assert_awaited_once()
        assert observed == expected
        assert len(final_results) == 1
        assert len(final_results[0].step_results) == (0 if stop_at == EventType.AFTER_XML_PARSE else 1)
        instance.session_manager.update_memory.assert_called_once()
        memory = instance.session_manager.update_memory.call_args.args[1]
        assert [message.role for message in memory] == ["user", "assistant"]
        instance.message_history.link_incoming_messages.assert_awaited_once()


@pytest.mark.anyio
async def test_request_stop_does_not_persist_native_media(processor, monkeypatch):
    instance, model = processor
    instance.session_manager.get_effective_capabilities = lambda *_: {
        "image_recognition": {"mode": "native"}
    }

    async def stop(event, *_):
        event.stop()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=stop)] if event_type == EventType.ON_LLM_REQUEST else []
    ))
    await instance.handle_im_batch_message(batch())

    instance.message_media.build_native_content.assert_not_awaited()
    model.chat.assert_not_awaited()
    instance.session_manager.update_memory.assert_not_called()


@pytest.mark.anyio
async def test_missing_model_stops_before_request_hooks_and_memory(processor, monkeypatch):
    instance, _ = processor
    instance.provider_mgr.get_default_llm = lambda: None
    request_hook = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=request_hook)] if event_type == EventType.ON_LLM_REQUEST else []
    ))

    await instance.handle_im_batch_message(batch())

    request_hook.assert_not_awaited()
    instance.session_manager.update_memory.assert_not_called()


@pytest.mark.anyio
async def test_request_only_prompts_and_step_edits_keep_memory_contract(processor, monkeypatch):
    instance, model = processor

    async def customize_request(event, request, tags):
        request.user_prompt.append(Prompt("temporary", persist=False, render_template=False))
        request.user_prompt.append(Prompt("remember", render_template=False))

    async def customize_result(event, result):
        result.raw_output = "edited reply"

    callbacks = {
        EventType.ON_LLM_REQUEST: customize_request,
        EventType.ON_STEP_RESULT: customize_result,
    }
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=callbacks[event_type])] if event_type in callbacks else []
    ))
    await instance.handle_im_batch_message(batch())

    memory = instance.session_manager.update_memory.call_args.args[1]
    assert memory[0].content == "user\nremember\n"
    assert memory[1].content == "edited reply"
    request = model.chat.await_args.args[0]
    assert "temporary" in request.messages[0].content
    assert request.messages[-1].content == "edited reply"


@pytest.mark.anyio
async def test_concurrent_batches_keep_requests_links_and_results_separate(processor, monkeypatch):
    instance, model = processor
    ready = asyncio.Event()
    requests = []
    results = {}

    async def chat(request):
        requests.append(request)
        if len(requests) == 2:
            ready.set()
        await asyncio.wait_for(ready.wait(), timeout=2)
        user = request.messages[-1].content.strip()
        return LLMResponse(f"<msg><text>{user}</text></msg>")

    async def final(event, result):
        results[event.sid] = result

    model.chat.side_effect = chat
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=final)] if event_type == EventType.ON_FINAL_RESULT else []
    ))
    await asyncio.gather(
        instance.handle_im_batch_message(batch("alice")),
        instance.handle_im_batch_message(batch("bob")),
    )

    saved = dict(call.args for call in instance.session_manager.update_memory.call_args_list)
    assert requests[0] is not requests[1]
    assert saved["adapter:dm:alice"] is not saved["adapter:dm:bob"]
    assert results["adapter:dm:alice"].step_results is not results["adapter:dm:bob"].step_results
    links = {call.args[0]: call.args[2] for call in instance.message_history.link_incoming_messages.await_args_list}
    for user in ("alice", "bob"):
        sid = f"adapter:dm:{user}"
        assert saved[sid][0].content == user + "\n"
        assert f"<text>{user}</text>" in saved[sid][1].content
        assert links[sid] == [user]
        assert len(results[sid].step_results) == 1


@pytest.mark.anyio
async def test_batch_keeps_original_sid_when_plugin_changes_session(processor, monkeypatch):
    instance, _ = processor
    event = batch()
    original_sid = event.sid

    async def redirect(event):
        event.session = Session("adapter", "dm", "changed")

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=redirect)]
        if event_type == EventType.ON_IM_BATCH_MESSAGE else []
    ))
    await instance.handle_im_batch_message(event)

    assert event.sid != original_sid
    assert instance.session_manager.update_memory.call_args.args[0] == original_sid
    assert instance.message_history.link_incoming_messages.await_args.args[0] == original_sid
    assert original_sid in instance.session_locks


@pytest.mark.anyio
async def test_receive_keeps_original_buffer_sid_when_plugin_changes_session(processor, monkeypatch):
    from core.chat.message_utils import KiraMessageEvent
    from core.message_manager import SessionBufferManager

    instance, _ = processor
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements,
        timestamp=1, message=incoming.messages[0], adapter=incoming.adapter,
    )
    original_sid = event.session.sid
    instance.session_buffer = SessionBufferManager()
    instance.session_manager.get_session_info = lambda sid: SimpleNamespace(session_description="")

    async def redirect(event):
        event.session = Session("adapter", "dm", "changed")
        event.buffer()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=redirect)]
        if event_type == EventType.ON_IM_MESSAGE else []
    ))
    await instance.handle_im_message(event)

    assert instance.session_buffer.get_buffer(original_sid).buffer == [event]
    assert instance.session_buffer.get_buffer(event.session.sid).buffer == []


@pytest.mark.anyio
async def test_batch_runs_with_injected_services_without_processor(processor):
    from dataclasses import replace
    from core.workflow.src.im.message_delivery import MessageDeliveryService
    from core.workflow.src.im.workflow import DefaultIMWorkflow

    instance, model = processor
    original = instance.im_workflow.ctx
    formatter = SimpleNamespace(format_to_text=AsyncMock(return_value="injected"))
    media = SimpleNamespace(
        iter_images=lambda chain: iter(()),
        build_native_content=AsyncMock(return_value=[]),
    )
    delivery = SimpleNamespace(
        get_session_lock=lambda sid: asyncio.Lock(),
        send_xml_messages=AsyncMock(return_value=[KiraIMSentResult("injected-id")]),
        add_message_ids=MessageDeliveryService.add_message_ids,
    )
    services = replace(
        original, message_formatter=formatter, message_media=media, message_delivery=delivery,
    )
    services.message_history.record_incoming_safely.return_value = "record-id"
    services.message_history.record_incoming_safely.side_effect = None
    services.session_manager.get_effective_capabilities = lambda *_: {
        "image_recognition": {"mode": "native"},
    }
    workflow = DefaultIMWorkflow(services)

    await workflow.handle_batch_event(batch())

    assert not hasattr(services, "processor")
    model.chat.assert_awaited_once()
    media.build_native_content.assert_awaited_once()
    delivery.send_xml_messages.assert_awaited_once()
    services.db.add_telemetry_llm_usage.assert_awaited_once()
    services.message_history.link_incoming_messages.assert_awaited_once()
    assert services.message_history.link_incoming_messages.await_args.args[2] == ["record-id"]
    memory = services.session_manager.update_memory.call_args.args[1]
    assert memory[0].content == "injected\n"
    assert 'message_id="injected-id"' in memory[1].content


@pytest.mark.anyio
async def test_receive_and_trigger_use_injected_session_manager_and_event_bus(processor):
    from core.chat.message_utils import KiraMessageEvent

    instance, _ = processor
    workflow = instance.im_workflow
    services = workflow.ctx
    services.session_manager = SimpleNamespace(
        get_session_info=lambda sid: SimpleNamespace(session_description="injected description"),
    )
    services.event_bus = SimpleNamespace(publish=AsyncMock())
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements,
        timestamp=1, message=incoming.messages[0], adapter=incoming.adapter,
    )
    event.trigger()

    await workflow.handle_event(event)

    assert not hasattr(services, "processor")
    services.message_history.record_incoming_safely.assert_awaited_once()
    assert event.session.session_description == "injected description"
    published = services.event_bus.publish.await_args.args[0]
    assert published.messages == [event.message]
    assert published.session is event.session


@pytest.mark.anyio
async def test_cached_workflow_picks_up_event_bus_bound_after_creation(processor):
    from core.chat.message_utils import KiraMessageEvent

    instance, _ = processor
    workflow = instance.im_workflow
    assert workflow.ctx.event_bus is None
    instance.event_bus = SimpleNamespace(publish=AsyncMock())
    instance.session_manager.get_session_info = lambda sid: SimpleNamespace(session_description="")
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements,
        timestamp=1, message=incoming.messages[0], adapter=incoming.adapter,
    )
    event.trigger()

    await instance.handle_im_message(event)

    assert instance.im_workflow is workflow
    assert workflow.ctx.event_bus is instance.event_bus
    instance.event_bus.publish.assert_awaited_once()
