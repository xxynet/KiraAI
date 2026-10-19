"""Policy ownership across concurrent and overdue capability lifecycle hooks."""

import asyncio

import pytest

from core.adapter import AdapterContext, BaseCapability
from core.adapter.access import AccessController, ListAccessPolicy
from core.adapter.adapter_info import AdapterInfo
from tests.test_adapter_base import ExampleAdapter
from tests.test_adapter_capability_extensions import account, manager


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["native", "plugin"])
@pytest.mark.parametrize("hook", ["initialize", "terminate"])
@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize("reuse_installed_policy", [False, True])
async def test_lifecycle_rollback_preserves_external_policy_writes(
    manager, monkeypatch, origin, hook, deferred, reuse_installed_policy,
):
    from core.adapter import capability_registry as module

    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01 if deferred else 1)
    monkeypatch.setattr(module, "CAPABILITY_CANCELLATION_GRACE", 0.01)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    installed = ListAccessPolicy("deny_list", frozenset())
    later = installed if reuse_installed_policy else ListAccessPolicy(
        "allow_list", frozenset({"external"}),
    )
    capabilities = manager.capability_registry

    async def pause():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()

    class Kind(BaseCapability):
        async def initialize(self):
            self.adapter.access.set_policy(
                capability_type=Kind, permission="post", policy=installed,
            )
            self.adapter.access.set_policy(
                capability_type=Kind, permission="temporary", policy=installed,
            )
            if hook == "initialize":
                await pause()

        async def terminate(self):
            if hook == "terminate":
                await pause()

    adapter = await account(manager) if origin == "plugin" else ExampleAdapter(AdapterContext(
        AdapterInfo(True, "native", "native", "qq"), asyncio.Queue(),
    ))
    adapter.access.set_policy(capability_type=Kind, permission="post", policy=original)

    async def register():
        if origin == "native":
            adapter.register_capability(Kind, Kind(adapter))
            await capabilities.initialize_native(adapter)
        else:
            await capabilities.register("plugin", "qq", Kind, Kind)

    async def unregister():
        if origin == "native":
            await capabilities.detach(adapter)
        else:
            await capabilities.unregister_owner("plugin")

    if hook == "initialize":
        pending = asyncio.create_task(register())
    else:
        await register()
        pending = asyncio.create_task(unregister())
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if deferred:
            if hook == "initialize":
                with pytest.raises(asyncio.TimeoutError):
                    await pending
            else:
                await pending
        adapter.access.set_policy(capability_type=Kind, permission="post", policy=later)
        adapter.access.set_policy(capability_type=Kind, permission="external_only", policy=later)
        release.set()
        if not deferred:
            await pending
            if hook == "initialize":
                await unregister()
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)
        await asyncio.gather(*capabilities._hook_tasks, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.gather(*capabilities._cleanup_tasks, return_exceptions=True)
        await asyncio.sleep(0)

    policies = adapter.access.get_policies(Kind)
    assert policies == {"post": later, "external_only": later}
    assert policies["post"] is later
    assert not capabilities._hook_tasks
    assert not capabilities._cleanup_tasks
    assert not capabilities._pending_cleanup

@pytest.mark.parametrize("repeated", [False, True])
def test_owned_rewrite_restores_intervening_external_policy(repeated):
    class Kind(BaseCapability):
        pass

    access = AccessController()
    original = ListAccessPolicy("allow_list", frozenset({"original"}))
    external = ListAccessPolicy("allow_list", frozenset({"external"}))
    installed = ListAccessPolicy("deny_list", frozenset())
    access.set_policy(capability_type=Kind, permission="post", policy=original)
    changes = access.track_policies(Kind)
    with changes.record():
        access.set_policy(capability_type=Kind, permission="post", policy=installed)
    access.set_policy(capability_type=Kind, permission="post", policy=external)
    with changes.record():
        for _ in range(3 if repeated else 1):
            access.set_policy(capability_type=Kind, permission="post", policy=installed)
    changes.restore()
    assert access.get_policies(Kind) == {"post": external}
    changes.restore()
    assert access.get_policies(Kind) == {"post": external}


def test_policy_recording_is_scoped_to_controller_and_kind():
    class First(BaseCapability):
        pass

    class Second(BaseCapability):
        pass

    access, other = AccessController(), AccessController()
    policy = ListAccessPolicy("allow_list", frozenset({"owner"}))
    changes = access.track_policies(First)
    with changes.record():
        access.set_policy(capability_type=First, permission="post", policy=policy)
        access.set_policy(capability_type=Second, permission="post", policy=policy)
        other.set_policy(capability_type=First, permission="post", policy=policy)
    changes.restore()
    assert not access.get_policies(First)
    assert access.get_policies(Second) == {"post": policy}
    assert other.get_policies(First) == {"post": policy}


def test_policy_recording_context_resets_after_exception():
    class Kind(BaseCapability):
        pass

    access = AccessController()
    policy = ListAccessPolicy("allow_list", frozenset({"owner"}))
    changes = access.track_policies(Kind)
    with pytest.raises(RuntimeError), changes.record():
        access.set_policy(capability_type=Kind, permission="post", policy=policy)
        raise RuntimeError("recording interrupted")
    access.set_policy(capability_type=Kind, permission="post", policy=policy)
    changes.restore()
    assert access.get_policies(Kind) == {"post": policy}


def test_nested_policy_recordings_restore_each_owners_version():
    class Kind(BaseCapability):
        pass

    access = AccessController()
    original = ListAccessPolicy("allow_list", frozenset({"original"}))
    outer_policy = ListAccessPolicy("allow_list", frozenset({"outer"}))
    inner_policy = ListAccessPolicy("allow_list", frozenset({"inner"}))
    access.set_policy(capability_type=Kind, permission="post", policy=original)
    outer, inner = access.track_policies(Kind), access.track_policies(Kind)
    with outer.record():
        access.set_policy(capability_type=Kind, permission="post", policy=outer_policy)
        with inner.record():
            access.set_policy(capability_type=Kind, permission="post", policy=inner_policy)
        inner.restore()
        assert access.get_policies(Kind) == {"post": outer_policy}
    outer.restore()
    assert access.get_policies(Kind) == {"post": original}
