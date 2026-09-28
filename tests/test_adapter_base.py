from __future__ import annotations

import asyncio

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.adapter.access import ListAccessPolicy
from core.adapter.base import BaseAdapter, BaseCapability
from core.adapter.capabilities import (
    FeedCapability,
    IMCapability,
    LiveEventCapability,
    VoiceChannelCapability,
)
from core.adapter.context import AdapterContext


class ExampleIM(IMCapability["ExampleAdapter"]):
    async def send_group_message(self, group_id, message):
        await self.adapter.send_payload(self.name, group_id, message)

    async def send_direct_message(self, user_id, message):
        await self.adapter.send_payload(self.name, user_id, message)


class ExampleFeed(FeedCapability["ExampleAdapter"]):
    async def get_feed(self, count):
        return self.adapter.posts[:count]

    async def search_feed(self, keyword, count):
        return [post for post in self.adapter.posts if keyword in post][:count]

    async def send_comment(self, text, root, sub=None):
        await self.adapter.send_payload(self.name, root, (text, sub))


class ExampleAdapter(BaseAdapter):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.sent = []
        self.posts = ["first post", "second post"]
        self.im = self.register_capability("im", ExampleIM(self))
        if self.config.get("enable_channel"):
            self.register_capability("qq-channel", ExampleIM(self))
        if self.config.get("enable_qzone"):
            self.register_capability("qzone", ExampleFeed(self))

    async def send_payload(self, name, target, payload):
        self.sent.append((name, target, payload))

    async def start(self):
        pass

    async def stop(self):
        pass

    def get_client(self):
        return None


def make_adapter(**config):
    return ExampleAdapter(AdapterContext(
        info=AdapterInfo(True, "example", "example", "qq", config=config),
        event_queue=asyncio.Queue(),
    ))


def test_adapter_config_decides_which_objects_are_registered():
    disabled = make_adapter()
    enabled = make_adapter(enable_channel=True, enable_qzone=True)

    assert set(disabled.capabilities) == {"im"}
    assert set(enabled.capabilities) == {"im", "qq-channel", "qzone"}
    with pytest.raises(KeyError):
        disabled.get_capability("qzone")


@pytest.mark.asyncio
async def test_two_im_objects_route_to_their_own_names_and_share_adapter():
    adapter = make_adapter(enable_channel=True)
    im = adapter.get_capability("im", IMCapability)
    channel = adapter.get_capability("qq-channel", ExampleIM)

    assert im is adapter.im
    assert im is not channel
    assert im.adapter is channel.adapter is adapter
    await im.send_direct_message("user", [])
    await channel.send_group_message("channel", [])
    assert adapter.sent == [("im", "user", []), ("qq-channel", "channel", [])]


@pytest.mark.asyncio
async def test_feed_object_includes_comments_and_uses_adapter_members():
    adapter = make_adapter(enable_qzone=True)
    feed = adapter.get_capability("qzone", FeedCapability)

    assert await feed.get_feed(1) == ["first post"]
    assert await feed.search_feed("second", 1) == ["second post"]
    await feed.send_comment("reply", "post", "comment")
    assert adapter.sent == [("qzone", "post", ("reply", "comment"))]


def test_lookup_checks_expected_capability_type():
    adapter = make_adapter()
    with pytest.raises(TypeError, match="not a FeedCapability"):
        adapter.get_capability("im", FeedCapability)


def test_duplicate_registration_cannot_replace_existing_object():
    adapter = make_adapter()
    replacement = ExampleIM(adapter)
    with pytest.raises(ValueError, match="already registered"):
        adapter.register_capability("im", replacement)
    assert adapter.get_capability("im") is adapter.im
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = replacement.name


def test_capability_cannot_be_shared_between_accounts_or_names():
    adapter = make_adapter()
    other = make_adapter()
    with pytest.raises(ValueError, match="another adapter"):
        other.register_capability("shared", adapter.im)
    with pytest.raises(ValueError, match="already registered"):
        adapter.register_capability("alias", adapter.im)
    assert adapter.im.name == "im"
    assert set(other.capabilities) == {"im"}


@pytest.mark.parametrize("name", ["", "   ", None])
def test_invalid_names_are_rejected_without_registering(name):
    adapter = make_adapter()
    with pytest.raises(ValueError, match="non-empty string"):
        adapter.register_capability(name, ExampleIM(adapter))
    assert set(adapter.capabilities) == {"im"}


def test_registration_requires_an_instance_and_registry_is_read_only():
    adapter = make_adapter()
    with pytest.raises(TypeError, match="BaseCapability instance"):
        adapter.register_capability("class", ExampleIM)
    with pytest.raises(TypeError):
        adapter.capabilities["injected"] = ExampleIM(adapter)


def test_registration_and_lookup_normalize_names_consistently():
    adapter = make_adapter()
    capability = adapter.register_capability(" custom ", BaseCapability(adapter))
    assert capability.name == "custom"
    assert adapter.get_capability(" custom ") is capability


def test_capability_permissions_use_registration_name_and_are_account_local():
    adapter = make_adapter(enable_channel=True)
    other = make_adapter()
    adapter.access.set_policy(
        domain="im",
        permission="im.direct.receive",
        policy=ListAccessPolicy.from_lists("allow_list", allow_list=[123]),
    )
    assert adapter.im.is_allowed("123", permission="im.direct.receive")
    assert not adapter.im.is_allowed("456", permission="im.direct.receive")
    assert not adapter.im.is_allowed("123", permission="im.direct.send")
    assert not adapter.get_capability("qq-channel").is_allowed(
        "123", permission="im.direct.receive",
    )
    assert not other.im.is_allowed("123", permission="im.direct.receive")


def test_unregistered_capability_cannot_use_a_permission_namespace():
    adapter = make_adapter()
    with pytest.raises(RuntimeError, match="not been registered"):
        ExampleIM(adapter).is_allowed("123", permission="im.direct.receive")


@pytest.mark.parametrize("mode", ["allow_list", "deny_list", "invalid"])
def test_list_policy_modes_and_identifier_normalization(mode):
    policy = ListAccessPolicy.from_lists(mode, allow_list=[123], deny_list=[456])
    assert policy.allows("123")
    assert not policy.allows(456)
    assert policy.allows("other") is (mode == "deny_list")
    assert not policy.allows(None)


@pytest.mark.parametrize(
    "capability_type", [IMCapability, FeedCapability, LiveEventCapability, VoiceChannelCapability],
)
def test_capabilities_require_implementing_their_abstract_operations(capability_type):
    with pytest.raises(TypeError, match="abstract"):
        capability_type(make_adapter())


def test_adapter_publishes_events_through_context():
    adapter = make_adapter()
    event = object()
    adapter.im.adapter.publish(event)
    assert adapter.ctx.event_queue.get_nowait() is event
