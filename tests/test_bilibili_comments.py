import asyncio
import base64
import json
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from bilibili_api import comment, dynamic

from core.adapter import FeedCapability, FeedItem, FeedRef
from core.chat import KiraCommentEvent, MessageChain
from core.chat.message_elements import At, Emoji, Image, Text, Video
from tests.test_bilibili_adapter import make_adapter, sdk_client
from tests.test_bilibili_feed_post import image_bytes


@pytest.mark.asyncio
async def test_comment_chain_preserves_text_and_native_emoji_order(monkeypatch):
    adapter = make_adapter()
    adapter.emoji_dict = {"1": "[微笑]"}
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    message = MessageChain([Text("one"), Emoji(1), Text("two"), Emoji(2, "[大笑]")])
    result = await adapter.feed.send_comment(message, FeedRef("video", "42"), root=10, parent=11)
    assert result == {"rpid": 1}
    send.assert_awaited_once_with(
        text="one[微笑]two[大笑]", oid=42, type_=comment.CommentResourceType.VIDEO,
        root=10, parent=11, pic=None,
    )
    assert isinstance(message[1], Emoji)


@pytest.mark.asyncio
@pytest.mark.parametrize("message", [
    "plain string", MessageChain(), MessageChain([Text(" ")]),
    MessageChain([At(42, "user")]), MessageChain([Video("https://video.test/a")]),
    MessageChain([Image("https://image.test/a"), Text(None)]),
])
async def test_invalid_comment_chains_fail_before_external_work(monkeypatch, message):
    adapter = make_adapter()
    send = AsyncMock()
    detail = AsyncMock()
    load = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    monkeypatch.setattr(adapter.feed, "_load_picture", load)
    with pytest.raises((TypeError, ValueError)):
        await adapter.feed.send_comment(message, FeedRef("dynamic", "42"))
    send.assert_not_awaited()
    detail.assert_not_awaited()
    load.assert_not_awaited()


@pytest.mark.asyncio
async def test_text_keyword_is_no_longer_accepted():
    with pytest.raises(TypeError, match="text"):
        await make_adapter().feed.send_comment(text="old interface", target=FeedRef("video", "42"))


@pytest.mark.asyncio
async def test_unknown_emoji_is_not_sent_as_a_numeric_token(monkeypatch):
    adapter = make_adapter()
    adapter.emoji_dict = {}
    send = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    with pytest.raises(ValueError, match="native token"):
        await adapter.feed.send_comment(MessageChain([Emoji(123)]), FeedRef("video", "42"))
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_comment_sdk_payload_includes_images_and_cleans_unique_files(monkeypatch, sdk_client):
    payloads = []
    upload_paths = []
    credentials = []

    class Api:
        def __init__(self, **kwargs):
            self.data = {}
            self.files = {}
            credentials.append(kwargs["credential"])

        def update_data(self, **data):
            self.data = data
            return self

        def update_files(self, **files):
            self.files = files
            return self

        @property
        def result(self):
            async def resolve():
                if self.files:
                    file = self.files["file_up"]
                    path = Path(file.path)
                    upload_paths.append(path)
                    assert path.read_bytes() == image_bytes()
                    assert file.mime_type == "image/png"
                    return {"image_height": 3, "image_width": 2, "image_url": f"https://image.test/{len(upload_paths)}", "img_size": 1}
                payloads.append(self.data)
                return {"rpid": 123}
            return resolve()

    monkeypatch.setattr(comment, "Api", Api)
    monkeypatch.setattr(dynamic, "Api", Api)
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    adapter.emoji_dict = {"1": "[微笑]"}
    image = base64.b64encode(image_bytes()).decode()
    message = MessageChain([Text("one"), Image(image, caption="caption"), Emoji(1), Image(image), Text("two")])
    assert await adapter.feed.send_comment(message, FeedRef("video", "42"), root=10, parent=11) == {"rpid": 123}
    payload = payloads[0]
    assert payload["message"] == "onecaption[微笑]two"
    assert payload["oid"] == 42 and payload["type"] == 1
    assert (payload["root"], payload["parent"]) == (10, 11)
    pictures = json.loads(payload["pictures"])
    assert [picture["img_src"] for picture in pictures] == ["https://image.test/1", "https://image.test/2"]
    assert all(picture["img_width"] == 2 and picture["img_height"] == 3 for picture in pictures)
    assert len(set(upload_paths)) == 2
    assert all(not path.parent.exists() for path in upload_paths)
    assert all(credential is adapter.credential for credential in credentials)


@pytest.mark.asyncio
async def test_image_only_comment_is_supported(monkeypatch):
    adapter = make_adapter()
    send = AsyncMock(return_value={"rpid": 1})
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    image = base64.b64encode(image_bytes()).decode()
    await adapter.feed.send_comment(MessageChain([Image(image)]), FeedRef("video", "42"))
    assert send.await_args.kwargs["text"] == ""
    assert send.await_args.kwargs["pic"][0].content == image_bytes()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["failure", "cancel", "timeout"])
async def test_comment_image_upload_cleanup_on_failure_cancel_and_timeout(monkeypatch, sdk_client, mode):
    paths = []
    adapter = make_adapter(sessdata="session", bili_jct="csrf")

    async def send(**kwargs):
        paths.extend(Path(picture._to_biliapifile().path) for picture in kwargs["pic"])
        assert all(path.exists() for path in paths)
        if mode == "failure":
            raise RuntimeError("private-post-and-cookie")
        if mode == "cancel":
            raise asyncio.CancelledError()
        await asyncio.Event().wait()

    monkeypatch.setattr(comment, "send_comment", send)
    if mode == "timeout":
        adapter.get_client().timeout = 0.1
    error = asyncio.CancelledError if mode == "cancel" else TimeoutError if mode == "timeout" else RuntimeError
    image = base64.b64encode(image_bytes()).decode()
    with pytest.raises(error) as caught:
        await adapter.feed.send_comment(MessageChain([Image(image), Image(image)]), FeedRef("video", "42"))
    if mode != "cancel":
        assert "private" not in str(caught.value)
    assert paths and all(not path.parent.exists() for path in paths)


def test_public_feed_comment_signature_uses_message_chain():
    for method in (FeedCapability.send_comment, type(make_adapter().feed).send_comment):
        signature = inspect.signature(method)
        assert "text" not in signature.parameters
        assert signature.parameters["message"].annotation == "MessageChain"
        assert signature.parameters["target"].annotation == "FeedItem | FeedRef"


@pytest.mark.asyncio
@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("item_target", [False, True])
async def test_comment_event_metadata_provides_uniform_reply_arguments(monkeypatch, nested, item_target):
    adapter = make_adapter()
    resource = FeedRef("video", "BV17x411w7KC")
    if item_target:
        resource = FeedItem(
            FeedRef("dynamic", "100"), "video", MessageChain([Text("post")]),
            comment_target=FeedRef("video", "170001"),
        )
    event = KiraCommentEvent(
        platform=adapter.info.platform, adapter_name=adapter.info.name,
        commenter_id="user", commenter_nickname="user", self_id=adapter.bot_uid,
        timestamp=1, comment_id=11 if nested else 10,
        comment_content=[Text("nested" if nested else "root")], target=resource,
        root_comment_id=10 if nested else None,
        root_comment_content=[Text("root")] if nested else None,
    )
    send = AsyncMock(return_value={"rpid": 123})
    detail = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    assert await adapter.feed.send_comment(
        MessageChain([Text("reply")]), target=event.target,
        root=event.root_comment_id, parent=event.comment_id,
    ) == {"rpid": 123}
    send.assert_awaited_once_with(
        text="reply", oid=170001, type_=comment.CommentResourceType.VIDEO,
        root=10, parent=11 if nested else 10, pic=None,
    )
    detail.assert_not_awaited()
    assert event.target is resource and event.root_comment_id == 10
    assert event.comment_id == (11 if nested else 10)
    assert event.comment_content[0].text == ("nested" if nested else "root")


@pytest.mark.asyncio
async def test_send_comment_rejects_event_objects_before_external_work(monkeypatch):
    adapter = make_adapter()
    event = KiraCommentEvent(
        adapter.info.platform, adapter.info.name, "user", "user", adapter.bot_uid,
        1, 10, [Text("root")], FeedRef("dynamic", "42"),
    )
    send = AsyncMock()
    detail = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_comment", send)
    monkeypatch.setattr(adapter.get_client(), "get_dynamic_info", detail)
    with pytest.raises(TypeError, match="FeedItem or FeedRef"):
        await adapter.feed.send_comment(MessageChain([Text("reply")]), event)
    send.assert_not_awaited()
    detail.assert_not_awaited()
