import asyncio
import base64
import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
from Crypto.Cipher import AES

from core.adapter.adapter_info import AdapterInfo
from core.adapter.src.qq_official import qq_official
from core.adapter.src.qq_official.qq_official import QQOfficialAdapter
from core.chat import MessageChain
from core.chat.message_elements import At, Emoji, File, Image, Record, Reply, Text


def test_qq_official_schema_starts_with_setup_info():
    schema_path = Path(__file__).parents[1] / "core" / "adapter" / "src" / "qq_official" / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    key, field = next(iter(schema.items()))

    assert key == "setup_info"
    assert field["type"] == "info"
    assert field["level"] == "info"


def make_adapter(permission_mode="allow_list"):
    return QQOfficialAdapter(
        AdapterInfo(
            adapter_id="qq-official-test",
            enabled=True,
            name="qq_official",
            platform="QQ Official",
            config={
                "app_id": "test-app",
                "app_secret": "test-secret",
                "permission_mode": permission_mode,
                "group_allow_list": ["group-openid"],
                "user_allow_list": ["user-openid"],
                "group_deny_list": ["group-denied"],
                "user_deny_list": ["user-denied"],
            },
        ),
        asyncio.Queue(),
    )


def test_qq_official_defers_botpy_client_creation():
    adapter = make_adapter()

    assert adapter.client is None


def test_qq_official_bounds_reply_state_per_conversation(monkeypatch):
    adapter = make_adapter()
    monkeypatch.setattr(qq_official, "QQ_OFFICIAL_MAX_REPLY_IDS_PER_CONVERSATION", 2)
    target_id = "user-openid"
    raw_message_ids = ["message-1", "message-2", "message-3"]
    display_message_ids = []
    for raw_message_id in raw_message_ids:
        display_message_ids.append(
            adapter._remember_reply_id(False, target_id, raw_message_id)
        )
        adapter._send_locks[(False, target_id, raw_message_id)] = object()

    expired_key = (False, target_id, raw_message_ids[0])
    assert (False, target_id, display_message_ids[0]) not in adapter._reply_id_aliases
    assert expired_key not in adapter._reply_msg_seqs
    assert expired_key not in adapter._send_locks
    assert (False, target_id, display_message_ids[1]) in adapter._reply_id_aliases
    assert (False, target_id, display_message_ids[2]) in adapter._reply_id_aliases


@pytest.mark.asyncio
async def test_qq_official_allow_list_uses_openids():
    adapter = make_adapter()

    assert adapter._is_allowed("group-openid", is_group=True)
    assert adapter._is_allowed("user-openid", is_group=False)
    assert not adapter._is_allowed("other-group", is_group=True)
    assert not adapter._is_allowed("other-user", is_group=False)


@pytest.mark.asyncio
async def test_qq_official_deny_list_uses_openids():
    adapter = make_adapter(permission_mode="deny_list")

    assert adapter._is_allowed("other-group", is_group=True)
    assert adapter._is_allowed("other-user", is_group=False)
    assert not adapter._is_allowed("group-denied", is_group=True)
    assert not adapter._is_allowed("user-denied", is_group=False)


def test_qq_official_text_content_omits_reply_metadata():
    content = QQOfficialAdapter._text_content(
        MessageChain([Reply("message-id"), Text("Hello "), At("u1", "Alice"), Emoji("1", "!"), Text(".")])
    )

    assert content == "Hello @Alice!."


@pytest.mark.asyncio
async def test_qq_official_maps_amr_attachment_to_record():
    message = SimpleNamespace(
        content="",
        attachments=[
            SimpleNamespace(
                url="https://example.com/voice.amr",
                filename="voice.amr",
                content_type="application/octet-stream",
                size=4273,
            )
        ],
    )

    chain = make_adapter()._message_chain(message, is_group=False, target_id="user-openid")

    assert isinstance(chain.message_list[0], Record)
    assert not isinstance(chain.message_list[0], Image)


@pytest.mark.asyncio
async def test_qq_official_increments_msg_seq_for_multiple_replies():
    adapter = make_adapter()
    sent_payloads = []

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": f"sent-{len(sent_payloads)}"}

    adapter.client = SimpleNamespace(api=SimpleNamespace(post_c2c_message=post_c2c_message))
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter._direct_reply_ids["user-openid"] = "incoming-message-id"

    first_result = await adapter.send_direct_message("user-openid", MessageChain([Text("first")]))
    await adapter.send_direct_message("user-openid", MessageChain([Text("second")]))

    assert [payload["msg_seq"] for payload in sent_payloads] == [1, 2]
    assert all(payload["msg_id"] == "incoming-message-id" for payload in sent_payloads)
    assert first_result.message_id.startswith("qqo-")
    assert adapter._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(first_result.message_id), Text("reply")]),
    ) == "sent-1"


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_local_file():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "file-uuid", "file_info": "file-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-file"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter._direct_reply_ids["user-openid"] = "incoming-message-id"
    file_path = str(Path(__file__).resolve())

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([File(file_path, name="test.py")])
    )

    assert result.ok
    assert uploads[0]["file_type"] == 4
    assert uploads[0]["file_name"] == "test.py"
    assert uploads[0]["file_data"]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "file-info"}
    assert sent_payloads[0]["content"] is None


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_local_image():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "image-uuid", "file_info": "image-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-image"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter._direct_reply_ids["user-openid"] = "incoming-message-id"

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([Image(str(Path(__file__).resolve()), name="image.jpg")])
    )

    assert result.ok
    assert uploads[0]["file_type"] == 1
    assert uploads[0]["file_name"] == "image.jpg"
    assert uploads[0]["file_data"]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "image-info"}


@pytest.mark.asyncio
async def test_qq_official_uploads_and_sends_image_url():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def post_c2c_file(**payload):
        uploads.append(payload)
        return {"file_uuid": "image-uuid", "file_info": "image-info", "ttl": 60}

    async def post_c2c_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-image"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            post_c2c_file=post_c2c_file,
            post_c2c_message=post_c2c_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter._direct_reply_ids["user-openid"] = "incoming-message-id"

    result = await adapter.send_direct_message(
        "user-openid", MessageChain([Image("https://example.com/image.png")])
    )

    assert result.ok
    assert uploads == [{
        "openid": "user-openid",
        "file_type": 1,
        "url": "https://example.com/image.png",
        "srv_send_msg": False,
    }]
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["media"] == {"file_info": "image-info"}
    assert sent_payloads[0]["content"] is None

@pytest.mark.asyncio
async def test_qq_official_group_file_keeps_reply_message_id():
    adapter = make_adapter()
    uploads = []
    sent_payloads = []

    async def request(_, json):
        uploads.append(json)
        return {"file_uuid": "file-uuid", "file_info": "file-info", "ttl": 60}

    async def post_group_message(**payload):
        sent_payloads.append(payload)
        return {"id": "sent-group-file"}

    adapter.client = SimpleNamespace(
        api=SimpleNamespace(
            _http=SimpleNamespace(request=request),
            post_group_message=post_group_message,
        )
    )
    adapter._client_task = SimpleNamespace(done=lambda: False)
    adapter._group_reply_ids["group-openid"] = "incoming-group-message-id"

    result = await adapter.send_group_message(
        "group-openid", MessageChain([File(str(Path(__file__).resolve()), name="test.py")])
    )

    assert result.ok
    assert uploads[0]["group_openid"] == "group-openid"
    assert sent_payloads[0]["msg_type"] == 7
    assert sent_payloads[0]["msg_id"] == "incoming-group-message-id"
    assert sent_payloads[0]["media"] == {"file_info": "file-info"}

@pytest.mark.asyncio
async def test_qq_official_uses_short_message_id_alias_for_llm_and_reply():
    adapter = make_adapter()
    raw_message_id = "ROBOT1.0_" + "x" * 300
    message = SimpleNamespace(
        id=raw_message_id,
        content="hello",
        attachments=[],
        author=SimpleNamespace(user_openid="user-openid"),
    )

    await adapter._handle_direct_message(message)

    event = adapter._event_queue.get_nowait()
    display_message_id = event.message.message_id
    assert display_message_id.startswith("qqo-")
    assert len(display_message_id) == 14
    assert raw_message_id not in display_message_id
    assert adapter._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(display_message_id), Text("reply")]),
    ) == raw_message_id


@pytest.mark.asyncio
async def test_qq_official_reads_quoted_message_with_short_reply_id():
    adapter = make_adapter()
    raw_quote_id = "ROBOT1.0_" + "q" * 300
    message = SimpleNamespace(
        id="incoming-message-id",
        content="我的回复",
        attachments=[],
        author=SimpleNamespace(user_openid="user-openid"),
        message_type=103,
        message_reference=SimpleNamespace(message_id=raw_quote_id),
        msg_elements=[
            SimpleNamespace(
                id=raw_quote_id,
                content="被引用的内容",
                attachments=[],
            )
        ],
    )

    await adapter._handle_direct_message(message)

    event = adapter._event_queue.get_nowait()
    reply, text = event.message.chain.message_list
    assert isinstance(reply, Reply)
    assert reply.message_id.startswith("qqo-")
    assert raw_quote_id not in reply.message_id
    assert isinstance(reply.chain.message_list[0], Text)
    assert reply.chain.message_list[0].text == "被引用的内容"
    assert isinstance(text, Text)
    assert text.text == "我的回复"
    assert adapter._resolve_reply_id(
        False,
        "user-openid",
        MessageChain([Reply(reply.message_id), Text("reply")]),
    ) == raw_quote_id


@pytest.mark.asyncio
async def test_qq_official_empty_credentials_start_qr_login(monkeypatch):
    adapter = make_adapter()
    adapter.app_id = ""
    adapter.app_secret = ""
    displayed_urls = []
    saved = False
    started = False

    bind_key = base64.b64encode(secrets.token_bytes(32)).decode("ascii")
    secret = "scanned-secret"
    nonce = secrets.token_bytes(12)
    cipher = AES.new(base64.b64decode(bind_key), AES.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(secret.encode("utf-8"))
    encrypted_secret = base64.b64encode(nonce + ciphertext + tag).decode("ascii")

    async def fake_start_session():
        adapter._display_qr_code("https://q.qq.com/qqbot/connect")
        return qq_official.QQOfficialLoginSession("task-id", bind_key)

    async def fake_poll_session(_):
        return {
            "status": 2,
            "bot_appid": "scanned-app-id",
            "bot_encrypt_secret": encrypted_secret,
            "user_openid": "scanner-openid",
        }

    async def fake_save_credentials():
        nonlocal saved
        saved = True

    async def fake_start():
        nonlocal started
        started = True

    monkeypatch.setattr(adapter, "_display_qr_code", displayed_urls.append)
    monkeypatch.setattr(adapter, "_start_qr_login_session", fake_start_session)
    monkeypatch.setattr(adapter, "_poll_qr_login_session", fake_poll_session)
    monkeypatch.setattr(adapter, "_save_credentials", fake_save_credentials)
    monkeypatch.setattr(adapter, "start", fake_start)

    await adapter._run_qr_login()

    assert displayed_urls == ["https://q.qq.com/qqbot/connect"]
    assert adapter.app_id == "scanned-app-id"
    assert adapter.app_secret == "scanned-secret"
    assert "scanner-openid" in adapter.user_list
    assert saved
    assert started
