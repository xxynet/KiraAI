import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.agent.tool import ToolSet
from core.agent.message import OpenAIMessage
from core.chat.message_elements import Text
from core.chat.message_utils import (
    KiraIMMessage, KiraIMSentResult, KiraMessageBatchEvent, MessageChain,
)
from core.chat.session import Session, User
from core.config.config_loader import KiraConfig
from core.message_manager import MessageProcessor
from core.workflow.src.im.workflow import DefaultIMWorkflow
from tests.im_workflow_helpers import make_workflow_context
from core.plugin.handlers import EventType, event_handler_reg
from core.prompt_manager import Prompt
from core.provider import LLMResponse
from core.tag import RootTagAction


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
    config = SimpleNamespace(get_config=lambda key, default=None: {
        "bot_config.agent.max_tool_loop": 2,
        "bot_config.bot.min_message_delay": 0,
        "bot_config.bot.max_message_delay": 0,
    }.get(key, default))
    model = SimpleNamespace(
        model=SimpleNamespace(provider_name="test", model_id="test", model_name="test"),
        chat=AsyncMock(side_effect=lambda request: LLMResponse("<msg><text>reply</text></msg>")),
    )
    services = make_workflow_context(
        config=config,
        session_manager=SimpleNamespace(
            get_session=AsyncMock(side_effect=lambda sid, *, ensure_session=False, include_content=True: Session(
                *sid.split(":", 2), session_title="Chat", internal_id="sess_test",
            )),
            update_session=AsyncMock(),
            get_effective_capabilities=AsyncMock(side_effect=lambda sid, default: default),
            update_memory=AsyncMock(),
        ),
        provider_mgr=SimpleNamespace(get_default_llm=lambda: model),
        prompt_manager=SimpleNamespace(get_agent_prompt=AsyncMock(return_value=[])),
        skills_manager=SimpleNamespace(skills_info=[]),
        mcp_manager=SimpleNamespace(get_tool_server_map=lambda: {}),
        tool_manager=SimpleNamespace(build_tool_set=ToolSet),
        db=SimpleNamespace(add_telemetry_llm_usage=AsyncMock()),
        message_history=SimpleNamespace(
            record_incoming_safely=AsyncMock(side_effect=lambda msg, *_: msg.message_id),
            link_incoming_messages=AsyncMock(),
        ),
    )
    services.message_delivery.parse_xml = AsyncMock(return_value=[MessageChain([Text("reply")])])
    services.message_delivery.send_message_chain = AsyncMock(return_value=KiraIMSentResult("sent-id"))
    services.message_media.build_native_content = AsyncMock(return_value=[])
    instance = MessageProcessor(DefaultIMWorkflow(services))
    return instance, model


@pytest.mark.anyio
@pytest.mark.parametrize("stop_at", [
    None, EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST,
    EventType.AFTER_XML_PARSE, EventType.ON_MESSAGE_SENT, EventType.ON_STEP_RESULT, EventType.ON_FINAL_RESULT,
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
    await instance.im_workflow.handle_batch_event(batch())

    order = [
        EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST,
        EventType.ON_LLM_RESPONSE, EventType.AFTER_XML_PARSE,
        EventType.ON_MESSAGE_SENT, EventType.ON_STEP_RESULT, EventType.ON_FINAL_RESULT,
    ]
    if stop_at in (EventType.ON_IM_BATCH_MESSAGE, EventType.ON_LLM_REQUEST):
        assert observed == order[:order.index(stop_at) + 1]
        model.chat.assert_not_awaited()
        instance.im_workflow.ctx.session_manager.update_memory.assert_not_called()
        instance.im_workflow.ctx.message_history.link_incoming_messages.assert_not_awaited()
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
        instance.im_workflow.ctx.session_manager.update_memory.assert_called_once()
        memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
        assert [message.role for message in memory] == ["user", "assistant"]
        instance.im_workflow.ctx.message_history.link_incoming_messages.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("settings, expected_steps", [
    ({}, 2),
    ({"max_tool_loop": None}, 2),
    ({"max_tool_loop": ""}, 2),
    ({"max_tool_loop": "invalid"}, 2),
    ({"max_tool_loop": []}, 2),
    ({"max_tool_loop": "3"}, 3),
])
async def test_tool_loop_config_fallback_preserves_execution_and_finalization(
    processor, monkeypatch, settings, expected_steps,
):
    instance, model = processor
    values = {f"bot_config.agent.{key}": value for key, value in settings.items()}
    instance.im_workflow.ctx.config = SimpleNamespace(get_config=lambda key, default=None: values.get(key, default))
    final = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=final)] if event_type == EventType.ON_FINAL_RESULT else []
    ))
    model.chat.side_effect = lambda request: LLMResponse(
        "<msg><text>reply</text></msg>",
        tool_calls=[{"id": "call-1", "type": "function",
                     "function": {"name": "check", "arguments": "{}"}}],
    )

    async def execute_tool(event, response, **kwargs):
        response.tool_results = [{"role": "tool", "tool_call_id": "call-1", "content": "result"}]

    instance.im_workflow.ctx.tool_manager.execute_tool = execute_tool
    await instance.im_workflow.handle_batch_event(batch())

    assert model.chat.await_count == expected_steps
    assert instance.message_delivery.send_message_chain.await_count == expected_steps
    final.assert_awaited_once()
    instance.im_workflow.ctx.session_manager.update_memory.assert_called_once()
    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    assert memory[0].role == "user"
    assert sum(message.role == "assistant" for message in memory) == expected_steps


@pytest.mark.anyio
async def test_request_stop_does_not_persist_native_media(processor, monkeypatch):
    instance, model = processor
    instance.im_workflow.ctx.session_manager.get_effective_capabilities = AsyncMock(side_effect=lambda *_: {
        "image_recognition": {"mode": "native"}
    })

    async def stop(event, *_):
        event.stop()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=stop)] if event_type == EventType.ON_LLM_REQUEST else []
    ))
    await instance.im_workflow.handle_batch_event(batch())

    instance.im_workflow.ctx.message_media.build_native_content.assert_not_awaited()
    model.chat.assert_not_awaited()
    instance.im_workflow.ctx.session_manager.update_memory.assert_not_called()


@pytest.mark.anyio
async def test_missing_model_stops_before_request_hooks_and_memory(processor, monkeypatch):
    instance, _ = processor
    instance.im_workflow.ctx.provider_mgr.get_default_llm = lambda: None
    request_hook = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=request_hook)] if event_type == EventType.ON_LLM_REQUEST else []
    ))

    await instance.im_workflow.handle_batch_event(batch())

    request_hook.assert_not_awaited()
    instance.im_workflow.ctx.session_manager.update_memory.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("append_request_only", [False, True])
async def test_request_only_prompts_and_step_edits_keep_memory_contract(processor, monkeypatch, append_request_only):
    instance, model = processor

    async def customize_request(event, request, tags):
        request.user_prompt.append(Prompt("temporary", persist=False, render_template=False))
        request.user_prompt.append(Prompt("remember", render_template=False))

    async def customize_result(event, result):
        result.raw_output = "edited reply"
        if append_request_only:
            request = model.chat.await_args.args[0]
            request.messages.append(OpenAIMessage(role="user", content="request-only tail"))

    callbacks = {
        EventType.ON_LLM_REQUEST: customize_request,
        EventType.ON_STEP_RESULT: customize_result,
    }
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=callbacks[event_type])] if event_type in callbacks else []
    ))
    await instance.im_workflow.handle_batch_event(batch())

    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    assert memory[0].content == "user\nremember\n"
    assert memory[1].content == "edited reply"
    request = model.chat.await_args.args[0]
    assert "temporary" in request.messages[0].content
    assistant = next(message for message in reversed(request.messages) if message.role == "assistant")
    assert assistant is memory[1]
    assert assistant.content == "edited reply"
    if append_request_only:
        assert request.messages[-1].content == "request-only tail"
    assert len(memory) == 2


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
        instance.im_workflow.handle_batch_event(batch("alice")),
        instance.im_workflow.handle_batch_event(batch("bob")),
    )

    saved = dict(call.args for call in instance.im_workflow.ctx.session_manager.update_memory.call_args_list)
    assert requests[0] is not requests[1]
    assert saved["adapter:dm:alice"] is not saved["adapter:dm:bob"]
    assert results["adapter:dm:alice"].step_results is not results["adapter:dm:bob"].step_results
    links = {call.args[0]: call.args[2] for call in instance.im_workflow.ctx.message_history.link_incoming_messages.await_args_list}
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
    await instance.im_workflow.handle_batch_event(event)

    assert event.sid != original_sid
    assert instance.im_workflow.ctx.session_manager.update_memory.call_args.args[0] == original_sid
    assert instance.im_workflow.ctx.message_history.link_incoming_messages.await_args.args[0] == original_sid
    assert original_sid in instance.im_workflow.ctx.message_delivery.session_locks


@pytest.mark.anyio
async def test_receive_keeps_original_buffer_sid_when_plugin_changes_session(processor, monkeypatch):
    from core.chat.message_utils import KiraMessageEvent
    from core.chat.session_buffer import SessionBufferManager

    instance, _ = processor
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements,
        timestamp=1, message=incoming.messages[0], adapter=incoming.adapter,
    )
    original_sid = event.session.sid
    instance.im_workflow.ctx.message_buffer = SessionBufferManager()
    instance.im_workflow.ctx.session_manager.get_session = AsyncMock(side_effect=lambda sid, *, ensure_session=False, include_content=True: Session(*sid.split(":", 2), session_description="", internal_id="sess_test"))

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
        parse_xml=AsyncMock(return_value=[MessageChain([Text("reply")])]),
        send_message_chain=AsyncMock(return_value=KiraIMSentResult("injected-id")),
        min_message_delay=0,
        max_message_delay=0,
        add_message_ids=MessageDeliveryService.add_message_ids,
    )
    services = replace(
        original, message_formatter=formatter, message_media=media, message_delivery=delivery,
    )
    services.message_history.record_incoming_safely.return_value = "record-id"
    services.message_history.record_incoming_safely.side_effect = None
    services.session_manager.get_effective_capabilities = AsyncMock(side_effect=lambda *_: {
        "image_recognition": {"mode": "native"},
    })
    workflow = DefaultIMWorkflow(services)

    await workflow.handle_batch_event(batch())

    assert not hasattr(services, "processor")
    model.chat.assert_awaited_once()
    media.build_native_content.assert_awaited_once()
    delivery.parse_xml.assert_awaited_once()
    delivery.send_message_chain.assert_awaited_once()
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
        get_session=AsyncMock(side_effect=lambda sid, *, ensure_session=False, include_content=True: Session(*sid.split(":", 2), session_description="injected description", internal_id="sess_test")),
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
@pytest.mark.parametrize("is_notice", [False, True])
@pytest.mark.parametrize("populate_in_plugin", [False, True])
async def test_receive_skips_empty_history_and_archives_plugin_content_in_batch(
    processor, monkeypatch, is_notice, populate_in_plugin,
):
    from core.chat.message_utils import KiraMessageEvent

    instance, _ = processor
    workflow = instance.im_workflow
    services = workflow.ctx
    message = batch().messages[0]
    message.chain = MessageChain()
    message.is_notice = is_notice
    event = KiraMessageEvent(
        supported_elements=["text"], timestamp=1, message=message,
        adapter=AdapterInfo(True, "test", "adapter", "test"),
    )

    async def populate(event):
        event.message.chain.text("plugin content")
        event.trigger()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=populate)]
        if populate_in_plugin and event_type == EventType.ON_IM_MESSAGE else []
    ))
    await workflow.handle_event(event)
    services.message_history.record_incoming_safely.assert_not_awaited()
    if populate_in_plugin:
        published = services.event_bus.publish.await_args.args[0]
        await workflow.handle_batch_event(published)
        services.message_history.record_incoming_safely.assert_awaited_once_with(
            message, event.session.sid, "test",
        )
        assert services.message_history.link_incoming_messages.await_args.args[2] == [message.message_id]
    else:
        services.event_bus.publish.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("is_notice", [False, True])
async def test_batch_archives_only_messages_with_content(processor, is_notice):
    instance, _ = processor
    services = instance.im_workflow.ctx
    event = batch()
    nonempty = event.messages[0]
    empty = batch("empty").messages[0]
    empty.chain = MessageChain()
    empty.is_notice = is_notice
    event.messages.insert(0, empty)

    await instance.im_workflow.handle_batch_event(event)

    services.message_history.record_incoming_safely.assert_awaited_once_with(
        nonempty, event.session.sid, "test",
    )
    assert services.message_history.link_incoming_messages.await_args.args[2] == [nonempty.message_id]


@pytest.mark.anyio
async def test_processor_preserves_injected_workflow_and_event_bus(processor):
    from core.chat.message_utils import KiraMessageEvent

    instance, _ = processor
    workflow = instance.im_workflow
    event_bus = workflow.ctx.event_bus
    instance.im_workflow.ctx.session_manager.get_session = AsyncMock(side_effect=lambda sid, *, ensure_session=False, include_content=True: Session(*sid.split(":", 2), session_description="", internal_id="sess_test"))
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements,
        timestamp=1, message=incoming.messages[0], adapter=incoming.adapter,
    )
    event.trigger()

    await instance.handle_im_message(event)

    assert instance.im_workflow is workflow
    assert workflow.ctx.event_bus is event_bus
    instance.im_workflow.ctx.event_bus.publish.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("root_fails", [False, True])
async def test_execution_preserves_message_and_root_action_order(processor, monkeypatch, root_fails):
    instance, _ = processor
    delivery = instance.message_delivery
    seen = []
    final = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=final)] if event_type == EventType.ON_FINAL_RESULT else []
    ))

    async def send(sid, chain, **kwargs):
        seen.append(chain[0].text)
        return KiraIMSentResult(chain[0].text)

    async def root(value, **attrs):
        seen.append(value)
        if root_fails:
            raise ValueError("control failed")

    delivery.send_message_chain = send
    delivery.parse_xml.return_value = [
        MessageChain([Text("first")]),
        RootTagAction(tag=SimpleNamespace(name="control", handle=root), value="control", attrs={}),
        MessageChain([Text("second")]),
    ]

    await instance.im_workflow.handle_batch_event(batch())

    assert seen == ["first", "control", "second"]
    results = final.await_args.args[1].step_results[0].message_results
    assert [result.message_id for result in results] == ["first", "second"]
    instance.im_workflow.ctx.session_manager.update_memory.assert_called_once()


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_delay", [None, "", "invalid", []])
async def test_execution_continues_after_invalid_runtime_delay_update(processor, monkeypatch, invalid_delay):
    instance, _ = processor
    config = dict.__new__(KiraConfig)
    config["bot_config"] = {"bot": {"min_message_delay": 0, "max_message_delay": 0}}
    delivery = instance.message_delivery
    delivery.kira_config = config
    sleep = AsyncMock()
    uniform = Mock(side_effect=lambda low, high: low)
    warning = Mock()
    monkeypatch.setattr("core.workflow.src.im.stages.execute.asyncio.sleep", sleep)
    monkeypatch.setattr("core.workflow.src.im.stages.execute.random.uniform", uniform)
    monkeypatch.setattr("core.workflow.src.im.message_delivery.logger.warning", warning)
    seen = []

    async def send(sid, chain, **kwargs):
        seen.append(chain[0].text)
        if len(seen) == 1:
            config["bot_config"]["bot"] = {
                "min_message_delay": invalid_delay, "max_message_delay": invalid_delay,
            }
        return KiraIMSentResult(chain[0].text)

    async def root(value, **attrs):
        seen.append(value)
        config["bot_config"]["bot"] = {"min_message_delay": 0, "max_message_delay": 0}

    delivery.send_message_chain = send
    delivery.parse_xml.return_value = [
        MessageChain([Text("first")]),
        RootTagAction(tag=SimpleNamespace(name="control", handle=root), value="control", attrs={}),
        MessageChain([Text("second")]),
    ]

    await instance.im_workflow.handle_batch_event(batch())

    assert seen == ["first", "control", "second"]
    assert [call.args for call in uniform.call_args_list] == [(0.8, 1.5), (0, 0)]
    assert [call.args for call in sleep.await_args_list] == [(0.8,), (0,)]
    assert [call.args[1:] for call in warning.call_args_list] == [
        ("bot_config.bot.min_message_delay", 0.8),
        ("bot_config.bot.max_message_delay", 1.5),
    ]


@pytest.mark.anyio
async def test_execution_passes_history_provenance(processor):
    instance, _ = processor
    event = batch("channel/123")
    event.bot.nickname = "Kira"
    assert event.bot is event.messages[-1].bot
    chain = MessageChain([Text("reply")])
    instance.message_delivery.parse_xml.return_value = [chain]

    await instance.im_workflow.handle_batch_event(event)

    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    instance.message_delivery.send_message_chain.assert_awaited_once_with(
        event.sid, chain, memory_message=memory[-1], bot=event.bot,
    )
    assert instance.message_delivery.send_message_chain.await_args.kwargs["memory_message"] is memory[-1]


@pytest.mark.anyio
async def test_message_sent_stop_skips_remaining_actions_and_preserves_results(processor, monkeypatch):
    instance, _ = processor
    root = AsyncMock()
    final = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr("core.workflow.src.im.stages.execute.asyncio.sleep", sleep)

    async def stop(event, *args):
        event.stop()

    callbacks = {EventType.ON_MESSAGE_SENT: stop, EventType.ON_FINAL_RESULT: final}
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=callbacks[event_type])] if event_type in callbacks else []
    ))
    first = MessageChain([Text("first")])
    instance.message_delivery.parse_xml.return_value = [
        first,
        RootTagAction(tag=SimpleNamespace(name="control", handle=root), value="control", attrs={}),
        MessageChain([Text("second")]),
    ]

    await instance.im_workflow.handle_batch_event(batch())

    instance.message_delivery.send_message_chain.assert_awaited_once()
    assert instance.message_delivery.send_message_chain.await_args.args[1] is first
    root.assert_not_awaited()
    sleep.assert_not_awaited()
    final.assert_awaited_once()
    results = final.await_args.args[1].step_results[0].message_results
    assert [result.message_id for result in results] == ["sent-id"]
    instance.im_workflow.ctx.session_manager.update_memory.assert_called_once()


@pytest.mark.anyio
async def test_xml_parse_failure_still_finalizes(processor, monkeypatch):
    instance, _ = processor
    instance.message_delivery.parse_xml.side_effect = ValueError("invalid XML")
    final = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=final)] if event_type == EventType.ON_FINAL_RESULT else []
    ))

    await instance.im_workflow.handle_batch_event(batch())

    instance.message_delivery.send_message_chain.assert_not_awaited()
    final.assert_awaited_once()
    assert final.await_args.args[1].step_results[0].message_results == []
    instance.im_workflow.ctx.session_manager.update_memory.assert_called_once()

@pytest.mark.anyio
@pytest.mark.parametrize("through_processor", [False, True])
async def test_direct_im_and_comments_share_limit_while_batches_can_run(processor, through_processor, monkeypatch):
    from core.chat.message_utils import KiraMessageEvent, KiraCommentEvent

    original, _ = processor
    workflow = DefaultIMWorkflow(original.im_workflow.ctx, max_concurrent_messages=1)
    instance = MessageProcessor(workflow)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def receive(ctx):
        entered.set()
        await release.wait()
        return False

    receive_stage = SimpleNamespace(run=AsyncMock(side_effect=receive))
    batch_stage = SimpleNamespace(run=AsyncMock(return_value=False))
    workflow.event_stages = (receive_stage,)
    workflow.batch_stages = (batch_stage,)
    comment_handler = AsyncMock()
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=comment_handler)] if event_type == EventType.ON_COMMENT else []
    ))
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements, timestamp=1,
        message=incoming.messages[0], adapter=incoming.adapter,
    )
    handle = instance.handle_im_message if through_processor else workflow.handle_event
    tasks = [asyncio.create_task(handle(event))]
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        tasks.append(asyncio.create_task(handle(event)))
        tasks.append(asyncio.create_task(instance.handle_cmt_event(Mock(spec=KiraCommentEvent, is_stopped=False))))
        await asyncio.sleep(0)
        assert receive_stage.run.await_count == 1
        comment_handler.assert_not_awaited()

        await asyncio.wait_for(workflow.handle_batch_event(incoming), timeout=1)
        batch_stage.run.assert_awaited_once()

        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=1)
        assert receive_stage.run.await_count == 2
        comment_handler.assert_awaited_once()
    finally:
        release.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.anyio
async def test_stopped_response_does_not_overwrite_previous_assistant(processor, monkeypatch):
    instance, model = processor
    model.chat.side_effect = [
        LLMResponse("first reply", tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "check", "arguments": "{}"},
        }]),
        LLMResponse("stopped reply"),
    ]

    async def execute_tool(event, response, **kwargs):
        response.tool_results = [{"role": "tool", "tool_call_id": "call-1", "content": "result"}]

    async def stop_second_response(event, response):
        if response.agent_step_index == 2:
            event.stop()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=stop_second_response)]
        if event_type == EventType.ON_LLM_RESPONSE else []
    ))
    instance.im_workflow.ctx.tool_manager.execute_tool = execute_tool
    await instance.im_workflow.handle_batch_event(batch())

    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    assert [message.role for message in memory] == ["user", "assistant", "tool"]
    assert "first reply" in memory[1].content
    assert "stopped reply" not in memory[1].content
    request = model.chat.await_args.args[0]
    assert next(message for message in request.messages if message.role == "assistant") is memory[1]
    assert "final model call" in request.messages[-1].content


@pytest.mark.anyio
@pytest.mark.parametrize("state", ["existing", "untitled", "missing"])
async def test_build_request_loads_current_session(processor, session_db, tmp_path, monkeypatch, state):
    from core.chat.session_manager import SessionManager
    from core.workflow.src.im.context import IMBatchContext
    from core.workflow.src.im.stages.request import BuildRequestStage

    instance, _ = processor
    services = instance.im_workflow.ctx
    manager = SessionManager(session_db, {})
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await manager.initialize()
    event = batch()
    event.session.session_title = "Incoming title"
    event.session.session_description = "Plugin description"
    if state != "missing":
        await manager.update_session(
            event.session.sid, title="Saved title" if state == "existing" else "",
            content=[[{"role": "user", "content": "latest history"}]],
        )
    services.session_manager = manager
    query = AsyncMock(wraps=manager.get_session)
    monkeypatch.setattr(manager, "get_session", query)
    ctx = IMBatchContext(services, event)
    assert await BuildRequestStage().run(ctx)
    query.assert_awaited_once_with(ctx.sid, ensure_session=True)
    assert event.session.content == []
    assert event.session.internal_id is None
    assert [message.content for message in ctx.request.messages] == ([] if state == "missing" else ["latest history"])
    row = await session_db.get_chat_session(ctx.sid)
    assert row["title"] == ("Saved title" if state == "existing" else "Incoming title")
    environment = services.prompt_manager.get_agent_prompt.await_args.args[0]
    assert environment["session_title"] == row["title"]
    assert environment["session_description"] == "Plugin description"


@pytest.mark.anyio
@pytest.mark.parametrize("buffered", [False, True])
@pytest.mark.parametrize("delete_before_build", [False, True])
async def test_event_session_identity_through_receive_batch_and_request(
    processor, session_db, tmp_path, buffered, delete_before_build,
):
    from core.chat.message_utils import KiraMessageEvent
    from core.chat.session_manager import SessionManager
    from core.workflow.src.im.batching import publish_buffered_messages
    from core.workflow.src.im.context import IMEventContext, IMBatchContext
    from core.workflow.src.im.stages.receive import ReceiveStage, RouteStage
    from core.workflow.src.im.stages.request import BuildRequestStage

    instance, _ = processor
    services = instance.im_workflow.ctx
    manager = SessionManager(session_db, {})
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await manager.initialize()
    services.session_manager = manager
    incoming = batch()
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements, timestamp=1,
        message=incoming.messages[0], adapter=incoming.adapter,
    )
    assert event.session.internal_id is None
    ctx = IMEventContext(services, event)
    assert await ReceiveStage().run(ctx)
    original_id = event.session.internal_id
    assert original_id.startswith("sess_")
    if buffered:
        event.buffer()
    else:
        event.trigger()
    await RouteStage().run(ctx)
    if buffered:
        assert await publish_buffered_messages(services.message_buffer, services.event_bus, ctx.sid)
    published = services.event_bus.publish.await_args.args[0]
    assert published.session is event.session
    assert published.session.internal_id == original_id
    if delete_before_build:
        await manager.delete_session(ctx.sid)
        assert published.session.internal_id == original_id
    assert await BuildRequestStage().run(IMBatchContext(services, published))
    persisted = await manager.get_session(ctx.sid)
    assert published.session.internal_id == original_id
    assert (persisted.internal_id != original_id) is delete_before_build


@pytest.mark.anyio
@pytest.mark.parametrize("stored_title", ["Saved title", ""])
async def test_receive_keeps_event_lightweight_before_plugins(processor, session_db, tmp_path, monkeypatch, stored_title):
    from sqlalchemy import event as sqlalchemy_event
    from core.chat.message_utils import KiraMessageEvent
    from core.chat.session_manager import SessionManager
    from core.workflow.src.im.context import IMEventContext
    from core.workflow.src.im.stages.receive import ReceiveStage

    instance, _ = processor
    services = instance.im_workflow.ctx
    manager = SessionManager(session_db, {})
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await manager.initialize()
    incoming = batch()
    incoming.messages[0].sender.nickname = "Platform nickname"
    event = KiraMessageEvent(
        supported_elements=incoming.supported_elements, timestamp=1,
        message=incoming.messages[0], adapter=incoming.adapter,
    )
    original = event.session
    await manager.update_session(
        original.sid, title=stored_title, description="Stored description",
        content=[[{"role": "user", "content": "History"}]], data={"custom": True},
    )
    services.session_manager = manager
    query = AsyncMock(wraps=manager.get_session)
    monkeypatch.setattr(manager, "get_session", query)
    seen = []

    async def inspect_session(received):
        assert received.session is original
        assert received.session.internal_id.startswith("sess_")
        assert received.session.session_title == "Platform nickname"
        assert received.session.session_description == "Stored description"
        assert received.session.content == [] and received.session.data == {}
        seen.append(received.session)

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=inspect_session)] if event_type == EventType.ON_IM_MESSAGE else []
    ))
    queries = []

    def capture_sql(conn, cursor, statement, parameters, context, executemany):
        queries.append((statement, [column[0] for column in cursor.description]))

    sqlalchemy_event.listen(session_db.db.engine.sync_engine, "after_cursor_execute", capture_sql)
    try:
        assert await ReceiveStage().run(IMEventContext(services, event))
    finally:
        sqlalchemy_event.remove(session_db.db.engine.sync_engine, "after_cursor_execute", capture_sql)
    assert len(queries) == 1
    sql, columns = queries[0]
    assert "chat_sessions.content" not in sql
    assert "content" not in columns and "data" in columns
    query.assert_awaited_once_with(original.sid, ensure_session=True, include_content=False)
    assert seen == [original]
    assert (await session_db.get_chat_session(original.sid))["title"] == stored_title


@pytest.mark.anyio
@pytest.mark.parametrize("outcome", ["success", "error", "cancelled"])
async def test_workflow_protects_native_and_tool_media_until_finalization(
    processor, tmp_path, monkeypatch, outcome,
):
    from core.chat.message_elements import Image
    from core.utils import media_refs

    monkeypatch.setattr(media_refs, "get_data_path", lambda: tmp_path)
    instance, model = processor
    services = instance.im_workflow.ctx
    event = batch()
    sid = event.sid
    image = Image("data:image/png;base64,aGVsbG8=")
    references = []
    services.session_manager.get_effective_capabilities = AsyncMock(return_value={
        "image_recognition": {"mode": "native"},
    })

    async def native_content(message, session_id):
        reference = await media_refs.store_session_media(image, session_id, message.message_id)
        references.append(reference)
        return [{"type": "text", "text": message.message_str}, reference]

    services.message_media.build_native_content = native_content

    async def assert_protected():
        await asyncio.to_thread(media_refs.cleanup_session_media, sid, [])
        assert all((tmp_path / ref["path"]).exists() for ref in references)

    async def chat(_request):
        # Tools invoked by the model share the same protection as native input.
        references.append(await media_refs.store_session_media(image, sid, "tool-result"))
        await assert_protected()
        if outcome == "error":
            raise RuntimeError("model failed")
        if outcome == "cancelled":
            raise asyncio.CancelledError
        return LLMResponse("<msg><text>reply</text></msg>")

    async def save_memory(_sid, _messages):
        await assert_protected()

    model.chat.side_effect = chat
    services.session_manager.update_memory.side_effect = save_memory
    if outcome == "success":
        await instance.im_workflow.handle_batch_event(event)
        services.session_manager.update_memory.assert_awaited_once()
    else:
        error = RuntimeError if outcome == "error" else asyncio.CancelledError
        with pytest.raises(error):
            await instance.im_workflow.handle_batch_event(event)
        services.session_manager.update_memory.assert_not_awaited()

    assert len(references) == 2
    await asyncio.to_thread(media_refs.cleanup_session_media, sid, [])
    assert all(not (tmp_path / ref["path"]).exists() for ref in references)


@pytest.mark.anyio
@pytest.mark.parametrize("error_type", ["api_status", "provider"])
@pytest.mark.parametrize("after_tool_step", [False, True])
@pytest.mark.parametrize("body", [
    '<html><head><title>413 Request Entity Too Large</title></head><body><msg><text>error & body',
    '<msg><text>provider error</text></msg>',
])
async def test_provider_error_stays_internal(processor, monkeypatch, error_type, after_tool_step, body):
    import importlib

    import httpx
    from openai import APIStatusError
    from core.provider import ProviderAPIError

    main = importlib.import_module("core.plugin.builtin_plugins.kira-ai.main")
    plugin_ctx = Mock()
    plugin = main.DefaultPlugin(plugin_ctx, {})
    instance, model = processor
    if error_type == "api_status":
        error = APIStatusError(body, response=httpx.Response(
            413, request=httpx.Request("POST", "https://provider.invalid/chat"),
        ), body=body)
    else:
        error = ProviderAPIError(body)
    if after_tool_step:
        model.chat.side_effect = [LLMResponse("<msg><text>reply</text></msg>", tool_calls=[{
            "id": "call-1", "type": "function",
            "function": {"name": "check", "arguments": "{}"},
        }]), error]

        async def execute_tool(event, response, **kwargs):
            response.tool_results = [{"role": "tool", "tool_call_id": "call-1", "content": "result"}]

        instance.im_workflow.ctx.tool_manager.execute_tool = execute_tool
    else:
        model.chat.side_effect = error
    response_handler = AsyncMock(side_effect=plugin.on_llm_resp)
    observer = AsyncMock()
    exception_handler, final = AsyncMock(), AsyncMock()
    step_handler, sent_handler, parse_handler = AsyncMock(), AsyncMock(), AsyncMock()
    callbacks = {
        EventType.ON_LLM_RESPONSE: response_handler,
        EventType.ON_EXCEPTION: exception_handler,
        EventType.ON_STEP_RESULT: step_handler,
        EventType.ON_MESSAGE_SENT: sent_handler,
        EventType.AFTER_XML_PARSE: parse_handler,
        EventType.ON_FINAL_RESULT: final,
    }
    def handlers(event_type):
        if event_type == EventType.ON_LLM_RESPONSE:
            return [SimpleNamespace(exec_handler=response_handler), SimpleNamespace(exec_handler=observer)]
        return [SimpleNamespace(exec_handler=callbacks[event_type], handler=callbacks[event_type])] if event_type in callbacks else []

    monkeypatch.setattr(event_handler_reg, "get_handlers", handlers)

    await instance.im_workflow.handle_batch_event(batch())

    assert response_handler.await_count == observer.await_count == 1 + int(after_tool_step)
    assert instance.message_delivery.parse_xml.await_count == int(after_tool_step)
    assert instance.message_delivery.send_message_chain.await_count == int(after_tool_step)
    plugin_ctx.get_default_fast_llm_client.assert_not_called()
    plugin_ctx.get_default_llm_client.assert_not_called()
    exception_handler.assert_awaited_once()
    exception = exception_handler.await_args.args[1]
    assert exception.source == "provider" and exception.e is error
    assert exception.message == str(error)
    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    assert [message.role for message in memory] == (
        ["user", "assistant", "tool", "assistant"] if after_tool_step else ["user", "assistant"]
    )
    expected = f"[ProviderError] All models in the group failed to respond. {type(error).__name__}: {error}"
    assert memory[-1].content == expected
    observed_response = observer.await_args.args[1]
    assert observed_response.status == "error"
    assert observed_response.text_response == expected
    if after_tool_step:
        assert "reply" in memory[1].content
    usage = instance.im_workflow.ctx.db.add_telemetry_llm_usage.await_args.kwargs
    assert usage["success"] is False
    final.assert_awaited_once()
    results = final.await_args.args[1].step_results
    assert len(results) == step_handler.await_count == 1 + int(after_tool_step)
    assert results[-1].raw_output == expected
    assert results[-1].message_results == []
    assert sent_handler.await_count == parse_handler.await_count == int(after_tool_step)


@pytest.mark.anyio
async def test_provider_error_is_persisted_and_loaded_into_next_turn(processor, session_db, tmp_path):
    from core.chat.session_manager import SessionManager
    from core.provider import ProviderAPIError

    instance, model = processor
    services = instance.im_workflow.ctx
    config = {"bot_config": {"bot": {"max_memory_length": 10}}}
    manager = SessionManager(session_db, config)
    manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await manager.initialize()
    services.session_manager = manager
    error = ProviderAPIError("<html>413 Request Entity Too Large</html>")
    expected = f"[ProviderError] All models in the group failed to respond. ProviderAPIError: {error}"
    requests = []

    async def chat(request):
        requests.append([message.to_dict() for message in request.messages])
        if len(requests) == 1:
            raise error
        return LLMResponse("<msg><text>reply</text></msg>")

    model.chat.side_effect = chat
    event = batch()
    event.session.session_title = "Chat"
    await instance.im_workflow.handle_batch_event(event)

    services.message_delivery.send_message_chain.assert_not_awaited()
    saved = (await manager.get_session(event.sid)).flatten_content()
    assert [message["role"] for message in saved] == ["user", "assistant"]
    assert saved[-1]["content"] == expected

    reloaded_manager = SessionManager(session_db, config)
    reloaded_manager.chat_memory_path = str(tmp_path / "chat_memory.json")
    await reloaded_manager.initialize()
    services.session_manager = reloaded_manager
    await instance.im_workflow.handle_batch_event(batch())

    assert len(requests) == 2
    assert requests[1][1]["role"] == "assistant"
    assert requests[1][1]["content"] == expected
    services.message_delivery.send_message_chain.assert_awaited_once()
    assert services.message_delivery.send_message_chain.await_args.args[1][0].text == "reply"


@pytest.mark.anyio
@pytest.mark.parametrize("with_tool_calls", [False, True])
async def test_error_status_response_is_context_only(processor, monkeypatch, with_tool_calls):
    instance, model = processor
    text = "<msg><text>Provider returned an error & diagnostic</text></msg>"
    response = LLMResponse(text, status="error", tool_calls=[{
        "id": "call-1", "type": "function",
        "function": {"name": "check", "arguments": "{}"},
    }] if with_tool_calls else [])
    model.chat.side_effect = None
    model.chat.return_value = response
    execute_tool = AsyncMock()
    instance.im_workflow.ctx.tool_manager.execute_tool = execute_tool
    response_hook, step_hook, final_hook = AsyncMock(), AsyncMock(), AsyncMock()
    callbacks = {
        EventType.ON_LLM_RESPONSE: response_hook,
        EventType.ON_STEP_RESULT: step_hook,
        EventType.ON_FINAL_RESULT: final_hook,
    }
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: (
        [SimpleNamespace(exec_handler=callbacks[event_type])] if event_type in callbacks else []
    ))

    await instance.im_workflow.handle_batch_event(batch())

    model.chat.assert_awaited_once()
    execute_tool.assert_not_awaited()
    response_hook.assert_awaited_once()
    assert response_hook.await_args.args[1] is response
    assert response_hook.await_args.args[1].status == "error"
    instance.message_delivery.parse_xml.assert_not_awaited()
    instance.message_delivery.send_message_chain.assert_not_awaited()
    memory = instance.im_workflow.ctx.session_manager.update_memory.call_args.args[1]
    assert [message.role for message in memory] == ["user", "assistant"]
    assert memory[-1].content == text
    assert not memory[-1].tool_calls
    assert response.agent_step_index == 1
    assert instance.im_workflow.ctx.db.add_telemetry_llm_usage.await_args.kwargs["success"] is False
    step_hook.assert_awaited_once()
    result = step_hook.await_args.args[1]
    assert result.raw_output == text and result.message_results == []
    final_hook.assert_awaited_once()
    assert final_hook.await_args.args[1].step_results == [result]


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["success", "error"])
async def test_builtin_xml_repair_respects_response_status(status):
    import importlib

    main = importlib.import_module("core.plugin.builtin_plugins.kira-ai.main")
    original = "<msg><text>text & data</text></msg>"
    fixed = "<msg><text>text &amp; data</text></msg>"
    client = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(fixed)))
    ctx = SimpleNamespace(get_default_fast_llm_client=Mock(return_value=client))
    plugin = main.DefaultPlugin(ctx, {})
    response = LLMResponse(original, status=status)

    await plugin.on_llm_resp(None, response)

    if status == "error":
        ctx.get_default_fast_llm_client.assert_not_called()
        client.chat.assert_not_awaited()
        assert response.text_response == original
    else:
        client.chat.assert_awaited_once()
        assert response.text_response == fixed
