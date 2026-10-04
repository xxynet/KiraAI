import asyncio
import importlib
from unittest.mock import Mock

import pytest

from core.adapter import MessageFormatMetadata
from core.adapter.message_format_metadata import load_emoji_mapping
from tests.test_bilibili_adapter import make_adapter as make_bilibili
from tests.test_qq_adapter import make_adapter as make_qq
from tests.test_qq_official_adapter import make_adapter as make_qq_official
from tests.test_weixin_oc_adapter import make_adapter as make_weixin


def test_metadata_is_a_snapshot_of_caller_owned_containers():
    types = ["text", "custom-format"]
    emojis = {"opaque:id": "smile"}
    metadata = MessageFormatMetadata(types, emojis=emojis)
    types.append("img")
    emojis["opaque:id"] = "changed"
    assert metadata.supported_elements == ["text", "custom-format"]
    metadata.supported_elements.append("caller-added")
    assert types == ["text", "custom-format", "img"]
    assert metadata.supported_elements == ["text", "custom-format", "caller-added"]
    metadata.supported_elements.remove("caller-added")
    assert metadata.emojis == {"opaque:id": "smile"}
    metadata.emojis["opaque:id"] = "updated"
    metadata.emojis["new"] = "new emoji"
    assert emojis == {"opaque:id": "changed"}
    assert metadata.emojis == {"opaque:id": "updated", "new": "new emoji"}
    del metadata.emojis["new"]
    metadata.emojis = {"replacement": "replacement emoji"}
    assert metadata.emojis == {"replacement": "replacement emoji"}


def test_default_supported_element_lists_are_independent():
    first, second = MessageFormatMetadata(), MessageFormatMetadata()
    first.supported_elements.append("text")
    assert first.supported_elements == ["text"]
    assert second.supported_elements == []


def test_unsupported_emoji_differs_from_an_empty_catalog():
    assert MessageFormatMetadata().emojis is None
    metadata = MessageFormatMetadata(["emoji"], emojis={})
    assert metadata.emojis == {}


def test_local_catalog_is_loaded_as_a_mutable_dictionary(tmp_path):
    path = tmp_path / "emoji.json"
    path.write_text('{"1": "smile"}', encoding="utf-8")
    emojis = load_emoji_mapping(path)
    assert emojis == {"1": "smile"}
    emojis["1"] = "changed"
    assert emojis == {"1": "changed"}


@pytest.mark.parametrize("content,error", [
    ("[]", TypeError), ('{"1": ["nested"]}', TypeError), ("{invalid", ValueError),
])
def test_invalid_catalogs_raise_instead_of_becoming_empty(tmp_path, content, error):
    path = tmp_path / "emoji.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(error):
        load_emoji_mapping(path)


@pytest.mark.asyncio
@pytest.mark.parametrize("factory,module_name", [
    (make_qq, "core.adapter.src.qq.im"),
    (make_bilibili, "core.adapter.src.bilibili.im"),
])
async def test_im_loads_once_during_construction_and_queries_use_loaded_data(monkeypatch, factory, module_name):
    module = importlib.import_module(module_name)
    loader = Mock(side_effect=lambda _: {"1": "capability emoji"})
    monkeypatch.setattr(module, "load_emoji_mapping", loader)
    first, second = factory(), factory()
    assert loader.call_count == 2
    assert first.im._metadata.emojis is not second.im._metadata.emojis
    loader.side_effect = AssertionError("Metadata queries must not reload emojis")
    snapshots = await asyncio.gather(*(first.im.get_message_metadata() for _ in range(5)))
    other = await second.im.get_message_metadata()
    assert all(snapshot.emojis == {"1": "capability emoji"} for snapshot in snapshots)
    assert other.emojis is not snapshots[0].emojis
    for adapter in (first, second):
        assert not hasattr(adapter, "_emoji_mapping")
        assert not hasattr(adapter, "_emoji_load_lock")
        assert not hasattr(adapter, "emoji_dict")
        assert not hasattr(adapter, "emojis")
    snapshots[0].supported_elements.append("caller-added")
    snapshots[0].emojis["1"] = "caller change"
    assert "caller-added" not in snapshots[1].supported_elements
    assert snapshots[1].emojis == {"1": "capability emoji"}
    assert first.im._metadata.emojis == {"1": "capability emoji"}
    first.im._metadata.emojis["1"] = "capability change"
    assert (await first.im.get_message_metadata()).emojis == {"1": "capability change"}
    assert other.emojis == {"1": "capability emoji"}

@pytest.mark.parametrize("factory,module_name", [
    (make_qq, "core.adapter.src.qq.im"),
    (make_bilibili, "core.adapter.src.bilibili.im"),
])
def test_catalog_loading_failure_is_reported_during_initialization(monkeypatch, factory, module_name):
    module = importlib.import_module(module_name)
    monkeypatch.setattr(module, "load_emoji_mapping", Mock(side_effect=OSError("unavailable")))
    with pytest.raises(OSError, match="unavailable"):
        factory()


@pytest.mark.asyncio
async def test_feed_loads_during_construction_without_im_and_queries_do_not_reload(monkeypatch):
    module = importlib.import_module("core.adapter.src.bilibili.feed")
    im_module = importlib.import_module("core.adapter.src.bilibili.im")
    loader = Mock(wraps=module.load_emoji_mapping)
    im_loader = Mock(side_effect=AssertionError("Disabled IM must not load metadata"))
    monkeypatch.setattr(module, "load_emoji_mapping", loader)
    monkeypatch.setattr(im_module, "load_emoji_mapping", im_loader)
    adapter = make_bilibili(enable_im=False)
    loader.assert_called_once()
    im_loader.assert_not_called()
    assert not hasattr(adapter, "emojis")
    loader.side_effect = AssertionError("Feed queries must not reload emojis")
    comment, post = await asyncio.gather(
        adapter.feed.get_comment_metadata(), adapter.feed.get_post_metadata(),
    )
    assert comment.supported_elements == ["text", "img", "emoji"]
    assert post.supported_elements == ["text", "img", "emoji", "at"]
    assert comment.emojis["1"] == "[微笑]"
    assert comment.emojis == post.emojis
    comment.emojis["1"] = "caller-change"
    assert post.emojis["1"] == "[微笑]"
    adapter.feed._comment_metadata.emojis["1"] = "comment-change"
    assert (await adapter.feed.get_comment_metadata()).emojis["1"] == "comment-change"
    assert (await adapter.feed.get_post_metadata()).emojis["1"] == "[微笑]"
    assert adapter.im is None
    assert adapter.listening_task is None and adapter._comment_task is None
    assert adapter._dm_task is None and adapter._dm_session is None
    assert adapter._event_queue.empty()


@pytest.mark.asyncio
async def test_bilibili_im_and_feed_construct_independent_metadata(monkeypatch):
    im_module = importlib.import_module("core.adapter.src.bilibili.im")
    feed_module = importlib.import_module("core.adapter.src.bilibili.feed")
    im_loader = Mock(return_value={"1": "IM emoji"})
    feed_loader = Mock(return_value={"1": "feed emoji"})
    monkeypatch.setattr(im_module, "load_emoji_mapping", im_loader)
    monkeypatch.setattr(feed_module, "load_emoji_mapping", feed_loader)
    adapter = make_bilibili()
    im_loader.assert_called_once()
    feed_loader.assert_called_once()
    im_loader.side_effect = feed_loader.side_effect = AssertionError("Queries must not reload metadata")
    assert (await adapter.im.get_message_metadata()).emojis == {"1": "IM emoji"}
    assert (await adapter.feed.get_comment_metadata()).emojis == {"1": "feed emoji"}
    assert (await adapter.feed.get_post_metadata()).emojis == {"1": "feed emoji"}
    adapter.im._metadata.emojis["1"] = "IM change"
    assert (await adapter.feed.get_comment_metadata()).emojis == {"1": "feed emoji"}

@pytest.mark.asyncio
@pytest.mark.parametrize("factory", [make_qq, make_qq_official, make_weixin, make_bilibili])
async def test_legacy_adapter_elements_are_live_and_synchronized_with_metadata(factory):
    first, second = factory(), factory()
    original = list(first.im._supported_elements)
    with pytest.warns(DeprecationWarning, match="message_types is deprecated"):
        live_elements = first.message_types
    assert live_elements == original
    assert live_elements is first.im._supported_elements
    assert not hasattr(first, '_emoji_mapping')
    assert not hasattr(first, '_emoji_load_lock')
    live_elements.append("legacy-custom")
    assert (await first.im.get_message_metadata()).supported_elements == original + ["legacy-custom"]
    assert second.im._supported_elements == original
    assert first.im._SUPPORTED_ELEMENTS == original
    replacement = ["text", "replacement-custom"]
    with pytest.warns(DeprecationWarning, match="message_types is deprecated"):
        first.message_types = replacement
    replacement.append("in-place-custom")
    assert (await first.im.get_message_metadata()).supported_elements == replacement
    with pytest.warns(DeprecationWarning, match="message_types is deprecated"):
        assert first.message_types is replacement
    snapshot = await first.im.get_message_metadata()
    snapshot.supported_elements.append("snapshot-custom")
    assert "snapshot-custom" not in replacement
