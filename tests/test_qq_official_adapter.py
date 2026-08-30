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
from core.chat.message_elements import At, Emoji, Image, Record, Reply, Text


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


def test_qq_official_maps_amr_attachment_to_record():
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

    chain = QQOfficialAdapter._message_chain(message)

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
