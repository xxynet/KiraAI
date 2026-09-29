from __future__ import annotations

import asyncio

import pytest

from core.adapter.adapter_info import AdapterInfo
from core.adapter.access import AccessController, ListAccessPolicy
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
        await self.adapter.send_payload(self.capability_type, group_id, message)

    async def send_direct_message(self, user_id, message):
        await self.adapter.send_payload(self.capability_type, user_id, message)


class ExampleFeed(FeedCapability["ExampleAdapter"]):
    async def get_feed(self, count):
        return self.adapter.posts[:count]

    async def search_feed(self, keyword, count):
        return [post for post in self.adapter.posts if keyword in post][:count]

    async def send_comment(self, text, root, sub=None):
        await self.adapter.send_payload(self.capability_type, root, (text, sub))


class ExampleAdapter(BaseAdapter):
    def __init__(self, ctx):
        super().__init__(ctx)
        self.message_types = ["text"]
        self.sent = []
        self.posts = ["first post", "second post"]
        if self.config.get("enable_im", True):
            self.im = self.register_capability(IMCapability, ExampleIM(self))
        if self.config.get("enable_qzone"):
            self.register_capability(FeedCapability, ExampleFeed(self))

    async def send_payload(self, capability_type, target, payload):
        self.sent.append((capability_type, target, payload))

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
    enabled = make_adapter(enable_qzone=True)

    assert set(disabled.capabilities) == {IMCapability}
    assert set(enabled.capabilities) == {IMCapability, FeedCapability}
    with pytest.raises(ValueError, match="Expected one FeedCapability, found 0"):
        disabled.get_capability(FeedCapability)


@pytest.mark.asyncio
async def test_im_lookup_by_type_does_not_require_a_registration_name():
    adapter = make_adapter()
    im = adapter.get_capability(IMCapability)
    channel = adapter.get_capability(ExampleIM)

    assert im is adapter.im
    assert im is channel
    assert im.adapter is channel.adapter is adapter
    await im.send_direct_message("user", [])
    await channel.send_group_message("channel", [])
    assert adapter.sent == [(IMCapability, "user", []), (IMCapability, "channel", [])]


@pytest.mark.asyncio
async def test_feed_object_includes_comments_and_uses_adapter_members():
    adapter = make_adapter(enable_qzone=True)
    feed = adapter.get_capability(FeedCapability)

    assert await feed.get_feed(1) == ["first post"]
    assert await feed.search_feed("second", 1) == ["second post"]
    await feed.send_comment("reply", "post", "comment")
    assert adapter.sent == [(FeedCapability, "post", ("reply", "comment"))]


def test_lookup_returns_the_matching_capability_type():
    adapter = make_adapter(enable_qzone=True)
    assert adapter.get_capability(IMCapability) is adapter.im
    assert adapter.get_capability(capability_type=ExampleIM) is adapter.im
    assert isinstance(adapter.get_capability(FeedCapability), ExampleFeed)


def test_lookup_rejects_missing_capability_types():
    adapter = make_adapter()
    with pytest.raises(ValueError, match="Expected one FeedCapability, found 0"):
        adapter.get_capability(FeedCapability)


@pytest.mark.parametrize("invalid_type", [None, "im", str, (IMCapability,)])
def test_lookup_requires_a_capability_class(invalid_type):
    with pytest.raises(TypeError, match="BaseCapability subclass"):
        make_adapter().get_capability(invalid_type)


def test_lookup_rejects_an_ambiguous_base_type():
    with pytest.raises(ValueError, match="Expected one BaseCapability, found 2"):
        make_adapter(enable_qzone=True).get_capability(BaseCapability)


def test_duplicate_registration_cannot_replace_existing_object():
    adapter = make_adapter()
    replacement = ExampleIM(adapter)
    with pytest.raises(ValueError, match="already registered"):
        adapter.register_capability(IMCapability, replacement)
    assert adapter.get_capability(IMCapability) is adapter.im
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = replacement.capability_type


@pytest.mark.parametrize("implementation", [ExampleIM, type("OtherIM", (ExampleIM,), {})])
def test_duplicate_kind_is_rejected_even_with_a_different_registration_type(implementation):
    adapter = make_adapter()
    replacement = implementation(adapter)
    with pytest.raises(ValueError, match="kind is already registered"):
        adapter.register_capability(implementation, replacement)
    assert adapter.get_capabilities() == {IMCapability: adapter.im}
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = replacement.capability_type


@pytest.mark.parametrize(
    "capability_type", [IMCapability, FeedCapability, LiveEventCapability, VoiceChannelCapability],
)
def test_sibling_implementations_share_the_same_capability_kind(capability_type):
    implementations = [
        type(name, (capability_type,), {
            method: (lambda *args, **kwargs: None)
            for method in capability_type.__abstractmethods__
        })
        for name in ("FirstImplementation", "SecondImplementation")
    ]
    adapter = make_adapter(enable_im=False)
    first = adapter.register_capability(capability_type, implementations[0](adapter))
    with pytest.raises(ValueError, match="kind is already registered"):
        adapter.register_capability(capability_type, implementations[1](adapter))
    assert adapter.get_capability(capability_type) is first


def test_custom_capability_kinds_are_independent_and_unique():
    class CustomCapability(BaseCapability):
        pass

    class CustomImplementation(CustomCapability):
        pass

    class OtherCapability(BaseCapability):
        pass

    adapter = make_adapter()
    custom = adapter.register_capability(CustomCapability, CustomCapability(adapter))
    adapter.register_capability(OtherCapability, OtherCapability(adapter))
    with pytest.raises(ValueError, match="kind is already registered"):
        adapter.register_capability(CustomImplementation, CustomImplementation(adapter))
    assert adapter.get_capability(CustomCapability) is custom


@pytest.mark.parametrize("combined_first", [False, True])
def test_combined_implementation_cannot_bypass_kind_uniqueness(combined_first):
    class CombinedCapability(ExampleIM, ExampleFeed):
        pass

    adapter = make_adapter(enable_im=False)
    first_type, second_type = (
        (CombinedCapability, ExampleFeed) if combined_first
        else (ExampleIM, CombinedCapability)
    )
    first = adapter.register_capability(first_type, first_type(adapter))
    with pytest.raises(ValueError, match="kind is already registered"):
        adapter.register_capability(second_type, second_type(adapter))
    assert adapter.get_capabilities() == {first_type: first}


def test_capability_discovery_filters_types_and_returns_a_snapshot():
    adapter = make_adapter(enable_qzone=True)
    capabilities = adapter.get_capabilities()
    assert set(capabilities) == {IMCapability, FeedCapability}
    assert adapter.get_capabilities(IMCapability) == {IMCapability: adapter.im}
    assert adapter.get_capabilities(VoiceChannelCapability) == {}
    capabilities.clear()
    assert set(adapter.capabilities) == {IMCapability, FeedCapability}


def test_capability_cannot_be_shared_between_accounts_or_registered_twice():
    adapter = make_adapter()
    other = make_adapter()
    with pytest.raises(ValueError, match="another adapter"):
        other.register_capability(IMCapability, adapter.im)
    with pytest.raises(ValueError, match="already registered"):
        adapter.register_capability(ExampleIM, adapter.im)
    assert adapter.im.capability_type is IMCapability
    assert set(other.capabilities) == {IMCapability}


@pytest.mark.parametrize("invalid_type", [None, "im", str, (IMCapability,)])
def test_registration_requires_a_capability_class(invalid_type):
    adapter = make_adapter(enable_im=False)
    with pytest.raises(TypeError, match="BaseCapability subclass"):
        adapter.register_capability(invalid_type, ExampleIM(adapter))
    assert not adapter.capabilities


def test_registration_rejects_an_instance_of_another_capability_type():
    adapter = make_adapter(enable_im=False)
    capability = ExampleFeed(adapter)
    with pytest.raises(TypeError, match="instance of capability_type"):
        adapter.register_capability(IMCapability, capability)
    assert not adapter.capabilities
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = capability.capability_type


def test_registration_requires_an_instance_and_registry_is_read_only():
    adapter = make_adapter()
    with pytest.raises(TypeError, match="BaseCapability instance"):
        adapter.register_capability(IMCapability, ExampleIM)
    with pytest.raises(TypeError):
        adapter.capabilities[IMCapability] = ExampleIM(adapter)


def test_registration_has_no_capability_name():
    adapter = make_adapter()
    assert not hasattr(adapter.im, "name")
    assert not hasattr(adapter.im, "_name")
    assert adapter.capabilities[IMCapability] is adapter.im


def test_capability_permissions_use_registered_type_and_are_account_local():
    adapter = make_adapter(enable_qzone=True)
    other = make_adapter()
    adapter.access.set_policy(
        capability_type=IMCapability,
        permission="im.direct.receive",
        policy=ListAccessPolicy.from_lists("allow_list", allow_list=[123]),
    )
    assert adapter.im.is_allowed("123", permission="im.direct.receive")
    assert not adapter.im.is_allowed("456", permission="im.direct.receive")
    assert not adapter.im.is_allowed("123", permission="im.direct.send")
    assert not adapter.get_capability(FeedCapability).is_allowed(
        "123", permission="im.direct.receive",
    )
    assert not other.im.is_allowed("123", permission="im.direct.receive")


def test_unregistered_capability_cannot_check_permissions():
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


@pytest.mark.parametrize("invalid_type", [None, "im", str, (IMCapability,)])
def test_access_policies_reject_non_capability_types(invalid_type):
    controller = AccessController()
    policy = ListAccessPolicy.from_lists("allow_list", allow_list=[123])
    with pytest.raises(TypeError, match="BaseCapability subclass"):
        controller.set_policy(
            capability_type=invalid_type, permission="receive", policy=policy,
        )
    with pytest.raises(TypeError, match="BaseCapability subclass"):
        controller.is_allowed(123, capability_type=invalid_type, permission="receive")


def test_permissions_are_normalized_and_empty_permissions_are_rejected():
    adapter = make_adapter()
    policy = ListAccessPolicy.from_lists("allow_list", allow_list=[123])
    adapter.access.set_policy(
        capability_type=IMCapability, permission=" receive ", policy=policy,
    )
    assert adapter.im.is_allowed(123, permission="receive")
    assert adapter.im.is_allowed(123, permission=" receive ")
    with pytest.raises(ValueError, match="permission must not be empty"):
        adapter.access.set_policy(
            capability_type=IMCapability, permission=" ", policy=policy,
        )
    with pytest.raises(ValueError, match="permission must not be empty"):
        adapter.im.is_allowed(123, permission=" ")

def test_broad_registration_type_cannot_overwrite_another_kind():
    adapter = make_adapter(enable_im=False)
    first = adapter.register_capability(BaseCapability, ExampleIM(adapter))
    replacement = ExampleFeed(adapter)
    with pytest.raises(ValueError, match="already registered"):
        adapter.register_capability(BaseCapability, replacement)
    assert adapter.get_capabilities() == {BaseCapability: first}
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = replacement.capability_type


def test_custom_capability_permissions_use_type_identity():
    adapter = make_adapter(enable_im=False)
    first_type = type("CustomCapability", (BaseCapability,), {})
    second_type = type("CustomCapability", (BaseCapability,), {})
    first = adapter.register_capability(first_type, first_type(adapter))
    second = adapter.register_capability(second_type, second_type(adapter))
    adapter.access.set_policy(
        capability_type=first_type, permission="receive",
        policy=ListAccessPolicy.from_lists("allow_list", allow_list=[123]),
    )
    assert first.is_allowed(123, permission="receive")
    assert not second.is_allowed(123, permission="receive")
