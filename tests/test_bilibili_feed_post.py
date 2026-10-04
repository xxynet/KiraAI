import asyncio
import base64
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.adapter_lifecycle import start_adapter
from PIL import Image as PILImage
from bilibili_api import dynamic
from bilibili_api.utils.picture import Picture

from core.adapter import FeedCapability, FeedPost
from core.adapter.src.bilibili import BiliBiliClient
from core.adapter.src.bilibili import client as client_module
from core.chat import MessageChain
from core.chat.message_elements import At, Emoji, Image, Text, Video
from tests.test_bilibili_adapter import make_adapter, sdk_client


def image_bytes(color="red", format="PNG"):
    stream = BytesIO()
    PILImage.new("RGB", (2, 3), color).save(stream, format=format)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_native_clients_bind_distinct_accounts_and_survive_restart(monkeypatch, sdk_client):
    first = make_adapter(enable_im=False, sessdata="account-one", bili_jct="csrf-one")
    second = make_adapter(enable_im=False, sessdata="account-two", bili_jct="csrf-two")
    first_client = first.get_client()
    assert isinstance(first_client, BiliBiliClient)
    assert first_client is not second.get_client()
    send = AsyncMock(return_value={"dyn_id": "123"})
    monkeypatch.setattr(dynamic, "send_dynamic", send)
    draft = dynamic.BuildDynamic.empty().add_plain_text("native post")
    await first_client.send_dynamic(draft)
    await second.get_client().send_dynamic(draft)
    assert [call.kwargs["credential"] for call in send.await_args_list] == [
        first.credential, second.credential,
    ]
    assert all(call.kwargs["info"] is not draft for call in send.await_args_list)
    first._log_login_status = AsyncMock()
    await start_adapter(first)
    await first.stop()
    await start_adapter(first)
    assert first.get_client() is first_client
    sdk_client.close.assert_not_awaited()
    await first.stop()


@pytest.mark.asyncio
async def test_send_post_preserves_native_elements_and_extra(monkeypatch):
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    adapter.feed._post_metadata.emojis = {"1": "[微笑]"}
    send = AsyncMock(return_value={"dyn_id_str": "123"})
    monkeypatch.setattr(adapter.get_client(), "send_dynamic", send)
    when = datetime(2030, 1, 1, tzinfo=timezone.utc)
    post = FeedPost(
        MessageChain([Text("hello"), At(42, "user"), Emoji(1), Text("end")]),
        extra={
            "topic_id": 12, "vote_id": 34, "live_reserve_id": 56,
            "send_time": when, "up_choose_comment": True, "close_comment": True,
        },
    )
    assert await adapter.get_capability(FeedCapability).send_post(post) == {"dyn_id_str": "123"}
    draft = send.await_args.args[0]
    assert [item["type"] for item in draft.contents] == [1, 2, 9, 1, 4]
    assert [item["raw_text"] for item in draft.contents[:4]] == ["hello", "@user", "[微笑]", "end"]
    assert draft.contents[-1]["biz_id"] == 34
    assert draft.topic == {"id": 12}
    assert draft.attach_card["biz_id"] == 56
    assert draft.time == when
    assert draft.options == {"up_choose_comment": 1, "close_comment": 1}
    assert post.extra["vote_id"] == 34


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["path", "url", "base64", "data_url"])
async def test_image_sources_and_format_detection(monkeypatch, tmp_path, source):
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    data = image_bytes(format="JPEG")
    if source == "path":
        path = tmp_path / "image.bin"
        path.write_bytes(data)
        value = str(path)
    elif source == "url":
        value = "https://image.test/no-extension"
        fetch = AsyncMock(return_value=data)
        monkeypatch.setattr("core.adapter.src.bilibili.feed.get_file_content", fetch)
    else:
        value = base64.b64encode(data).decode()
        if source == "data_url":
            value = "data:image/jpeg;base64," + value
    send = AsyncMock(return_value={"dyn_id": "image-post"})
    monkeypatch.setattr(adapter.get_client(), "send_dynamic", send)
    await adapter.feed.send_post(FeedPost(MessageChain([Text("photo"), Image(value)])))
    draft = send.await_args.args[0]
    assert draft.get_dynamic_type() is dynamic.SendDynamicType.IMAGE
    assert len(draft.pics) == 1
    picture = draft.pics[0]
    assert (picture.width, picture.height, picture.imageType) == (2, 3, "jpeg")
    assert picture.content == data
    if source == "url":
        fetch.assert_awaited_once_with(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("post", [
    FeedPost(MessageChain()),
    FeedPost(MessageChain([Text("  ")])),
    FeedPost(MessageChain([Text("text")]), extra={"credential": "other-account"}),
    FeedPost(MessageChain([Text("text")]), extra={"topic_id": True}),
    FeedPost(MessageChain([Text("text")]), extra={"vote_id": 0}),
    FeedPost(MessageChain([Text("text")]), extra={"close_comment": 1}),
    FeedPost(MessageChain([Text("text")]), extra={"send_time": datetime(2030, 1, 1)}),
    FeedPost(MessageChain([At("all")])),
    FeedPost(MessageChain([Image("https://image.test/a"), Video("https://video.test/a")])),
])
async def test_invalid_posts_fail_before_loading_media_or_sending(monkeypatch, post):
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    send = AsyncMock()
    load = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_dynamic", send)
    monkeypatch.setattr(adapter.feed, "_load_picture", load)
    with pytest.raises((TypeError, ValueError)):
        await adapter.feed.send_post(post)
    send.assert_not_awaited()
    load.assert_not_awaited()


@pytest.mark.asyncio
async def test_unrecognized_emoji_and_invalid_image_fail_without_publishing(monkeypatch):
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    adapter.feed._post_metadata.emojis = {}
    send = AsyncMock()
    monkeypatch.setattr(adapter.get_client(), "send_dynamic", send)
    with pytest.raises(ValueError, match="native token"):
        await adapter.feed.send_post(FeedPost(MessageChain([Emoji("unknown")])))
    with pytest.raises(ValueError, match="image could not be loaded"):
        await adapter.feed.send_post(FeedPost(MessageChain([Image("data:image/png;base64,aW52YWxpZA==")])))
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_account_credentials_cannot_be_omitted(monkeypatch, sdk_client):
    send = AsyncMock()
    monkeypatch.setattr(dynamic, "send_dynamic", send)
    adapter = make_adapter()
    with pytest.raises(Exception):
        await adapter.get_client().send_dynamic(dynamic.BuildDynamic.empty().add_plain_text("text"))
    with pytest.raises(Exception):
        await adapter.feed.send_post(FeedPost(MessageChain([Text("text")])))
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_client_sanitizes_failure_and_preserves_cancellation(monkeypatch, sdk_client):
    client = make_adapter(sessdata="session", bili_jct="csrf").get_client()
    send = AsyncMock(side_effect=RuntimeError("private-cookie-and-post-body"))
    monkeypatch.setattr(dynamic, "send_dynamic", send)
    draft = dynamic.BuildDynamic.empty().add_plain_text("text")
    with pytest.raises(RuntimeError, match="^Bilibili dynamic publishing failed$") as caught:
        await client.send_dynamic(draft)
    assert caught.value.__suppress_context__
    send.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await client.send_dynamic(draft)
    cancelled = asyncio.Event()

    async def blocked(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    send.side_effect = blocked
    client.timeout = 0.01
    with pytest.raises(TimeoutError, match="publishing timed out"):
        await client.send_dynamic(draft)
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_sdk_payload_keeps_schedule_and_comments_and_cleans_image_files(monkeypatch, sdk_client):
    payloads = []
    upload_paths = []

    class Api:
        def __init__(self, **kwargs):
            self.data = {}
            self.files = {}

        def update_data(self, **data):
            self.data = data
            return self

        def update_params(self, **params):
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
                    return {"image_height": 3, "image_width": 2, "image_url": "https://image.test/uploaded", "img_size": 1}
                payloads.append(self.data["dyn_req"])
                return {"dyn_id_str": "123"}
            return resolve()

    monkeypatch.setattr(dynamic, "Api", Api)
    adapter = make_adapter(sessdata="session", bili_jct="csrf")
    when = datetime(2030, 1, 1, tzinfo=timezone.utc)
    post = FeedPost(
        MessageChain([Image(base64.b64encode(image_bytes()).decode())]),
        extra={"send_time": when, "close_comment": True},
    )
    result = await adapter.feed.send_post(post)
    assert result == {"dyn_id_str": "123"}
    assert payloads[0]["option"] == {"timer_pub_time": int(when.timestamp()), "close_comment": 1}
    assert payloads[0]["scene"] == 2
    assert payloads[0]["pics"] == [{"img_src": "https://image.test/uploaded", "img_width": 2, "img_height": 3}]
    assert upload_paths and all(not path.parent.exists() for path in upload_paths)


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_upload_failure_or_cancellation_cleans_temporary_files(monkeypatch, sdk_client, cancel):
    paths = []

    async def upload(picture, credential):
        paths.append(Path(picture._to_biliapifile().path))
        assert paths[-1].exists()
        if cancel:
            raise asyncio.CancelledError()
        raise RuntimeError("private-upload-error")

    monkeypatch.setattr(dynamic, "upload_image", upload)
    client = make_adapter(sessdata="session", bili_jct="csrf").get_client()
    draft = dynamic.BuildDynamic.empty().add_image(Picture(content=image_bytes(), imageType="png"))
    expected = asyncio.CancelledError if cancel else RuntimeError
    with pytest.raises(expected):
        await client.send_dynamic(draft)
    assert all(not path.parent.exists() for path in paths)


def test_feed_post_extra_is_not_shared():
    first = FeedPost(MessageChain([Text("one")]))
    second = FeedPost(MessageChain([Text("two")]))
    first.extra["topic_id"] = 1
    assert second.extra == {}

@pytest.mark.asyncio
async def test_concurrent_accounts_upload_distinct_files_without_mutating_draft(monkeypatch, sdk_client):
    first = make_adapter(sessdata="account-one", bili_jct="csrf-one")
    second = make_adapter(sessdata="account-two", bili_jct="csrf-two")
    all_entered = asyncio.Event()
    uploads = []

    async def upload(picture, credential):
        path = Path(picture._to_biliapifile().path)
        uploads.append((path, credential, picture.content))
        if len(uploads) == 2:
            all_entered.set()
        await asyncio.wait_for(all_entered.wait(), timeout=2)
        assert path.read_bytes() == picture.content
        return {"image_height": 3, "image_width": 2, "image_url": "https://image.test/uploaded", "img_size": 1}

    monkeypatch.setattr(dynamic, "upload_image", upload)

    async def send(info, credential):
        for picture in info.pics:
            await picture.upload(credential)
        return {"dyn_id": "123"}

    monkeypatch.setattr(dynamic, "send_dynamic", send)
    draft = dynamic.BuildDynamic.empty().add_image(Picture(content=image_bytes(), imageType="png"))
    await asyncio.gather(first.get_client().send_dynamic(draft), second.get_client().send_dynamic(draft))
    assert uploads[0][0] != uploads[1][0]
    assert {id(entry[1]) for entry in uploads} == {id(first.credential), id(second.credential)}
    assert all(not path.parent.exists() for path, _, _ in uploads)
    assert type(draft.pics[0]) is Picture
    assert draft.pics[0].url == ""


@pytest.mark.asyncio
async def test_cancel_during_file_preparation_waits_for_cleanup(monkeypatch, sdk_client):
    import threading

    loop = asyncio.get_running_loop()
    prepared = asyncio.Event()
    release = threading.Event()
    paths = []
    original = client_module._BiliBiliPicture._prepare_upload

    def prepare(picture):
        directory, file = original(picture)
        paths.append(Path(file.path))
        loop.call_soon_threadsafe(prepared.set)
        release.wait(timeout=2)
        return directory, file

    monkeypatch.setattr(client_module._BiliBiliPicture, "_prepare_upload", prepare)
    upload = AsyncMock()
    monkeypatch.setattr(dynamic, "upload_image", upload)
    client = make_adapter(sessdata="session", bili_jct="csrf").get_client()
    draft = dynamic.BuildDynamic.empty().add_image(Picture(content=image_bytes(), imageType="png"))
    task = asyncio.create_task(client.send_dynamic(draft))
    try:
        await asyncio.wait_for(prepared.wait(), timeout=2)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert paths and all(not path.parent.exists() for path in paths)
    upload.assert_not_awaited()
