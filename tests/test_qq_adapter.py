"""Tests for the OneBot QQ adapter's inbound message processing
(core/adapter/src/qq/qq.py).

Focus: a failing sticker download or a missing quoted message must degrade
that one segment/event instead of aborting the whole incoming message.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import core.utils.common_utils as common_utils
from core.adapter.src.qq.qq import QQAdapter
from core.chat.message_elements import Image, Text

pytestmark = pytest.mark.asyncio


def make_adapter(config: dict = None) -> QQAdapter:
    info = SimpleNamespace(name="qq", config=config or {})
    return QQAdapter(info, asyncio.Queue())


async def test_sticker_download_failure_skips_sticker_and_keeps_rest(monkeypatch: pytest.MonkeyPatch):
    adapter = make_adapter()

    async def boom(image_path: str) -> str:
        raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(common_utils, "image_to_base64", boom)

    chain = await adapter.process_incoming_message({
        "message_type": "group",
        "group_id": 123,
        "message": [
            {"type": "image", "data": {"url": "https://expired.example/a.jpg", "sub_type": 1, "summary": "[动画表情]"}},
            {"type": "text", "data": {"text": "after"}},
        ],
    })

    # The failed sticker is logged and skipped; the following segments survive.
    assert len(chain) == 1
    assert isinstance(chain[0], Text)
    assert chain[0].text == "after"


async def test_empty_url_sticker_is_skipped_without_mock():
    """An empty sticker url hits the real image_to_base64 open('') path; the
    branch must still skip the segment instead of raising out of the loop."""
    adapter = make_adapter()

    chain = await adapter.process_incoming_message({
        "message_type": "private",
        "message": [
            {"type": "image", "data": {"url": "", "summary": "[动画表情]"}},
        ],
    })

    assert len(chain) == 0


async def test_regular_image_skips_download(monkeypatch: pytest.MonkeyPatch):
    adapter = make_adapter()

    async def boom(image_path: str) -> str:
        raise AssertionError("regular image must not be downloaded at receive time")

    monkeypatch.setattr(common_utils, "image_to_base64", boom)

    chain = await adapter.process_incoming_message({
        "message_type": "group",
        "group_id": 123,
        "message": [
            {"type": "image", "data": {"url": "https://example.com/pic.jpg", "sub_type": 0, "summary": "[图片]"}},
        ],
    })

    assert len(chain) == 1
    assert isinstance(chain[0], Image)


async def test_mention_check_survives_missing_quoted_message():
    """get_msg failing for the quoted message only skips the mention check;
    the message itself must still be processed and published."""
    adapter = make_adapter(config={"group_allow_list": ["123"]})
    adapter.bot = AsyncMock()
    adapter.bot.get_msg = AsyncMock(side_effect=TimeoutError("请求 get_msg 超时"))
    adapter.bot.get_user_info = AsyncMock(return_value={"data": {"nickname": "u"}})
    adapter.bot.get_group_info = AsyncMock(return_value={"data": {"group_name": "g"}})

    await adapter._on_group_message({
        "message_type": "group",
        "group_id": 123,
        "user_id": 456,
        "self_id": 10000,
        "time": 1700000000,
        "message_id": "m1",
        "sender": {"nickname": "alice"},
        "message": [
            {"type": "reply", "data": {"id": "999"}},
            {"type": "text", "data": {"text": "hi"}},
        ],
    })

    event = adapter._event_queue.get_nowait()
    chain_repr = "".join(ele.repr for ele in event.message.chain)
    assert "hi" in chain_repr
