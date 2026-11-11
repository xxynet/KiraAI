"""Session-based routing without identifier parsing or execution waits."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter.access import ListAccessPolicy
from core.adapter.capabilities import IMCapability
from core.agent.message import OpenAIMessage
from core.chat.im_message_route import IMMessageRoute
from core.chat.message_elements import Image, Text
from core.chat.message_router import MessageRouter
from core.chat.message_utils import (
    KiraIMMessage,
    KiraIMSentResult,
    KiraMessageBatchEvent,
    KiraMessageEvent,
    MessageChain,
)
from core.chat.session import Session, User
from core.chat.session_manager import SessionManager
from core.event_bus import EventBus
from core.message_manager import MessageProcessor
from core.plugin.builtin_plugins.session_tools.main import SessionPlugin
from core.plugin.plugin_context import PluginContext
from tests.im_workflow_helpers import make_session_manager
from tests.test_adapter_base import make_adapter


def _route(matches=lambda session: True):
    return SimpleNamespace(
        matches=Mock(side_effect=matches),
        receive_message=AsyncMock(),
        send_message_chain=AsyncMock(return_value=KiraIMSentResult("message-1")),
    )


def _session(**kwargs):
    return Session("example", "dm", "opaque:123", **kwargs)


@pytest.mark.anyio
async def test_route_receives_the_original_complete_session_payload_and_receipt():
    route = _route()
    router = MessageRouter(session_manager=make_session_manager())
    router.register_route(route)
    session = _session(internal_id="sess_one", data={"worker": True}, content=[[{"role": "user", "content": "previous"}]])
    chain = MessageChain([Text("hello"), Image(image="https://example.invalid/image.png")])
    memory = OpenAIMessage(role="assistant", content="hello")
    bot = User("bot", "Kira")

    result = await router.send_message_chain(session, chain, memory_message=memory, bot=bot)

    assert result is route.send_message_chain.return_value
    route.send_message_chain.assert_awaited_once_with(session, chain, memory_message=memory, bot=bot)
    assert route.matches.call_args.args[0] is session
    assert route.send_message_chain.await_args.args[0] is session
    assert route.send_message_chain.await_args.args[1] is chain
    message = object()
    await router.receive_message(session, message)
    route.receive_message.assert_awaited_once_with(session, message)
    assert route.receive_message.await_args.args[0] is session
    assert route.receive_message.await_args.args[1] is message


@pytest.mark.anyio
@pytest.mark.parametrize("criterion", ["internal_id", "data", "content"])
async def test_matchers_can_use_identity_metadata_or_history_without_parsing_sid(criterion):
    router = MessageRouter(session_manager=make_session_manager())
    # The adapter and session type deliberately do not follow an IM routing key.
    session = Session("not:a:namespace", "worker", "", internal_id="sess_worker", data={"route": "worker"},
                      content=[[{"role": "user", "content": "performance"}]])
    rules = {
        "internal_id": lambda s: s.internal_id == "sess_worker",
        "data": lambda s: s.data.get("route") == "worker",
        "content": lambda s: s.content[-1][-1]["content"] == "performance",
    }
    miss = _route(lambda s: False)
    worker = _route(rules[criterion])
    router.register_route(miss)
    router.register_route(worker)
    await router.send_message_chain(session, MessageChain([Text("work")]))
    miss.send_message_chain.assert_not_awaited()
    assert worker.send_message_chain.await_args.args[0] is session


@pytest.mark.anyio
async def test_priority_then_registration_order_determine_the_first_match():
    router = MessageRouter(session_manager=make_session_manager())
    im, first, second = _route(), _route(), _route()
    router.register_route(im, priority=-100)
    router.register_route(first)
    router.register_route(second)
    session, chain = _session(), MessageChain([Text("work")])
    await router.send_message_chain(session, chain)
    first.send_message_chain.assert_awaited_once()
    second.matches.assert_not_called()
    im.matches.assert_not_called()
    assert router.unregister_route(first)
    await router.send_message_chain(session, chain)
    second.send_message_chain.assert_awaited_once()
    assert router.unregister_route(second)
    await router.send_message_chain(session, chain)
    im.send_message_chain.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("operation", ["receive_message", "send_message_chain"])
async def test_unmatched_sessions_do_not_fall_back_to_a_transport(operation):
    router = MessageRouter(session_manager=make_session_manager())
    route = _route(lambda s: False)
    router.register_route(route)
    session = _session(internal_id="sess_missing")
    args = {
        "receive_message": (session, object()),
        "send_message_chain": (session, MessageChain([Text("hello")])),
    }[operation]
    with pytest.raises(ValueError, match="No message route matches.*sess_missing"):
        await getattr(router, operation)(*args)
    getattr(route, operation).assert_not_awaited()


def test_registration_and_removal_use_route_identity():
    router = MessageRouter(session_manager=make_session_manager())
    first, other = _route(), _route()
    router.register_route(first)
    with pytest.raises(ValueError, match="already registered"):
        router.register_route(first)
    assert not router.unregister_route(other)
    assert router.unregister_route(first)
    assert not router.unregister_route(first)
    with pytest.raises(ValueError, match="No message route"):
        router._resolve(_session())
    router.register_route(other)
    assert router._resolve(_session()) is other


@pytest.mark.anyio
async def test_router_rejects_strings_instead_of_resolving_them_itself():
    route = _route()
    router = MessageRouter(session_manager=make_session_manager())
    router.register_route(route)
    with pytest.raises(TypeError, match="Session object"):
        await router.send_message_chain("adapter:dm:one", MessageChain([Text("hello")]))
    route.matches.assert_not_called()


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
@pytest.mark.parametrize("operation", ["receive_message", "send_message_chain"])
async def test_transport_failure_or_cancellation_propagates_without_retry(error, operation):
    router = MessageRouter(session_manager=make_session_manager())
    failing, other = _route(), _route()
    getattr(failing, operation).side_effect = error("delivery failed")
    router.register_route(failing)
    router.register_route(other)
    with pytest.raises(error, match="delivery failed"):
        payload = object() if operation == "receive_message" else MessageChain([Text("hello")])
        await getattr(router, operation)(_session(), payload)
    getattr(failing, operation).assert_awaited_once()
    getattr(other, operation).assert_not_awaited()


@pytest.mark.anyio
async def test_delivery_returns_while_the_receiving_agent_is_still_running():
    release = asyncio.Event()
    running = []
    receipt = KiraIMSentResult("input-1")

    async def receive(session, chain, **kwargs):
        running.append(asyncio.create_task(release.wait()))
        return receipt

    route = _route()
    route.send_message_chain.side_effect = receive
    router = MessageRouter(session_manager=make_session_manager())
    router.register_route(route)
    try:
        result = await asyncio.wait_for(router.send_message_chain(
            _session(), MessageChain([Text("work")]),
        ), timeout=2)
        assert result is receipt
        assert len(running) == 1 and not running[0].done()
    finally:
        release.set()
        await asyncio.gather(*running)


@pytest.mark.anyio
async def test_plugin_and_legacy_processor_resolve_targets_and_share_the_injected_router():
    router = MessageRouter(session_manager=make_session_manager())
    internal = _route(lambda s: s.data.get("route") == "worker")
    router.register_route(internal)
    session = _session(internal_id="sess_one", data={"route": "worker"})
    manager = make_session_manager()
    manager.get_session = AsyncMock(return_value=session)
    ctx = object.__new__(PluginContext)
    ctx.message_router = router
    ctx.session_mgr = manager
    ctx.event_bus = SimpleNamespace(publish=AsyncMock())
    adapter = make_adapter()
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    workflow = SimpleNamespace(
        message_processing_semaphore=asyncio.Semaphore(1),
        ctx=SimpleNamespace(session_manager=manager),
    )
    processor = MessageProcessor(
        workflow,
        message_router=router,
    )
    chain = MessageChain([Text("hello")])

    assert await ctx.send_message_chain(session.sid, chain) is internal.send_message_chain.return_value
    assert await processor.send_message_chain(session.sid, chain) is internal.send_message_chain.return_value
    await ctx.publish_notice(session, chain, is_mentioned=False)

    assert processor.message_router is router
    assert internal.send_message_chain.await_count == 2
    assert all(call.args[0] is session for call in internal.send_message_chain.await_args_list)
    ctx.event_bus.publish.assert_awaited_once()
    event = ctx.event_bus.publish.await_args.args[0]
    assert event.session is session and event.message.chain is chain
    assert isinstance(event, KiraMessageEvent)
    assert event.is_notice and not event.is_mentioned
    assert event.message.sender.nickname == "system"
    assert event.message.message_id == "system_message"
    assert not hasattr(router, "publish_notice")
    assert not hasattr(router, "publish_event")


@pytest.mark.anyio
@pytest.mark.parametrize("denied", [False, True])
async def test_session_send_checks_adapter_permission_before_publishing_to_event_bus(denied):
    session = _session(internal_id="sess_one", data={"owner": "source:dm:one"})
    manager = make_session_manager()
    manager.resolve_session = AsyncMock(return_value=session)
    ctx = object.__new__(PluginContext)
    ctx.session_mgr = manager
    ctx.event_bus = SimpleNamespace(publish=AsyncMock())
    adapter = make_adapter()
    adapter.access.set_policy(
        capability_type=IMCapability,
        permission="im.direct.receive",
        policy=ListAccessPolicy.from_lists(
            "allow_list",
            allow_list=[] if denied else [session.session_id],
        ),
    )
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    plugin = SessionPlugin(ctx, {})
    result = await plugin.session_send(SimpleNamespace(sid="source:dm:one"), "sess_one", "check performance")
    if denied:
        assert result == "Permission denied: target session is not allowed by adapter example"
        ctx.event_bus.publish.assert_not_awaited()
    else:
        assert result == "message sent"
        ctx.event_bus.publish.assert_awaited_once()
        event = ctx.event_bus.publish.await_args.args[0]
        assert event.session is session
        assert "source:dm:one" in event.message.chain[0].text
        assert "check performance" in event.message.chain[0].text


def test_im_route_requires_an_existing_adapter_and_im_session_type():
    adapter_mgr = SimpleNamespace(get_adapter=lambda name: object() if name == "real" else None)
    route = IMMessageRoute(
        delivery=Mock(),
        adapter_mgr=adapter_mgr,
        workflow=Mock(),
    )
    assert route.matches(Session("real", "dm", "user"))
    assert not route.matches(Session("missing", "dm", "user"))
    assert not route.matches(Session("real", "worker", "user"))


@pytest.mark.anyio
@pytest.mark.parametrize("batched", [False, True])
async def test_im_route_delivers_events_to_the_matching_workflow_entry(batched):
    adapter = make_adapter()
    workflow = SimpleNamespace(handle_event=AsyncMock(), handle_batch_event=AsyncMock())
    route = IMMessageRoute(
        delivery=Mock(),
        adapter_mgr=SimpleNamespace(get_adapter=lambda name: adapter),
        workflow=workflow,
    )
    session = _session()
    message = KiraIMMessage(
        message_id="input",
        self_id="bot",
        timestamp=1,
        sender=User(session.session_id),
        chain=MessageChain([Text("hello")]),
    )
    if batched:
        event = KiraMessageBatchEvent(
            adapter=adapter.info,
            supported_elements=["text"],
            timestamp=1,
            session=session,
            messages=[message],
        )
    else:
        event = KiraMessageEvent(
            adapter=adapter.info,
            supported_elements=["text"],
            timestamp=1,
            message=message,
        )
    await route.receive_message(session, event)
    expected = workflow.handle_batch_event if batched else workflow.handle_event
    unused = workflow.handle_event if batched else workflow.handle_batch_event
    expected.assert_awaited_once_with(event)
    assert expected.await_args.args[0] is event
    assert event.session is session
    unused.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("batched", [False, True])
async def test_event_bus_selects_receiver_using_persisted_session_context(session_db, batched):
    session = _session()
    row = await session_db.save_chat_session(
        session.sid,
        data={"kind": "worker"},
        content=[[{"role": "user", "content": "previous instruction"}]],
    )
    manager = SessionManager(session_db, {})
    workflow = SimpleNamespace(
        ctx=SimpleNamespace(session_manager=manager),
        message_processing_semaphore=asyncio.Semaphore(1),
        handle_event=AsyncMock(),
        handle_batch_event=AsyncMock(),
    )
    router = MessageRouter(session_manager=manager)
    router.register_route(
        IMMessageRoute(
            delivery=Mock(),
            adapter_mgr=SimpleNamespace(get_adapter=lambda name: make_adapter()),
            workflow=workflow,
        ),
        priority=-100,
    )
    worker = _route(lambda target: target.data.get("kind") == "worker")
    router.register_route(worker)
    message = KiraIMMessage(
        message_id="input",
        self_id="bot",
        timestamp=1,
        sender=User(session.session_id),
        chain=MessageChain([Text("new instruction")]),
    )
    adapter = make_adapter()
    if batched:
        event = KiraMessageBatchEvent(
            adapter=adapter.info,
            supported_elements=["text"],
            timestamp=1,
            session=session,
            messages=[message],
        )
    else:
        event = KiraMessageEvent(
            adapter=adapter.info,
            supported_elements=["text"],
            timestamp=1,
            message=message,
        )
    bus = EventBus(Mock(), asyncio.Queue())
    bus.subscribe(type(event), router.handle_event)
    await bus.publish(event)
    await bus._process_event(bus.event_queue.get_nowait())

    worker.receive_message.assert_awaited_once()
    target, received = worker.receive_message.await_args.args
    assert received is event and target is event.session
    assert target.internal_id == row["id"]
    assert target.content == row["content"]
    assert target.data == {"kind": "worker"}
    workflow.handle_event.assert_not_awaited()
    workflow.handle_batch_event.assert_not_awaited()
    assert bus.event_queue.empty()


@pytest.mark.anyio
async def test_publish_notice_uses_event_bus_without_a_message_router():
    adapter = make_adapter()
    bus = SimpleNamespace(publish=AsyncMock())
    session = Session(adapter.info.name, "dm", "user", internal_id="sess_input",
                      data={"routing": "custom"}, content=[[{"role": "user", "content": "history"}]])
    ctx = object.__new__(PluginContext)
    ctx.session_mgr = make_session_manager()
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = bus
    chain = MessageChain([Text("hello")])

    await ctx.publish_notice(session, chain, is_mentioned=False)

    bus.publish.assert_awaited_once()
    event = bus.publish.await_args.args[0]
    assert isinstance(event, KiraMessageEvent)
    assert event.session is session
    assert event.message.chain is chain
    assert event.is_notice and not event.is_mentioned
    assert event.message.message_id == "system_message"


@pytest.mark.anyio
@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
async def test_notice_event_bus_failure_or_cancellation_propagates(error):
    adapter = make_adapter()
    ctx = object.__new__(PluginContext)
    ctx.session_mgr = make_session_manager()
    ctx.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    ctx.event_bus = SimpleNamespace(publish=AsyncMock(side_effect=error("publish failed")))

    with pytest.raises(error, match="publish failed"):
        await ctx.publish_notice(_session(), MessageChain([Text("hello")]))
    ctx.event_bus.publish.assert_awaited_once()


@pytest.mark.anyio
async def test_internal_id_cannot_bypass_the_current_session_send_guard():
    session = _session(internal_id="sess_self")
    ctx = SimpleNamespace(
        session_mgr=SimpleNamespace(resolve_session=AsyncMock(return_value=session)),
        adapter_mgr=SimpleNamespace(get_adapter=Mock()),
        publish_notice=AsyncMock(),
    )
    result = await SessionPlugin(ctx, {}).session_send(SimpleNamespace(sid=session.sid), "sess_self", "hello")
    assert "current session" in result
    ctx.adapter_mgr.get_adapter.assert_not_called()
    ctx.publish_notice.assert_not_awaited()
