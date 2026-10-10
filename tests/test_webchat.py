import asyncio
import base64
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from core.adapter.adapter_info import AdapterInfo
from core.adapter.adapter_registry import AdapterManager
from core.adapter.builtin.webchat.webchat import WebChatAdapter
from core.adapter.capabilities import IMCapability
from core.adapter.context import AdapterContext
from core.chat.message_elements import Image, Text
from core.chat.message_utils import MessageChain
from core.webchat.service import WebChatService
from core.webchat.store import WebChatStore
from core.event_bus import EventBus
from tests.test_im_workflow import processor
from webui.routes.auth import require_auth
from webui.routes.webchat import WebChatRoutes

PROFILE = {"nickname": "Alice", "peer_nickname": "Kira", "description": "A quiet evening"}


class Sessions:
    def __init__(self):
        self.memory = None
        self.description = None

    def get_existing_memory_snapshot(self, sid):
        return self.memory

    def write_memory(self, sid, memory):
        self.memory = memory

    def update_session_info(self, sid, title, description):
        self.description = description


def make_adapter(store):
    return WebChatAdapter(AdapterContext(
        AdapterInfo(True, "builtin-webchat", WebChatAdapter.NAME, "webchat"), asyncio.Queue()), store)


@pytest.fixture
async def store(tmp_path):
    result = WebChatStore(tmp_path / "webchat")
    await result.initialize()
    return result


@pytest.mark.anyio
async def test_store_restart_preserves_profile_and_sent_messages(store):
    await store.set_setting("profile", PROFILE)
    request_id = str(uuid.uuid4())
    await store.accept(request_id, "hello", "Alice")
    second = WebChatStore(store.root)
    await second.initialize()
    assert await second.get_setting("profile") == PROFILE
    assert (await second.latest_request())["status"] == "sent"
    page = await second.list_messages()
    assert page["messages"][0]["chain"] == [{"type": "text", "text": "hello"}]
    duplicate, created = await second.accept(request_id, "hello", "Alice")
    assert not created and duplicate["status"] == "sent"
    with pytest.raises(ValueError, match="request_conflict"):
        await second.accept(request_id, "changed", "Alice")


@pytest.mark.anyio
async def test_concurrent_submissions_are_all_accepted_and_paginated(store):
    results = await asyncio.gather(*(store.accept(str(uuid.uuid4()), "hello", "Alice") for _ in range(5)), return_exceptions=True)
    assert all(result[0]["status"] == "sent" and result[1] for result in results)
    for index in range(5):
        await store.append_reply(MessageChain([Text(str(index))]), "Kira")
    page = await store.list_messages(limit=2)
    assert page["has_more"] and [m["seq"] for m in page["messages"]] == [9, 10]
    older = await store.list_messages(before=5, limit=2)
    assert [m["seq"] for m in older["messages"]] == [3, 4]
    newer = await store.list_messages(after=2, limit=2)
    assert newer["has_more"] and [m["seq"] for m in newer["messages"]] == [3, 4]


@pytest.mark.anyio
async def test_builtin_is_singleton_and_absent_from_catalog(store, monkeypatch):
    monkeypatch.setattr(AdapterManager, "scan_adapters", lambda *args: None)
    manager = AdapterManager({}, asyncio.Queue())
    adapter = make_adapter(store)
    before = manager.get_adapter_types()
    await manager.register_builtin_adapter(adapter)
    try:
        assert manager.get_adapter(WebChatAdapter.NAME) is adapter
        assert manager.get_adapter_types() == before
        assert manager.get_adapters_info() == []
        assert not manager._check_name_unique(WebChatAdapter.NAME)
        with pytest.raises(ValueError, match="already in use"):
            await manager.register_builtin_adapter(make_adapter(store))
        with pytest.raises(ValueError, match="application-owned"):
            await manager.register_adapter(adapter.info)
    finally:
        await manager.stop_adapters()
    assert not manager.get_adapters()
    assert not manager._adapter_tasks


@pytest.mark.anyio
async def test_routes_require_auth_validate_input_and_gate_setup(store):
    service = WebChatService(make_adapter(store), Sessions())
    app = FastAPI()
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        for method, path in [("GET", ""), ("PUT", "/profile"), ("GET", "/messages"), ("POST", "/messages"), ("GET", "/messages/id/media?element_path=0")]:
            assert (await client.request(method, "/api/webchat" + path, json=PROFILE)).status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        assert (await client.get("/api/webchat")).json()["profile"] is None
        payload = {"request_id": str(uuid.uuid4()), "text": "hello"}
        assert (await client.post("/api/webchat/messages", json=payload)).json()["detail"] == "setup_required"
        assert (await client.put("/api/webchat/profile", json={**PROFILE, "nickname": "  "})).status_code == 422
        assert (await client.put("/api/webchat/profile", json=PROFILE)).status_code == 200
        assert (await client.post("/api/webchat/messages", json=payload)).json()["status"] == "sent"
        assert (await client.post("/api/webchat/messages", json={**payload, "text": " "})).status_code == 422
        assert (await client.get("/api/webchat/messages?after=-1")).status_code == 422
        assert (await client.get("/api/webchat/messages?after=1&before=2")).status_code == 400
    assert len((await store.list_messages())["messages"]) == 1


@pytest.mark.anyio
async def test_media_has_independent_copy_and_cannot_read_arbitrary_paths(store, tmp_path):
    content = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jT1sAAAAASUVORK5CYII=")
    source = tmp_path / "original.png"
    source.write_bytes(content)
    message_id = await store.append_reply(MessageChain([Image(str(source))]), "Kira")
    source.unlink()
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    WebChatRoutes(app, SimpleNamespace(webchat=SimpleNamespace(store=store))).register()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.get(f"/api/webchat/messages/{message_id}/media?element_path=0")
        assert response.status_code == 200 and response.content == content
        assert response.headers["content-type"] == "image/png"
        assert (await client.get(f"/api/webchat/messages/{message_id}/media?element_path=../0")).status_code == 400
        assert (await client.get("/api/webchat/messages/unknown/media?element_path=0")).status_code == 404

@pytest.mark.anyio
async def test_service_publishes_once_without_reply_lock_or_model_gate(store):
    adapter = make_adapter(store)
    service = WebChatService(adapter, Sessions())
    await service.save_profile(PROFILE)
    request_id = str(uuid.uuid4())
    await service.submit(request_id, "hello")
    await service.submit(request_id, "hello")
    await service.submit(str(uuid.uuid4()), "another message")
    first = adapter.ctx.event_queue.get_nowait()
    second = adapter.ctx.event_queue.get_nowait()
    assert adapter.ctx.event_queue.empty()
    assert first.session.sid == "webchat:dm:admin"
    assert first.message.sender.nickname == "Alice"
    assert first.process_strategy == "discard" and not first._is_forced
    assert second.message.chain[0].text == "another message"
    assert first.buffer() and first.discard() and first.trigger()
    await service.save_profile({**PROFILE, "description": "Updated"})
    await service.stop()
    with pytest.raises(ValueError, match="unavailable"):
        await service.submit(str(uuid.uuid4()), "closed")


@pytest.mark.anyio
@pytest.mark.parametrize("description", ["", "A quiet evening"])
async def test_profile_keeps_description_verbatim_and_context_in_session_manager(store, description):
    profile = {**PROFILE, "description": description}
    await store.set_setting("profile", profile)
    sessions = Sessions()
    sessions.memory = [[{"role": "user", "content": "session context"}]]
    sessions.get_existing_memory_snapshot = Mock(side_effect=AssertionError("WebChat must not read context"))
    sessions.write_memory = Mock(side_effect=AssertionError("WebChat must not restore context"))
    service = WebChatService(make_adapter(store), sessions)
    await service.initialize()
    assert sessions.description == description
    await service.save_profile(profile)
    await service.submit(str(uuid.uuid4()), "hello")
    assert sessions.description == description
    assert await store.get_setting("memory") is None
    sessions.memory = []
    await service.stop()
    restarted = WebChatService(make_adapter(store), sessions)
    await restarted.initialize()
    assert sessions.memory == []
    assert await store.get_setting("memory") is None
    sessions.get_existing_memory_snapshot.assert_not_called()
    sessions.write_memory.assert_not_called()

@pytest.mark.anyio
async def test_normal_event_bus_buffers_batches_counts_and_delivers_webchat(store, processor, monkeypatch):
    from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent
    from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin
    from core.plugin.handlers import EventType, event_handler_reg
    from core.workflow.src.im.batching import publish_buffered_messages
    from core.workflow.src.im.message_delivery import MessageDeliveryService
    from core.provider import LLMResponse

    adapter = make_adapter(store)
    telemetry = SimpleNamespace(add_telemetry_message=AsyncMock())
    bus = EventBus(SimpleNamespace(set_stats=Mock()), adapter.ctx.event_queue, db=telemetry)
    instance, model = processor
    workflow = instance.im_workflow
    services = workflow.ctx
    services.event_bus = bus
    services.session_manager.get_session_info = lambda sid: SimpleNamespace(session_title="Chat", session_description="Description")
    services.session_manager.get_existing_memory_snapshot = lambda sid: []
    services.session_manager.update_session_info = Mock()
    services.message_delivery.adapter_mgr = SimpleNamespace(get_adapter=lambda name: adapter)
    services.message_delivery.message_history = None
    services.message_delivery.send_message_chain = MessageDeliveryService.send_message_chain.__get__(services.message_delivery)
    plugin = DefaultChatPlugin(SimpleNamespace(
        config={"bot_config": {"bot": {"max_message_interval": 3600, "max_buffer_messages": 2}}},
        get_buffer=services.message_buffer.get_buffer,
        flush_session_messages=lambda sid: publish_buffered_messages(services.message_buffer, bus, sid),
    ), {})
    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: [SimpleNamespace(exec_handler=plugin.handle_msg)] if event_type == EventType.ON_IM_MESSAGE else [])
    received = asyncio.Event()
    started = asyncio.Event()
    release = asyncio.Event()
    completed = asyncio.Event()
    received_events = []

    async def receive(event):
        await workflow.handle_event(event)
        received_events.append(event)
        received.set()

    async def process_batch(event):
        await workflow.handle_batch_event(event)
        completed.set()

    async def chat(request):
        started.set()
        await release.wait()
        return LLMResponse("<msg><text>reply</text></msg>")

    model.chat.side_effect = chat
    bus.subscribe(KiraMessageEvent, receive)
    bus.subscribe(KiraMessageBatchEvent, process_batch)
    service = WebChatService(adapter, services.session_manager)
    await service.initialize()
    await service.save_profile(PROFILE)
    dispatcher = asyncio.create_task(bus.dispatch())
    try:
        await service.submit(str(uuid.uuid4()), "first")
        await asyncio.wait_for(received.wait(), 2)
        assert services.message_buffer.get_buffer(adapter.SID).get_length() == 1
        model.chat.assert_not_awaited()
        received.clear()
        await service.submit(str(uuid.uuid4()), "second")
        await asyncio.wait_for(started.wait(), 2)
        received.clear()
        await service.submit(str(uuid.uuid4()), "third while replying")
        await asyncio.wait_for(received.wait(), 2)
        assert services.message_buffer.get_buffer(adapter.SID).get_length() == 1
        assert bus.total_messages_stats["total_messages"] == 3
        assert telemetry.add_telemetry_message.await_count == 3
        assert all(call.args[1] == "webchat" for call in telemetry.add_telemetry_message.await_args_list)
        release.set()
        await asyncio.wait_for(completed.wait(), 2)
        model.chat.assert_awaited_once()
        rows = (await store.list_messages())["messages"]
        assert len(rows) == 4 and rows[-1]["direction"] == "outgoing"
        assert all(not event._is_forced for event in received_events)
    finally:
        release.set()
        await plugin.terminate()
        await service.stop()
        await bus.stop()
        dispatcher.cancel()
        await asyncio.gather(dispatcher, return_exceptions=True)

@pytest.mark.anyio
@pytest.mark.parametrize("action", ["discard", "stop"])
async def test_plugin_can_suppress_webchat_reply(store, processor, monkeypatch, action):
    from core.chat.message_utils import KiraMessageEvent
    from core.plugin.handlers import EventType, event_handler_reg

    adapter = make_adapter(store)
    bus = EventBus(SimpleNamespace(set_stats=Mock()), adapter.ctx.event_queue)
    instance, model = processor
    workflow = instance.im_workflow
    workflow.ctx.event_bus = bus
    workflow.ctx.session_manager.get_session_info = lambda sid: SimpleNamespace(session_description="Description")

    async def suppress(event):
        getattr(event, action)()

    monkeypatch.setattr(event_handler_reg, "get_handlers", lambda event_type: [SimpleNamespace(exec_handler=suppress)] if event_type == EventType.ON_IM_MESSAGE else [])
    bus.subscribe(KiraMessageEvent, workflow.handle_event)
    service = WebChatService(adapter, Sessions())
    await service.save_profile(PROFILE)
    await service.submit(str(uuid.uuid4()), "hello")
    await bus._process_event(adapter.ctx.event_queue.get_nowait())
    assert adapter.ctx.event_queue.empty()
    model.chat.assert_not_awaited()
    assert (await store.latest_request())["status"] == "sent"
    await service.submit(str(uuid.uuid4()), "still allowed")
    assert adapter.ctx.event_queue.qsize() == 1
    await service.stop()


@pytest.mark.anyio
async def test_upload_archives_media_and_publishes_once_through_normal_adapter(store):
    from core.chat.message_elements import File

    adapter = make_adapter(store)
    service = WebChatService(adapter, Sessions())
    await service.save_profile(PROFILE)
    app = FastAPI()
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    request_id = str(uuid.uuid4())
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jT1sAAAAASUVORK5CYII=")
    data = {"request_id": request_id, "text": "See attachments", "kinds": ["image", "file"]}
    uploads = [("files", ("photo.png", png, "image/png")), ("files", ("../hello.txt", b"hello", "text/plain"))]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.post("/api/webchat/messages/upload", data=data, files=uploads)).status_code == 401
        app.dependency_overrides[require_auth] = lambda: "admin"
        first = await client.post("/api/webchat/messages/upload", data=data, files=uploads)
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "sent"
        repeated = await client.post("/api/webchat/messages/upload", data=data, files=uploads)
        assert repeated.json() == first.json()
        different = [uploads[0], ("files", ("hello.txt", b"changed", "text/plain"))]
        assert (await client.post("/api/webchat/messages/upload", data=data, files=different)).status_code == 409
        assert (await client.post("/api/webchat/messages", json={"request_id": request_id, "text": data["text"]})).status_code == 409
        for index, content in [(1, png), (2, b"hello")]:
            download = await client.get(f"/api/webchat/messages/{request_id}/media?element_path={index}")
            assert download.status_code == 200 and download.content == content
        image_only = await client.post("/api/webchat/messages/upload", data={"request_id": str(uuid.uuid4()), "kinds": "image"}, files=[uploads[0]])
        assert image_only.status_code == 200, image_only.text
    event = adapter.ctx.event_queue.get_nowait()
    assert not event._is_forced and event.process_strategy == "discard"
    assert [type(element) for element in event.message.chain] == [Text, Image, File]
    assert event.message.chain[2].name == "hello.txt"
    for element, content in [(event.message.chain[1], png), (event.message.chain[2], b"hello")]:
        assert element.file_type == "data_url"
        assert base64.b64decode(await element.to_base64()) == content
        assert element.size == len(content)
    assert [type(element) for element in adapter.ctx.event_queue.get_nowait().message.chain] == [Image]
    assert adapter.ctx.event_queue.empty()
    restarted = WebChatStore(store.root)
    await restarted.initialize()
    history = (await restarted.list_messages())["messages"]
    assert len(history) == 2
    assert [element["type"] for element in history[0]["chain"]] == ["text", "image", "file"]
    assert all(element["file_type"] == "archive" for element in history[0]["chain"][1:])


@pytest.mark.anyio
async def test_upload_validates_profile_attachment_type_count_and_total_size(store, monkeypatch):
    import webui.routes.webchat as routes

    adapter = make_adapter(store)
    service = WebChatService(adapter, Sessions())
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    data = {"request_id": str(uuid.uuid4()), "kinds": "file"}
    uploads = [("files", ("hello.txt", b"hello", "text/plain"))]
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post("/api/webchat/messages/upload", data=data, files=uploads)
        assert response.status_code == 409 and response.json()["detail"] == "setup_required"
        await service.save_profile(PROFILE)
        invalid_image = await client.post("/api/webchat/messages/upload", data={**data, "kinds": "image"}, files=uploads)
        assert invalid_image.status_code == 400 and invalid_image.json()["detail"] == "invalid_image"
        assert (await client.post("/api/webchat/messages/upload", data={**data, "kinds": "other"}, files=uploads)).status_code == 422
        mismatch = await client.post("/api/webchat/messages/upload", data=data, files=uploads * 2)
        assert mismatch.status_code == 400 and mismatch.json()["detail"] == "attachment_count"
        too_many = await client.post("/api/webchat/messages/upload", data={**data, "kinds": ["file"] * 11}, files=uploads * 11)
        assert too_many.status_code == 400 and too_many.json()["detail"] == "attachment_count"
        monkeypatch.setattr(routes, "MAX_ATTACHMENT_BYTES", 8)
        oversized = await client.post("/api/webchat/messages/upload", data={**data, "kinds": ["file"] * 2}, files=uploads * 2)
        assert oversized.status_code == 413 and oversized.json()["detail"] == "attachments_too_large"
    assert adapter.ctx.event_queue.empty()
    assert not (await store.list_messages())["messages"]


@pytest.mark.anyio
async def test_failed_attachment_archive_does_not_publish_or_persist_message(store, monkeypatch):
    import core.webchat.service as service_module

    adapter = make_adapter(store)
    service = WebChatService(adapter, Sessions())
    await service.save_profile(PROFILE)
    monkeypatch.setattr(service_module, "serialize_message_chain", AsyncMock(return_value=[{"type": "image", "file_type": "unavailable"}]))
    with pytest.raises(ValueError, match="attachment_failed"):
        await service.submit(str(uuid.uuid4()), "", [Image("data:image/png;base64,aGVsbG8=")])
    assert adapter.ctx.event_queue.empty()
    assert not (await store.list_messages())["messages"]

@pytest.mark.anyio
@pytest.mark.parametrize("direction", ["incoming", "outgoing"])
async def test_webchat_persists_quote_content_when_sending(store, direction):
    import json
    import aiosqlite
    from core.chat.message_elements import Reply
    from core.adapter.builtin.webchat.im import WebChatIMCapability

    await store.set_setting("profile", PROFILE)
    if direction == "incoming":
        original_id = str(uuid.uuid4())
        await store.accept(original_id, "Original message", "Alice")
    else:
        original_id = await store.append_reply(MessageChain([Text("Original message")]), "Kira")
    adapter = make_adapter(store)
    result = await adapter.get_capability(WebChatIMCapability).send_direct_message(
        "admin", MessageChain([Reply(original_id), Text("Reply text")]),
    )
    restarted = WebChatStore(store.root)
    await restarted.initialize()
    page = await restarted.list_messages(limit=1)
    assert page["has_more"] and len(page["messages"]) == 1
    reply = page["messages"][0]
    assert reply["id"] == result.message_id
    assert reply["chain"][0]["chain"] == [{"type": "text", "text": "Original message"}]
    assert reply["chain"][1] == {"type": "text", "text": "Reply text"}
    assert (await restarted.get_message(result.message_id))["chain"] == reply["chain"]
    assert (await restarted.list_messages(after=1))["messages"][0]["chain"] == reply["chain"]
    async with aiosqlite.connect(store.path) as db:
        async with db.execute("SELECT body FROM messages WHERE id = ?", (result.message_id,)) as cursor:
            persisted = json.loads((await cursor.fetchone())[0])
    assert persisted["chain"] == reply["chain"]


@pytest.mark.anyio
async def test_quoted_images_are_available_through_existing_media_route(store, tmp_path):
    from core.chat.message_elements import Reply

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jT1sAAAAASUVORK5CYII=")
    source = tmp_path / "quoted.png"
    source.write_bytes(png)
    original_id = await store.append_reply(MessageChain([Text("Picture"), Image(str(source))]), "Kira")
    reply_id = await store.append_reply(MessageChain([Reply(original_id), Text("See this")]), "Kira")
    source.unlink()
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    WebChatRoutes(app, SimpleNamespace(webchat=SimpleNamespace(store=store))).register()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        messages = (await client.get("/api/webchat/messages?after=1")).json()["messages"]
        assert messages[0]["chain"][0]["chain"][1]["type"] == "image"
        response = await client.get(f"/api/webchat/messages/{reply_id}/media?element_path=0.1")
        assert response.status_code == 200 and response.content == png
        assert response.headers["content-type"] == "image/png"


@pytest.mark.anyio
async def test_new_quotes_preserve_supplied_content_and_limit_nested_snapshots(store):
    from core.chat.message_elements import Reply

    await store.accept("a", "", "Alice", [{"type": "reply", "message_id": "b"}, {"type": "text", "text": "A"}])
    await store.accept("b", "", "Alice", [{"type": "reply", "message_id": "a"}, {"type": "text", "text": "B"}])
    quote_id = await store.append_reply(MessageChain([
        Reply("a", "Supplied text"), Reply("a", chain=MessageChain([Text("Supplied chain")])),
        Reply("missing"), Reply("a"),
    ]), "Kira")
    quote = (await store.get_message(quote_id))["chain"]
    assert quote[0]["message_content"] == "Supplied text" and "chain" not in quote[0]
    assert quote[1]["chain"] == [{"type": "text", "text": "Supplied chain"}]
    assert quote[2]["message_id"] == "missing" and "chain" not in quote[2]
    assert quote[3]["chain"][1]["text"] == "A"
    assert quote[3]["chain"][0]["message_id"] == "b"
    assert "chain" not in quote[3]["chain"][0]
    previous = "a"
    for _ in range(5):
        previous = await store.append_reply(MessageChain([Reply(previous)]), "Kira")
    chain = (await store.get_message(previous))["chain"]
    for _ in range(3):
        chain = chain[0]["chain"]
    assert "chain" not in chain[0]


@pytest.mark.anyio
async def test_reading_id_only_quotes_does_not_fill_or_rewrite_them(store):
    await store.accept("original", "Original text", "Alice")
    stored_chain = [{"type": "reply", "message_id": "original"}, {"type": "text", "text": "Old reply"}]
    await store.accept("old-reply", "Old reply", "Alice", stored_chain)
    assert (await store.get_message("old-reply"))["chain"] == stored_chain
    assert (await store.list_messages(limit=1))["messages"][0]["chain"] == stored_chain


@pytest.mark.anyio
async def test_delete_history_removes_only_webchat_messages_and_media(store, tmp_path):
    sessions = Sessions()
    sessions.memory = [[{"role": "user", "content": "Keep context"}]]
    service = WebChatService(make_adapter(store), sessions)
    await service.save_profile(PROFILE)
    await service.submit(str(uuid.uuid4()), "Incoming")
    source = tmp_path / "source.png"
    source.write_bytes(base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jT1sAAAAASUVORK5CYII="))
    reply_id = await store.append_reply(MessageChain([Image(str(source))]), "Kira")
    old_seq = (await store.list_messages())["messages"][-1]["seq"]
    assert any(store.media_dir.iterdir())
    app = FastAPI()
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        assert (await client.delete("/api/webchat/messages")).status_code == 401
        assert (await store.list_messages())["messages"]
        app.dependency_overrides[require_auth] = lambda: "admin"
        assert (await client.delete("/api/webchat/messages")).status_code == 200
        assert (await client.get("/api/webchat/messages")).json() == {"messages": [], "has_more": False}
        assert (await client.get(f"/api/webchat/messages/{reply_id}/media?element_path=0")).status_code == 404
        assert (await client.delete("/api/webchat/messages")).status_code == 200
    assert not store.media_dir.exists()
    assert source.is_file()
    assert sessions.memory == [[{"role": "user", "content": "Keep context"}]]
    assert sessions.description == PROFILE["description"]
    restarted = WebChatStore(store.root)
    await restarted.initialize()
    assert await restarted.get_setting("profile") == PROFILE
    assert await restarted.latest_request() is None
    assert (await restarted.list_messages())["messages"] == []
    await service.submit(str(uuid.uuid4()), "New message")
    await store.append_reply(MessageChain([Image(str(source))]), "Kira")
    new_messages = (await restarted.list_messages(after=old_seq))["messages"]
    assert len(new_messages) == 2
    assert (store.media_dir / new_messages[-1]["chain"][0]["file"]).is_file()


@pytest.mark.anyio
async def test_delete_history_waits_for_reply_media_to_be_persisted(store, monkeypatch):
    import core.webchat.store as store_module

    entered = asyncio.Event()
    release = asyncio.Event()
    serialize = store_module.serialize_message_chain

    async def delayed_serialize(*args, **kwargs):
        result = await serialize(*args, **kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(store_module, "serialize_message_chain", delayed_serialize)
    reply = asyncio.create_task(store.append_reply(MessageChain([Image("data:image/png;base64,aGVsbG8=")]), "Kira"))
    deletion = None
    try:
        await asyncio.wait_for(entered.wait(), 2)
        deletion = asyncio.create_task(store.clear_messages())
        await asyncio.sleep(0)
        assert not deletion.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(reply, deletion), 2)
        assert (await store.list_messages())["messages"] == []
        assert not store.media_dir.exists()
    finally:
        release.set()
        await asyncio.gather(reply, *([deletion] if deletion else []), return_exceptions=True)


@pytest.mark.anyio
async def test_delete_history_reports_media_failure_without_removing_messages(store, monkeypatch):
    import core.webchat.store as store_module

    service = WebChatService(make_adapter(store), Sessions())
    await service.save_profile(PROFILE)
    await service.submit(str(uuid.uuid4()), "Keep if deletion fails")
    store.media_dir.mkdir()
    monkeypatch.setattr(store_module.shutil, "rmtree", Mock(side_effect=PermissionError("locked")))
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.delete("/api/webchat/messages")
        assert response.status_code == 500 and response.json()["detail"] == "delete_failed"
    assert len((await store.list_messages())["messages"]) == 1
    assert await store.latest_request() is not None


@pytest.mark.anyio
@pytest.mark.parametrize("clear_before_processing", [False, True])
async def test_uploaded_file_is_readable_through_normal_pipeline_after_history_deletion(
    store, tmp_path, monkeypatch, clear_before_processing,
):
    from pathlib import Path
    from core.plugin.builtin_plugins.agent.main import AgentPlugin
    from core.utils import path_utils
    from core.workflow.src.im.message_formatter import MessageFormatter

    data_root = tmp_path / "data"
    monkeypatch.setattr(path_utils, "_data_dir", data_root)
    adapter = make_adapter(store)
    service = WebChatService(adapter, Sessions())
    await service.save_profile(PROFILE)
    app = FastAPI()
    app.dependency_overrides[require_auth] = lambda: "admin"
    WebChatRoutes(app, SimpleNamespace(webchat=service)).register()
    content = "A file sent through WebChat."
    request_id = str(uuid.uuid4())
    async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
        response = await client.post(
            "/api/webchat/messages/upload",
            data={"request_id": request_id, "text": "Read this file", "kinds": "file"},
            files=[("files", ("1.txt", content.encode(), "text/plain"))],
        )
        assert response.status_code == 200, response.text
        download = await client.get(f"/api/webchat/messages/{request_id}/media?element_path=1")
        assert download.status_code == 200 and download.content == content.encode()
        assert 'filename="1.txt"' in download.headers["content-disposition"]

    event = adapter.ctx.event_queue.get_nowait()
    assert adapter.ctx.event_queue.empty()
    if clear_before_processing:
        await service.clear_messages()

    formatter = MessageFormatter(SimpleNamespace(get_config=lambda key, default=None: default))
    formatted = await formatter.format_to_text(event.message.chain, adapter.SID)
    assert "file_path: data/temp/" in formatted.replace("\\", "/")
    attachment = event.message.chain[1]
    path = Path(await attachment.to_path())
    assert path.parent == data_root / "temp" and path.name == "1.txt"
    assert path.read_text() == content
    assert await attachment.to_path() == str(path)

    plugin = AgentPlugin(None, {"file_access": {
        "permission_mode": "allow_list", "session_list": [adapter.SID],
    }})
    await plugin.initialize()
    assert await plugin.read_file(SimpleNamespace(sid=adapter.SID), "data/temp/1.txt") == content
    denied = await plugin.read_file(SimpleNamespace(sid="other:dm:user"), "data/temp/1.txt")
    assert denied.startswith("Permission denied")

    if not clear_before_processing:
        await service.clear_messages()
    assert (await store.list_messages())["messages"] == []
    assert not store.media_dir.exists()
    assert await plugin.read_file(SimpleNamespace(sid=adapter.SID), "data/temp/1.txt") == content


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("configured_name", ["webchat", None, "renamed"])
async def test_startup_preserves_configured_adapter_and_disables_conflicting_webchat(
    tmp_path, monkeypatch, enabled, configured_name,
):
    import copy
    from unittest.mock import MagicMock
    import core.lifecycle as lifecycle_module
    from core.utils import path_utils

    class Config(dict):
        def get_config(self, key, default=None):
            return default

    class ConfiguredAdapter:
        def __init__(self, ctx):
            self.info = ctx.info
            self.stopped = asyncio.Event()

        async def start(self):
            await self.stopped.wait()

        async def stop(self):
            self.stopped.set()

    config = Config({"adapters": {"webchat": {
        "enabled": enabled, "name": configured_name, "platform": "test-configured", "config": {},
    }}})
    original = copy.deepcopy(config)
    monkeypatch.setattr(path_utils, "_data_dir", tmp_path)
    monkeypatch.setattr(lifecycle_module, "KiraConfig", lambda: config)
    monkeypatch.setattr(lifecycle_module, "setup_logging", Mock())
    monkeypatch.setattr(lifecycle_module, "run_migrations", AsyncMock())
    monkeypatch.setattr(lifecycle_module, "migrate_selfie_reference_image", AsyncMock())
    monkeypatch.setattr(lifecycle_module.event_handler_reg, "get_handlers", lambda _: [])
    monkeypatch.setattr(AdapterManager, "scan_adapters", lambda *args: None)
    monkeypatch.setitem(AdapterManager._registry, "test-configured", ConfiguredAdapter)
    for name in (
        "DatabaseManager", "DatabaseService", "TelemetryClient", "ProviderManager",
        "FuncToolManager", "EventBus", "SessionMediaManager", "PersonaManager",
        "StickerManager", "PromptManager", "MCPManager", "SkillsManager",
        "MessageHistoryService", "ImageDescCache", "MessageHistoryCleanup",
        "DefaultIMWorkflow", "MessageProcessor", "PluginContext", "PluginManager", "AsyncTempMonitor",
    ):
        component = MagicMock()
        for method in ("init", "initialize", "init_tables", "init_persona", "init_mcp",
                       "cleanup_task", "start_monitoring", "dispatch"):
            setattr(component, method, AsyncMock())
        monkeypatch.setattr(lifecycle_module, name, Mock(return_value=component))
    sessions = Sessions()
    monkeypatch.setattr(lifecycle_module, "SessionManager", Mock(return_value=sessions))
    service_factory = Mock(wraps=WebChatService)
    monkeypatch.setattr(lifecycle_module, "WebChatService", service_factory)
    warning = Mock()
    monkeypatch.setattr(lifecycle_module.logger, "warning", warning)

    store = WebChatStore(tmp_path / "webchat")
    await store.initialize()
    await store.set_setting("profile", PROFILE)
    await store.accept("saved-message", "Keep history", "Alice")
    lifecycle = lifecycle_module.KiraLifecycle(Mock())
    conflict = configured_name != "renamed"
    try:
        await lifecycle.init_and_run_system()
        assert config == original
        lifecycle.plugin_manager.init.assert_awaited_once()
        lifecycle.event_bus.dispatch.assert_awaited_once()
        if enabled:
            adapter = lifecycle.adapter_manager.get_adapter(configured_name or "webchat")
            assert isinstance(adapter, ConfiguredAdapter) and adapter.info.adapter_id == "webchat"
        if conflict:
            assert lifecycle.webchat is None
            service_factory.assert_not_called()
            warning.assert_called_once()
            assert "Rename" in warning.call_args.args[0] and "restart" in warning.call_args.args[0]
            assert sessions.description is None
            assert "webchat" not in lifecycle.adapter_manager._builtin_names
        else:
            assert lifecycle.webchat is not None
            assert isinstance(lifecycle.adapter_manager.get_adapter("webchat"), WebChatAdapter)
            assert sessions.description == PROFILE["description"]
            warning.assert_not_called()
        app = FastAPI()
        app.dependency_overrides[require_auth] = lambda: "admin"
        WebChatRoutes(app, lifecycle).register()
        async with AsyncClient(transport=ASGITransport(app), base_url="http://test") as client:
            response = await client.get("/api/webchat")
            assert response.status_code == (503 if conflict else 200)
        assert await store.get_setting("profile") == PROFILE
        assert len((await store.list_messages())["messages"]) == 1
    finally:
        if lifecycle.adapter_manager is not None:
            await lifecycle.adapter_manager.stop_adapters()
        for task in lifecycle.tasks:
            task.cancel()
        await asyncio.gather(*lifecycle.tasks, return_exceptions=True)
