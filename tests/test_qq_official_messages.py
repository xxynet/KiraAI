import asyncio
import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from botpy.connection import ConnectionState

from core.adapter.src.qq_official import im as im_module
from core.adapter.src.qq_official.message_parser import QQOfficialMessageParser
from core.chat import MessageChain
from core.chat.message_elements import At, File, Image, Record, Reply, Text
from tests.adapter_lifecycle import start_adapter
from tests.test_qq_official_adapter import make_adapter, sdk_gateway, cleanup_sdk_gateway


def message(group=True, message_id="incoming", **updates):
    body = {
        "id": message_id,
        "content": "hello",
        "author": {"member_openid" if group else "user_openid": "user-openid", "username": "Alice"},
        "attachments": [],
    }
    if group:
        body["group_openid"] = "group-openid"
    body.update(updates)
    return body


def attach_api(adapter, send):
    adapter.client = SimpleNamespace(api=SimpleNamespace(post_group_message=send, post_c2c_message=send))
    adapter._client_task = SimpleNamespace(done=lambda: False)


@pytest.mark.asyncio
@pytest.mark.parametrize("event_name", ["group_message_create", "group_at_message_create", "c2c_message_create"])
async def test_real_sdk_parser_preserves_nickname_quote_and_scene(sdk_gateway, event_name):
    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        await asyncio.wait_for(sdk_gateway.opened.get(), 2)
        group = event_name != "c2c_message_create"
        body = message(group, content="my reply", message_type=103,
                       msg_elements=[{"content": "quoted", "attachments": []}],
                       message_scene={"ext": ["msg_idx=REFIDX_incoming=="]})
        adapter.client._connection.parser[event_name]({"d": body})
        await asyncio.sleep(0)
        event = adapter.ctx.event_queue.get_nowait()
        assert event.message.sender.nickname == "Alice"
        assert event.message.is_mentioned == (event_name != "group_message_create")
        assert isinstance(event.message.chain.message_list[0], Reply)
        assert event.message.chain.message_list[0].chain.message_list[0].text == "quoted"
        target_id = "group-openid" if group else "user-openid"
        assert adapter.im._message_references[(group, target_id, "incoming")] == "REFIDX_incoming=="
        assert not hasattr(ConnectionState, "parse_group_message_create")
        adapter.client._connection.parser[event_name]({"d": None})
        await asyncio.sleep(0)
        assert adapter.ctx.event_queue.empty()
        client = adapter.client
        await adapter.stop()
        client._connection.parser[event_name]({"d": message(group, "after-stop")})
        await asyncio.sleep(0)
        assert adapter.ctx.event_queue.empty()
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
async def test_full_message_parsers_are_isolated_between_instances(sdk_gateway):
    first = make_adapter()
    second = make_adapter()
    try:
        for adapter in (first, second):
            await start_adapter(adapter)
            await asyncio.wait_for(sdk_gateway.opened.get(), 2)
        await first.stop()
        second.client._connection.parser["group_message_create"]({"d": message()})
        await asyncio.sleep(0)
        assert first.ctx.event_queue.empty()
        assert second.ctx.event_queue.qsize() == 1
    finally:
        await first.stop()
        await second.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_denied_raw_messages_cannot_change_identity_or_reply_state(group):
    adapter = make_adapter(**{"group_allow_list" if group else "user_allow_list": []})
    await adapter.im._handle_message(message(group, mentions=[{"id": "self", "is_you": True}]), group, True)
    assert adapter.ctx.event_queue.empty()
    assert not adapter.im._received_messages
    assert not adapter.im._reply_received_at
    assert not adapter.im._parser._names
    assert not adapter.im._parser._self_ids


@pytest.mark.asyncio
async def test_full_messages_use_trusted_identity_and_preserve_at_ids():
    adapter = make_adapter(permission_mode="deny_list")
    bodies = [
        message(message_id="plain", content="hello"),
        message(message_id="other", content="<@other> hi", mentions=[{"id": "other", "username": "Alice"}]),
        message(message_id="unknown", content="<@unknown> hi"),
        message(message_id="self", content="<@self> hi", mentions=[{"id": "self", "is_you": True, "username": "Bot"}]),
        message(message_id="known-self", content='<qqbot-at-user id="self" /> hi'),
        message(message_id="spoof", content="<@other> hi", mentions=[{"id": "other", "bot": True, "username": "Bot"}]),
        message(message_id="other-group", group_openid="another-group", content="<@self> hi"),
    ]
    for body in bodies:
        await adapter.im._handle_group_message(body, force_mention=False)
    events = [adapter.ctx.event_queue.get_nowait() for _ in bodies]
    assert [event.is_mentioned for event in events] == [False, False, False, True, True, False, False]
    mention = events[1].message.chain.message_list[0]
    assert isinstance(mention, At)
    assert mention.pid == "other" and mention.nickname == "Alice"
    assert not adapter.im._parser._self_ids.get((True, "another-group"))


@pytest.mark.asyncio
async def test_only_quoting_self_wakes_not_historical_at():
    adapter = make_adapter()
    adapter.client = SimpleNamespace(robot=SimpleNamespace(id="self"))
    for index, author_id in enumerate(("other", "self")):
        body = message(message_id=str(index), message_type=103, content="reply",
                       msg_elements=[{"author": {"id": author_id}, "content": "<@self> old", "mentions": [{"id": "self"}]}])
        await adapter.im._handle_group_message(body, force_mention=False)
        event = adapter.ctx.event_queue.get_nowait()
        assert event.is_mentioned == (author_id == "self")
        assert isinstance(event.message.chain.message_list[0].chain.message_list[0], At)


@pytest.mark.asyncio
async def test_nicknames_follow_renames_and_missing_values_without_changing_id():
    adapter = make_adapter()
    for index, name in enumerate(("Alice", "Bob", None)):
        body = message(False, str(index), author={"user_openid": "user-openid", "username": name})
        await adapter.im._handle_direct_message(body)
        sender = adapter.ctx.event_queue.get_nowait().message.sender
        assert sender.user_id == "user-openid"
        assert sender.nickname == ("Alice" if index == 0 else "Bob")


@pytest.mark.asyncio
async def test_dedup_across_events_preserves_sequence_and_allows_distinct_msg_seq():
    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent"})
    attach_api(adapter, send)
    body = message(mentions=[{"id": "self", "is_you": True}], msg_seq=1)
    await adapter.im._handle_group_message(body, force_mention=False)
    await adapter.send_group_message("group-openid", MessageChain([Text("first")]))
    await adapter.im._handle_group_message(body)
    await adapter.send_group_message("group-openid", MessageChain([Text("second")]))
    assert adapter.ctx.event_queue.qsize() == 1
    assert [call.kwargs["msg_seq"] for call in send.await_args_list] == [1, 2]
    await adapter.im._handle_group_message(dict(body, msg_seq=2))
    assert adapter.ctx.event_queue.qsize() == 2
    assert adapter.im._reply_msg_seqs[(True, "group-openid", "incoming")] == 2


def test_dedup_cache_ttl_scope_and_capacity(monkeypatch):
    adapter = make_adapter()
    now = [10.0]
    monkeypatch.setattr(im_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_RECEIVED_MESSAGES", 2)
    assert adapter.im._accept_message(message(), True, "one")
    assert not adapter.im._accept_message(message(), True, "one")
    assert adapter.im._accept_message(message(), True, "two")
    assert adapter.im._accept_message(message(), False, "one")
    assert len(adapter.im._received_messages) == 2
    now[0] += 181
    assert adapter.im._accept_message(message(), True, "two")
    assert len(adapter.im._received_messages) == 1


@pytest.mark.parametrize("attachment,expected", [
    ({"content_type": "voice", "asr_refer_text": "words"}, Text),
    ({"content_type": "voice", "url": "https://example.com/voice"}, Record),
    ({"content_type": "voice", "voice_wav_url": "https://example.com/voice.wav"}, Record),
    ({"content_type": "application/octet-stream", "filename": "audio.amr", "url": "https://example.com/voice"}, Record),
    ({"content_type": "image/png", "url": "https://example.com/img"}, Image),
    ({"content_type": "file", "url": "https://example.com/file"}, File),
])
def test_voice_asr_audio_and_existing_attachment_types(attachment, expected):
    chain = make_adapter().im._message_chain({"attachments": [attachment]}, True, "group-openid")
    element = chain.message_list[0]
    assert isinstance(element, expected)
    if expected is Text:
        assert element.text == "[Voice: words]"
    if attachment.get("voice_wav_url"):
        assert element.file == attachment["voice_wav_url"] and element.mime == "audio/wav"


def test_cards_faces_and_quoted_rich_content():
    ext = base64.b64encode(json.dumps({"text": "smile"}).encode()).decode().rstrip("=")
    quoted = {"content": f'<faceType=6, faceId="0", ext="{ext}">',
              "ark_data": {"ark_name": "map", "fields": {"title": "Park", "address": "Street"}},
              "attachments": [{"content_type": "voice", "asr_refer_text": "words"}]}
    chain = make_adapter().im._message_chain({"message_type": 103, "msg_elements": [quoted]}, True, "group-openid")
    reply = chain.message_list[0]
    assert isinstance(reply, Reply)
    assert reply.message_id == ""
    assert [item.text for item in reply.chain] == ["[Emoji: smile]", "[Card: map - Park - Street]", "[Voice: words]"]
    bad_face = QQOfficialMessageParser().content_elements({"content": '<faceType=6, faceId="0", ext="!!!">'}, True, "group")
    assert bad_face[0].text == "[Emoji]"


@pytest.mark.asyncio
@pytest.mark.parametrize("group", [False, True])
async def test_reference_ids_are_separate_from_passive_reply_ids_and_sent_ids(group):
    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
    attach_api(adapter, send)
    target = "group-openid" if group else "user-openid"
    await adapter.im._handle_message(message(group, message_scene={"ext": ["msg_idx=REFIDX_incoming"]}), group, True)
    incoming = adapter.ctx.event_queue.get_nowait().message.message_id
    first = await adapter.im._send_message(target, MessageChain([Reply(incoming), At("user-openid", "Alice"), Text(" hi")]), group)
    await adapter.im._send_message(target, MessageChain([Reply(first.message_id), Text("again")]), group)
    calls = [call.kwargs for call in send.await_args_list]
    expected_content = '<qqbot-at-user id="user-openid" /> hi'
    if group:
        assert calls[0]["markdown"] == {"content": expected_content}
        assert calls[0]["msg_type"] == 2
    else:
        assert calls[0]["content"] == expected_content
        assert calls[0]["msg_type"] == 0
    assert calls[0]["message_reference"] == {"message_id": "REFIDX_incoming"}
    assert calls[1]["message_reference"] == {"message_id": "REFIDX_sent"}
    assert all(call["msg_id"] == "incoming" for call in calls)
    await adapter.im._send_message(target, MessageChain([Text("no quote")]), group)
    assert "message_reference" not in send.await_args.kwargs
    other = "other-group" if group else "other-user"
    assert adapter.im._resolve_reference(group, other, MessageChain([Reply(incoming)])) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("code", ["40034005", "304103", "40034128"])
async def test_expiry_invalidates_id_and_only_retries_when_enabled(enabled, code):
    adapter = make_adapter(proactive_enabled=enabled)
    send = AsyncMock(side_effect=[RuntimeError(f"code={code} private_payload=secret"), {"id": "sent"}])
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hello")]))
    assert result.ok == enabled
    assert send.await_count == (2 if enabled else 1)
    assert "group-openid" not in adapter.im._group_reply_ids
    if enabled:
        assert "msg_id" not in send.await_args.kwargs and "msg_seq" not in send.await_args.kwargs
    else:
        assert "secret" not in result.err


@pytest.mark.asyncio
@pytest.mark.parametrize("group,age,limit", [(True, 301, 5), (False, 3601, 4)])
@pytest.mark.parametrize("cause", ["age", "limit"])
async def test_local_expiry_and_reply_limits_do_not_send_stale_ids(group, age, limit, cause):
    adapter = make_adapter(proactive_enabled=False)
    send = AsyncMock(return_value={"id": "sent"})
    attach_api(adapter, send)
    target = "group-openid" if group else "user-openid"
    await adapter.im._handle_message(message(group), group, True)
    key = (group, target, "incoming")
    if cause == "age":
        adapter.im._reply_received_at[key] -= age
    else:
        adapter.im._reply_msg_seqs[key] = limit
    result = await adapter.im._send_message(target, MessageChain([Text("late")]), group)
    assert not result.ok
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_explicit_quote_uses_fresh_passive_id_and_keeps_reference():
    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent"})
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message(message_scene={"ext": ["msg_idx=REFIDX_old"]}))
    old = adapter.ctx.event_queue.get_nowait().message.message_id
    adapter.im._reply_received_at[(True, "group-openid", "incoming")] -= 301
    await adapter.im._handle_group_message(message(message_id="fresh"))
    result = await adapter.send_group_message("group-openid", MessageChain([Reply(old), Text("hi")]))
    assert result.ok
    assert send.await_args.kwargs["msg_id"] == "fresh"
    assert send.await_args.kwargs["message_reference"]["message_id"] == "REFIDX_old"


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["40034105", "40034100", "40034006", "40034024", "unknown"])
async def test_other_errors_do_not_retry_or_invalidate_passive_id(code):
    adapter = make_adapter(proactive_enabled=True)
    send = AsyncMock(side_effect=RuntimeError(code))
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hi")]))
    assert not result.ok
    assert send.await_count == 1
    assert adapter.im._group_reply_ids["group-openid"] == "incoming"


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [None, False, True])
async def test_proactive_defaults_on_respects_disable_and_retries_are_bounded(enabled):
    adapter = make_adapter(**({} if enabled is None else {"proactive_enabled": enabled}))
    expected = enabled is not False
    assert adapter.im._proactive_enabled is expected
    send = AsyncMock(side_effect=RuntimeError("40034005"))
    attach_api(adapter, send)
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hi")]))
    assert not result.ok
    assert send.await_count == int(expected)
    if expected:
        assert "msg_id" not in send.await_args.kwargs

@pytest.mark.asyncio
async def test_concurrent_sends_use_distinct_reply_sequences():
    adapter = make_adapter()
    async def send(**payload):
        await asyncio.sleep(0)
        return {"id": f'sent-{payload["msg_seq"]}'}
    mocked = AsyncMock(side_effect=send)
    attach_api(adapter, mocked)
    await adapter.im._handle_group_message(message())
    results = await asyncio.gather(*(adapter.send_group_message("group-openid", MessageChain([Text("hi")])) for _ in range(5)))
    assert all(result.ok for result in results)
    assert [call.kwargs["msg_seq"] for call in mocked.await_args_list] == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_disconnect_during_upload_prevents_sending():
    adapter = make_adapter()
    send = AsyncMock()
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    async def upload(*args):
        adapter.client = None
        adapter._client_task = None
        return {"file_info": "file"}
    adapter.im._upload_file = upload
    result = await adapter.send_group_message("group-openid", MessageChain([Image("https://example.com/image")]))
    assert not result.ok
    send.assert_not_awaited()


def test_proactive_schema_has_english_chinese_and_enabled_default():
    from pathlib import Path
    schema = json.loads((Path(__file__).parents[1] / "core/adapter/src/qq_official/schema.json").read_text(encoding="utf-8"))
    field = schema["proactive_enabled"]
    assert field["default"] is True
    assert field["name"] and field["hint"]
    assert field["locales"]["zh"]["name"] and field["locales"]["zh"]["hint"]

@pytest.mark.asyncio
async def test_alias_eviction_removes_passive_time_and_reference_state(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION", 2)
    await adapter.im._handle_group_message(message(message_scene={"ext": ["msg_idx=REFIDX_old"]}))
    old_key = (True, "group-openid", "incoming")
    adapter.im._remember_reply_id(True, "group-openid", "sent-1")
    adapter.im._remember_reply_id(True, "group-openid", "sent-2")
    assert old_key not in adapter.im._reply_received_at
    assert old_key not in adapter.im._message_references
    assert "group-openid" not in adapter.im._group_reply_ids
    assert adapter.im._resolve_reply_id(True, "group-openid", MessageChain([Text("hi")])) is None


@pytest.mark.asyncio
async def test_received_quote_pointer_resolves_only_within_its_conversation():
    adapter = make_adapter(permission_mode="deny_list")
    await adapter.im._handle_group_message(message(message_scene={"ext": ["msg_idx=REFIDX_original"]}))
    original_id = adapter.ctx.event_queue.get_nowait().message.message_id
    quoted = message(message_id="quote", message_type=103, msg_elements=[{"content": "original"}],
                     message_scene={"ext": ["ref_msg_idx=REFIDX_original"]})
    chain = adapter.im._message_chain(quoted, True, "group-openid")
    assert chain.message_list[0].message_id == original_id
    other = adapter.im._message_chain(quoted, True, "another-group")
    assert other.message_list[0].message_id == ""


@pytest.mark.asyncio
async def test_passive_reply_is_revalidated_after_slow_upload():
    adapter = make_adapter(proactive_enabled=False)
    send = AsyncMock()
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    async def upload(*args):
        adapter.im._reply_received_at[(True, "group-openid", "incoming")] -= 301
        return {"file_info": "file"}
    adapter.im._upload_file = upload
    result = await adapter.send_group_message("group-openid", MessageChain([Image("https://example.com/image")]))
    assert not result.ok
    send.assert_not_awaited()


def test_identity_cache_capacity_and_conversation_scope(monkeypatch):
    from core.adapter.src.qq_official import message_parser
    monkeypatch.setattr(message_parser, "MAX_IDENTITIES", 2)
    parser = QQOfficialMessageParser()
    for index in range(3):
        parser.nickname(True, str(index), {"username": "Alice"}, "user")
        parser.self_ids({"mentions": [{"id": str(index), "is_you": True}]}, True, str(index), "")
    assert len(parser._names) == len(parser._self_ids) == 2
    assert parser.nickname(True, "0", {}, "user") == "user"
    assert parser.self_ids({}, True, "0", "") == set()

@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
async def test_inflight_send_does_not_restore_evicted_reply_state(monkeypatch, expired):
    adapter = make_adapter(proactive_enabled=False)
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION", 2)
    async def send(**payload):
        for index in range(3):
            await adapter.im._handle_group_message(message(message_id=f"fresh-{index}"))
        if expired:
            raise RuntimeError("40034005")
        return {"id": "sent"}
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hi")]))
    assert result.ok == (not expired)
    key = (True, "group-openid", "incoming")
    assert key not in adapter.im._reply_received_at
    assert key not in adapter.im._reply_msg_seqs
    assert adapter.im._group_reply_ids["group-openid"] == "fresh-2"

@pytest.mark.asyncio
async def test_default_proactive_fallback_sends_once_after_passive_expiry():
    adapter = make_adapter()
    send = AsyncMock(side_effect=[RuntimeError("40034005"), {"id": "sent"}])
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hi")]))
    assert result.ok
    assert send.await_count == 2
    assert "msg_id" not in send.await_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("quote_kind", ["scene", "nested_id", "legacy_reference"])
@pytest.mark.parametrize("include_author", [False, True])
async def test_quoting_sent_message_triggers_chat_without_matching_author_id(quote_kind, include_author):
    from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin

    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
    attach_api(adapter, send)
    adapter.client.robot = SimpleNamespace(id="login-bot-id", name="Bot")
    result = await adapter.send_group_message("group-openid", MessageChain([Text("hello")]))
    assert result.ok
    body = message(message_id="quote", message_type=103,
                   msg_elements=[{"content": "hello", "author": {"id": "group-bot-openid"}}])
    if not include_author:
        body["msg_elements"][0].pop("author")
    if quote_kind == "scene":
        body["message_scene"] = {"ext": ["ref_msg_idx=REFIDX_sent"]}
    elif quote_kind == "nested_id":
        body["msg_elements"][0]["id"] = "sent"
    else:
        body.pop("message_type")
        body["message_reference"] = {"message_id": "sent"}
    await adapter.im._handle_group_message(body, force_mention=False)
    event = adapter.ctx.event_queue.get_nowait()
    ctx = SimpleNamespace(config={"bot_config": {"bot": {"max_buffer_messages": 1}}},
                          message_processor=SimpleNamespace(get_session_buffer_length=lambda _sid: 0))
    chat = DefaultChatPlugin(ctx, {"receive_unmentioned": False})
    await chat.handle_msg(event)
    assert event.is_mentioned
    assert event._process_strategy == "flush"
    assert event.message.chain.message_list[0].message_id == result.message_id


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["received", "unknown", "other_group", "other_direct", "forward", "cached_quote", "failed_send"])
async def test_quote_trigger_requires_own_sent_message_in_same_conversation(case):
    adapter = make_adapter(permission_mode="deny_list")
    send = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
    attach_api(adapter, send)
    body = message(message_id="quote", message_type=103, msg_elements=[{"content": "hello"}],
                   message_scene={"ext": ["ref_msg_idx=REFIDX_sent"]})
    if case == "received":
        await adapter.im._handle_group_message(message(message_id="sent", message_scene={"ext": ["msg_idx=REFIDX_sent"]}))
        adapter.ctx.event_queue.get_nowait()
    elif case == "cached_quote":
        await adapter.im._handle_group_message(message(message_id="original", message_type=103,
                                                       msg_elements=[{"id": "sent", "content": "other user's message"}]))
        adapter.ctx.event_queue.get_nowait()
        body["msg_elements"][0]["id"] = "sent"
    elif case == "failed_send":
        send.side_effect = RuntimeError("40034100")
        result = await adapter.send_group_message("group-openid", MessageChain([Text("hello")]))
        assert not result.ok
    elif case != "unknown":
        group = case != "other_direct"
        target = "other-group" if case == "other_group" else "group-openid"
        result = await adapter.im._send_message(target, MessageChain([Text("hello")]), group)
        assert result.ok
        if case == "forward":
            body["message_type"] = 100
    await adapter.im._handle_group_message(body, force_mention=False)
    event = adapter.ctx.event_queue.get_nowait()
    assert not event.is_mentioned


@pytest.mark.asyncio
async def test_sent_quote_identity_is_evicted_with_message_aliases(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION", 2)
    send = AsyncMock(side_effect=[{"id": f"sent-{index}", "ext_info": {"ref_idx": f"REFIDX_{index}"}} for index in range(3)])
    attach_api(adapter, send)
    for _ in range(3):
        assert (await adapter.send_group_message("group-openid", MessageChain([Text("hello")]))).ok
    assert len(adapter.im._sent_message_ids) == 2
    body = message(message_id="quote", message_type=103, msg_elements=[{"content": "hello"}],
                   message_scene={"ext": ["ref_msg_idx=REFIDX_0"]})
    await adapter.im._handle_group_message(body, force_mention=False)
    assert not adapter.ctx.event_queue.get_nowait().is_mentioned


@pytest.mark.asyncio
async def test_real_sdk_full_message_quote_wakes_chat_without_at(sdk_gateway):
    from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin

    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        await asyncio.wait_for(sdk_gateway.opened.get(), 2)
        adapter.client.api.post_group_message = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
        assert (await adapter.send_group_message("group-openid", MessageChain([Text("hello")]))).ok
        body = message(message_id="quote", message_type=103, msg_elements=[{"content": "hello"}],
                       message_scene={"ext": ["ref_msg_idx=REFIDX_sent"]})
        adapter.client._connection.parser["group_message_create"]({"d": body})
        await asyncio.sleep(0)
        event = adapter.ctx.event_queue.get_nowait()
        ctx = SimpleNamespace(config={"bot_config": {"bot": {"max_buffer_messages": 1}}},
                              message_processor=SimpleNamespace(get_session_buffer_length=lambda _sid: 0))
        chat = DefaultChatPlugin(ctx, {"receive_unmentioned": False})
        await chat.handle_msg(event)
        assert event.is_mentioned
        assert event._process_strategy == "flush"
        adapter.client._connection.parser["group_at_message_create"]({"d": body})
        await asyncio.sleep(0)
        assert adapter.ctx.event_queue.empty()
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)

@pytest.mark.asyncio
@pytest.mark.parametrize("mention", ["element", "raw_new", "raw_legacy"])
@pytest.mark.parametrize("reply_mode", ["passive", "proactive", "expired"])
async def test_group_mentions_use_markdown_payload_and_keep_reply_context(mention, reply_mode):
    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
    attach_api(adapter, send)
    if reply_mode != "proactive":
        await adapter.im._handle_group_message(message(message_scene={"ext": ["msg_idx=REFIDX_incoming"]}))
        received_id = adapter.ctx.event_queue.get_nowait().message.message_id
    if reply_mode == "expired":
        send.side_effect = [RuntimeError("40034005"), {"id": "sent"}]
    expected = 'hello <qqbot-at-user id="user-openid" />'
    if mention == "element":
        chain = MessageChain([Text("hello "), At("user-openid")])
    else:
        markup = '<qqbot-at-user id="user-openid" />' if mention == "raw_new" else "<@user-openid>"
        chain = MessageChain([Text("hello " + markup)])
    if reply_mode != "proactive":
        chain.message_list.insert(0, Reply(received_id))
    result = await adapter.send_group_message("group-openid", chain)
    assert result.ok
    for call in send.await_args_list:
        payload = call.kwargs
        assert payload["msg_type"] == 2
        assert payload["markdown"] == {"content": expected}
        assert "content" not in payload
        if reply_mode != "proactive":
            assert payload["message_reference"] == {"message_id": "REFIDX_incoming"}
    first = send.await_args_list[0].kwargs
    if reply_mode == "proactive":
        assert "msg_id" not in first and "msg_seq" not in first
    else:
        assert first["msg_id"] == "incoming" and first["msg_seq"] == 1
    if reply_mode == "expired":
        assert send.await_count == 2
        assert "msg_id" not in send.await_args.kwargs
        assert "msg_seq" not in send.await_args.kwargs
    else:
        assert send.await_count == 1

@pytest.mark.asyncio
async def test_real_sdk_serializes_group_mention_in_markdown_field(sdk_gateway):
    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        await asyncio.wait_for(sdk_gateway.opened.get(), 2)
        request = AsyncMock(return_value={"id": "sent", "ext_info": {"ref_idx": "REFIDX_sent"}})
        adapter.client.api._http.request = request
        result = await adapter.send_group_message("group-openid", MessageChain([Text("hello "), At("user-openid")]))
        assert result.ok
        payload = request.await_args.kwargs["json"]
        assert payload["msg_type"] == 2
        assert payload["markdown"] == {"content": 'hello <qqbot-at-user id="user-openid" />'}
        assert payload["content"] is None
        assert payload["group_openid"] == "group-openid"
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("code", ["40034105", "40034100", "40034006", "40034024", "unknown"])
async def test_markdown_send_errors_do_not_start_extra_retries(code):
    adapter = make_adapter()
    send = AsyncMock(side_effect=RuntimeError(code))
    attach_api(adapter, send)
    await adapter.im._handle_group_message(message())
    adapter.ctx.event_queue.get_nowait()
    result = await adapter.send_group_message("group-openid", MessageChain([At("user-openid"), Text("hello")]))
    assert not result.ok
    assert send.await_count == 1
    assert send.await_args.kwargs["msg_type"] == 2
    assert adapter.im._group_reply_ids["group-openid"] == "incoming"

@pytest.mark.asyncio
@pytest.mark.parametrize("first_forced, second_forced", [(False, True), (True, False), (True, True), (False, False)])
async def test_duplicate_group_event_preserves_forced_mention_on_shared_message(first_forced, second_forced):
    from core.plugin.builtin_plugins.chat.main import DefaultChatPlugin

    adapter = make_adapter()
    send = AsyncMock(return_value={"id": "sent"})
    attach_api(adapter, send)
    body = message(msg_seq=1)
    await adapter.im._handle_group_message(body, force_mention=first_forced)
    event = adapter.ctx.event_queue.get_nowait()
    original_message = event.message
    await adapter.send_group_message("group-openid", MessageChain([Text("first reply")]))
    await adapter.im._handle_group_message(body, force_mention=second_forced)
    assert adapter.ctx.event_queue.empty()
    assert event.message is original_message
    assert event.is_mentioned == (first_forced or second_forced)
    assert adapter.im._reply_msg_seqs[(True, "group-openid", "incoming")] == 1
    ctx = SimpleNamespace(config={"bot_config": {"bot": {"max_buffer_messages": 1}}},
                          message_processor=SimpleNamespace(get_session_buffer_length=lambda _sid: 0))
    chat = DefaultChatPlugin(ctx, {"receive_unmentioned": False})
    await chat.handle_msg(event)
    assert event.process_strategy == ("flush" if first_forced or second_forced else "discard")
    await adapter.im._handle_group_message(body, force_mention=second_forced)
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
async def test_forced_duplicate_during_metadata_await_is_applied_before_publication():
    adapter = make_adapter()
    metadata_started = asyncio.Event()
    release_metadata = asyncio.Event()
    get_metadata = adapter.im.get_message_metadata
    async def delayed_metadata():
        metadata_started.set()
        await release_metadata.wait()
        return await get_metadata()
    adapter.im.get_message_metadata = delayed_metadata
    body = message(msg_seq=1)
    first = asyncio.create_task(adapter.im._handle_group_message(body, force_mention=False))
    try:
        await metadata_started.wait()
        await adapter.im._handle_group_message(body, force_mention=True)
        assert adapter.ctx.event_queue.empty()
        release_metadata.set()
        await first
        event = adapter.ctx.event_queue.get_nowait()
        assert event.is_mentioned
        assert adapter.ctx.event_queue.empty()
    finally:
        release_metadata.set()
        await first

@pytest.mark.asyncio
@pytest.mark.parametrize("first_event", ["group_message_create", "group_at_message_create"])
async def test_real_sdk_duplicate_at_event_promotes_single_queued_message(sdk_gateway, first_event):
    adapter = make_adapter()
    try:
        await start_adapter(adapter)
        await asyncio.wait_for(sdk_gateway.opened.get(), 2)
        body = message(msg_seq=1)
        second_event = "group_at_message_create" if first_event == "group_message_create" else "group_message_create"
        adapter.client._connection.parser[first_event]({"d": body})
        await asyncio.sleep(0)
        event = adapter.ctx.event_queue.get_nowait()
        adapter.client._connection.parser[second_event]({"d": body})
        await asyncio.sleep(0)
        assert event.is_mentioned
        assert adapter.ctx.event_queue.empty()
    finally:
        await adapter.stop()
        await cleanup_sdk_gateway(sdk_gateway.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("other_key", ["group", "direct", "sequence"])
async def test_forced_dedup_upgrade_does_not_cross_conversation_or_sequence(other_key):
    adapter = make_adapter(permission_mode="deny_list")
    body = message(msg_seq=1)
    await adapter.im._handle_group_message(body, force_mention=False)
    original = adapter.ctx.event_queue.get_nowait()
    if other_key == "direct":
        await adapter.im._handle_direct_message(message(False, msg_seq=1))
    else:
        other = dict(body, group_openid="other-group") if other_key == "group" else dict(body, msg_seq=2)
        await adapter.im._handle_group_message(other, force_mention=True)
    assert adapter.ctx.event_queue.get_nowait().is_mentioned
    assert not original.is_mentioned
    await adapter.im._handle_group_message(body, force_mention=True)
    assert original.is_mentioned
    assert adapter.ctx.event_queue.empty()


@pytest.mark.asyncio
@pytest.mark.parametrize("eviction", ["ttl", "capacity"])
async def test_evicted_dedup_record_does_not_promote_old_message(monkeypatch, eviction):
    adapter = make_adapter()
    now = [10.0]
    monkeypatch.setattr(im_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(im_module, "QQ_OFFICIAL_MAX_RECEIVED_MESSAGES", 1)
    body = message()
    await adapter.im._handle_group_message(body, force_mention=False)
    original = adapter.ctx.event_queue.get_nowait()
    if eviction == "ttl":
        now[0] += 181
    else:
        await adapter.im._handle_group_message(message(message_id="other"), force_mention=False)
        adapter.ctx.event_queue.get_nowait()
    await adapter.im._handle_group_message(body, force_mention=True)
    replacement = adapter.ctx.event_queue.get_nowait()
    assert replacement.is_mentioned
    assert not original.is_mentioned
    assert replacement.message is not original.message
    assert len(adapter.im._received_messages) == 1


@pytest.mark.asyncio
async def test_dedup_record_does_not_retain_consumed_message_content():
    import gc
    from weakref import ref

    adapter = make_adapter()
    body = message()
    await adapter.im._handle_group_message(body, force_mention=False)
    event = adapter.ctx.event_queue.get_nowait()
    message_ref = ref(event.message)
    del event
    gc.collect()
    assert message_ref() is None
    await adapter.im._handle_group_message(body, force_mention=True)
    assert adapter.ctx.event_queue.empty()
