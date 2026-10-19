"""Lifecycle coverage for plugin capabilities on existing and future accounts."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from core.adapter import AdapterManager, BaseCapability, FeedCapability, IMCapability
from core.adapter.access import ListAccessPolicy
from core.adapter.adapter_info import AdapterInfo
from core.plugin import PluginContext, PluginManager, registry
from core.plugin import manager as plugin_manager_module
from tests.test_adapter_base import ExampleAdapter, ExampleFeed


class ExtensionFeed(ExampleFeed):
    created = None

    def __init__(self, adapter):
        super().__init__(adapter)
        self.initialized = False
        self.closed = False
        self.close_count = 0
        if self.created is not None:
            self.created.append(self)

    async def initialize(self):
        assert self not in self.adapter.capabilities.values()
        self.initialized = True

    async def terminate(self):
        assert self not in self.adapter.capabilities.values()
        self.closed = True
        self.close_count += 1


@pytest_asyncio.fixture
async def manager(monkeypatch, tmp_path):
    for name in ("_registry", "_manifests", "_manifest_dirs", "_schemas"):
        monkeypatch.setattr(AdapterManager, name, {})
    monkeypatch.setattr(AdapterManager, "scan_adapters", lambda *args: None)
    manager = AdapterManager({}, asyncio.Queue())
    manager.register_adapter_type("qq", ExampleAdapter, {"name": "qq"}, tmp_path)
    yield manager
    await manager.stop_adapters()


async def account(manager, name="one", **config):
    info = AdapterInfo(True, name, name, "qq", config=config)
    await manager.register_adapter(info)
    return manager.get_adapter(name)


@pytest.mark.asyncio
async def test_existing_accounts_get_independent_ready_capabilities_without_restart(manager):
    first, second = await account(manager), await account(manager, "two")
    first_im, first_task = first.im, manager._adapter_tasks["one"]
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    a, b = first.get_capability(FeedCapability), second.get_capability(FeedCapability)
    assert a is not b and a.adapter is first and b.adapter is second
    assert a.initialized and b.initialized
    assert first.im is first_im and manager._adapter_tasks["one"] is first_task
    assert not a.is_allowed("123", permission="feed.post")
    await manager.capability_registry.unregister_owner("plugin")
    assert a.closed and b.closed
    assert first.im is first_im and not first_task.done()


@pytest.mark.asyncio
async def test_binding_can_precede_adapter_type_and_future_accounts(manager, tmp_path):
    await manager.capability_registry.register("plugin", "late", FeedCapability, ExtensionFeed)
    manager.register_adapter_type("late", ExampleAdapter, {"name": "late"}, tmp_path)
    info = AdapterInfo(True, "later", "later", "late")
    await manager.register_adapter(info)
    adapter = manager.get_adapter("later")
    assert adapter.get_capability(FeedCapability).initialized
    await manager.stop_adapter("later")
    await manager.register_adapter(info)
    replacement = manager.get_adapter("later")
    assert replacement is not adapter
    assert replacement.get_capability(FeedCapability).initialized


@pytest.mark.asyncio
async def test_stop_replacement_and_run_completion_close_extensions_once(manager):
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    first = await account(manager)
    old = first.get_capability(FeedCapability)
    await account(manager)
    assert old.closed and old.close_count == 1
    current = manager.get_adapter("one")
    feed = current.get_capability(FeedCapability)
    current._shutdown_event.set()
    await manager._adapter_tasks["one"]
    await asyncio.sleep(0)
    assert feed.closed and feed.close_count == 1
    assert manager.get_adapter("one") is None
    assert not manager.capability_registry._bindings[("qq", FeedCapability)].instances


@pytest.mark.asyncio
async def test_builtin_instance_uses_same_binding_lifecycle(manager):
    from core.adapter import AdapterContext
    adapter = ExampleAdapter(AdapterContext(
        AdapterInfo(True, "internal", "internal", "qq"), asyncio.Queue(),
    ))
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    await manager.register_builtin_adapter(adapter)
    feed = adapter.get_capability(FeedCapability)
    assert feed.initialized
    await manager.stop_adapter("internal")
    assert feed.close_count == 1


@pytest.mark.asyncio
async def test_native_conflict_does_not_replace_or_close_native_capability(manager):
    adapter = await account(manager, enable_qzone=True)
    native = adapter.get_capability(FeedCapability)
    native.terminate = AsyncMock()
    with pytest.raises(ValueError, match="already registered"):
        await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    assert adapter.get_capability(FeedCapability) is native
    assert not manager.capability_registry._bindings
    native.terminate.assert_not_awaited()
    await manager.stop_adapter("one")
    native.terminate.assert_awaited_once()


@pytest.mark.asyncio
async def test_future_native_conflict_does_not_publish_or_start_partial_adapter(manager):
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    with pytest.raises(ValueError, match="already registered"):
        await account(manager, enable_qzone=True)
    assert manager.get_adapter("one") is None
    assert "one" not in manager._adapter_tasks


@pytest.mark.asyncio
async def test_duplicate_kind_and_other_plugin_cannot_replace_or_unregister(manager):
    await manager.capability_registry.register("first", "qq", FeedCapability, ExtensionFeed)
    for owner, kind in (("first", FeedCapability), ("other", ExtensionFeed)):
        with pytest.raises(ValueError, match="already registered"):
            await manager.capability_registry.register(owner, "qq", kind, ExtensionFeed)
    adapter = await account(manager)
    feed = adapter.get_capability(FeedCapability)
    assert not await manager.capability_registry.unregister("other", "qq", FeedCapability)
    assert adapter.get_capability(FeedCapability) is feed and not feed.closed
    assert await manager.capability_registry.unregister("first", "qq", FeedCapability)
    assert feed.closed
    assert not await manager.capability_registry.unregister("first", "qq", FeedCapability)
    await manager.capability_registry.register("other", "qq", FeedCapability, ExtensionFeed)
    assert adapter.get_capability(FeedCapability) is not feed


@pytest.mark.asyncio
async def test_failed_initialization_rolls_back_all_accounts_and_owned_policies(manager):
    first, second = await account(manager), await account(manager, "two")
    original = ListAccessPolicy("allow_list", frozenset({"original"}))
    first.access.set_policy(capability_type=FeedCapability, permission="post", policy=original)
    created = []

    class FailingFeed(ExtensionFeed):
        async def initialize(self):
            await super().initialize()
            self.adapter.access.set_policy(
                capability_type=FeedCapability, permission="post",
                policy=ListAccessPolicy("allow_list", frozenset({"extension"})),
            )
            if self.adapter is second:
                raise RuntimeError("init failed")

    def factory(adapter):
        feed = FailingFeed(adapter)
        created.append(feed)
        return feed

    with pytest.raises(RuntimeError, match="init failed"):
        await manager.capability_registry.register("plugin", "qq", FeedCapability, factory)
    assert all(feed.closed and feed.close_count == 1 for feed in created)
    assert all(FeedCapability not in adapter.capabilities for adapter in (first, second))
    assert first.access.get_policies(FeedCapability) == {"post": original}
    assert second.access.get_policies(FeedCapability) == {}
    assert not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_policy_cleanup_keeps_later_changes_and_unrelated_im_permissions(manager):
    adapter = await account(manager)
    original = ListAccessPolicy("allow_list", frozenset({"old"}))
    installed = ListAccessPolicy("allow_list", frozenset({"plugin"}))
    later = ListAccessPolicy("allow_list", frozenset({"later"}))
    adapter.access.set_policy(capability_type=IMCapability, permission="receive", policy=original)
    adapter.access.set_policy(capability_type=FeedCapability, permission="post", policy=original)

    class PolicyFeed(ExtensionFeed):
        async def initialize(self):
            for permission in ("post", "comment"):
                self.adapter.access.set_policy(
                    capability_type=FeedCapability, permission=permission, policy=installed,
                )

    await manager.capability_registry.register("plugin", "qq", FeedCapability, PolicyFeed)
    adapter.access.set_policy(capability_type=FeedCapability, permission="comment", policy=later)
    await manager.capability_registry.unregister_owner("plugin")
    assert adapter.access.get_policies(FeedCapability) == {"post": original, "comment": later}
    assert adapter.im.is_allowed("old", permission="receive")


@pytest.mark.asyncio
async def test_cancelling_registration_cleans_partial_initialization(manager):
    adapter = await account(manager)
    entered = asyncio.Event()
    created = []

    class WaitingFeed(ExtensionFeed):
        async def initialize(self):
            created.append(self)
            entered.set()
            await asyncio.Event().wait()

    task = asyncio.create_task(manager.capability_registry.register(
        "plugin", "qq", FeedCapability, WaitingFeed,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created[0].closed and not manager.capability_registry._bindings
    assert FeedCapability not in adapter.capabilities


@pytest.mark.asyncio
async def test_unregistration_cleanup_survives_caller_cancellation(manager):
    adapter = await account(manager)
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingCloseFeed(ExtensionFeed):
        async def terminate(self):
            entered.set()
            await release.wait()
            await super().terminate()

    await manager.capability_registry.register("plugin", "qq", FeedCapability, WaitingCloseFeed)
    feed = adapter.get_capability(FeedCapability)
    task = asyncio.create_task(manager.capability_registry.unregister(
        "plugin", "qq", FeedCapability,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    assert FeedCapability not in adapter.capabilities
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert feed.closed and not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_cleanup_errors_do_not_skip_other_accounts_or_expose_exception_text(manager, monkeypatch):
    from core.adapter import capability_registry as module
    adapter, other = await account(manager), await account(manager, "two")
    errors = []
    monkeypatch.setattr(module.logger, "error", errors.append)

    class BadCloseFeed(ExtensionFeed):
        async def terminate(self):
            await super().terminate()
            if self.adapter is other:
                raise RuntimeError("private-token")

    await manager.capability_registry.register("plugin", "qq", FeedCapability, BadCloseFeed)
    feeds = [item.get_capability(FeedCapability) for item in (adapter, other)]
    await manager.capability_registry.unregister_owner("plugin")
    assert all(feed.closed for feed in feeds)
    assert errors and "private-token" not in str(errors)


@pytest.mark.asyncio
async def test_reentrant_lifecycle_mutation_fails_instead_of_deadlocking(manager):
    await account(manager)

    class ReentrantFeed(ExtensionFeed):
        async def initialize(self):
            await manager.capability_registry.unregister_owner("plugin")

    with pytest.raises(RuntimeError, match="lifecycle hooks cannot mutate"):
        await asyncio.wait_for(manager.capability_registry.register(
            "plugin", "qq", FeedCapability, ReentrantFeed,
        ), 1)
    assert not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_registration_serializes_with_new_account_creation(manager):
    adapter = await account(manager)
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingFeed(ExtensionFeed):
        async def initialize(self):
            if self.adapter is adapter:
                entered.set()
                await release.wait()
            await super().initialize()

    registering = asyncio.create_task(manager.capability_registry.register(
        "plugin", "qq", FeedCapability, WaitingFeed,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    creating = asyncio.create_task(account(manager, "two"))
    await asyncio.sleep(0)
    assert manager.get_adapter("two") is None
    release.set()
    await registering
    second = await creating
    assert adapter.get_capability(FeedCapability).initialized
    assert second.get_capability(FeedCapability).initialized


@pytest.mark.asyncio
async def test_unload_blocks_in_progress_and_late_registrations(manager):
    await account(manager)
    entered, release = asyncio.Event(), asyncio.Event()

    class WaitingFeed(ExtensionFeed):
        async def initialize(self):
            entered.set()
            await release.wait()

    task = asyncio.create_task(manager.capability_registry.register(
        "plugin", "qq", FeedCapability, WaitingFeed,
    ))
    await asyncio.wait_for(entered.wait(), 1)
    manager.capability_registry.block_owner("plugin")
    cleanup = asyncio.create_task(manager.capability_registry.unregister_owner("plugin"))
    release.set()
    with pytest.raises(RuntimeError, match="shutting down"):
        await task
    await cleanup
    with pytest.raises(RuntimeError, match="shutting down"):
        await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    manager.capability_registry.allow_owner("plugin")
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)


@pytest.mark.asyncio
@pytest.mark.parametrize("platform,kind,factory,error", [
    ("", FeedCapability, ExtensionFeed, ValueError),
    ("qq", str, ExtensionFeed, TypeError),
    ("qq", FeedCapability, None, TypeError),
])
async def test_invalid_bindings_fail_before_mutation(manager, platform, kind, factory, error):
    with pytest.raises(error):
        await manager.capability_registry.register("plugin", platform, kind, factory)
    assert not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_factory_cannot_reuse_another_accounts_capability(manager):
    first, second = await account(manager), await account(manager, "two")
    feed = ExtensionFeed(first)
    with pytest.raises(ValueError, match="another adapter"):
        await manager.capability_registry.register("plugin", "qq", FeedCapability, lambda adapter: feed)
    assert feed.closed and not manager.capability_registry._bindings
    assert FeedCapability not in second.capabilities


def test_identity_checked_unregistration_does_not_remove_replacement():
    from tests.test_adapter_base import make_adapter
    adapter = make_adapter(enable_qzone=True)
    old = adapter.get_capability(FeedCapability)
    assert not adapter.unregister_capability(FeedCapability, ExampleFeed(adapter))
    assert adapter.unregister_capability(FeedCapability, old)
    replacement = adapter.register_capability(FeedCapability, ExampleFeed(adapter))
    assert not adapter.unregister_capability(FeedCapability, old)
    assert adapter.get_capability(FeedCapability) is replacement
    with pytest.raises(RuntimeError, match="not been registered"):
        _ = old.capability_type


@pytest.fixture
def plugin_context(manager, monkeypatch, tmp_path):
    for name in (
        "_plugin_classes", "_plugin_components", "_plugin_load_errors", "_plugin_manifests",
        "_plugin_module_dirs", "_plugin_module_paths", "_plugin_schemas",
        "_plugin_infos", "_module_to_plugin",
    ):
        monkeypatch.setattr(registry, name, {})
    monkeypatch.setattr(plugin_manager_module, "PLUGIN_CONFIG_DIR", tmp_path / "config")
    monkeypatch.setattr(plugin_manager_module, "PLUGIN_STATE_FILE", tmp_path / "state.json")
    context = object.__new__(PluginContext)
    context.adapter_mgr = manager
    context.config = {}
    context.tool_mgr = None
    context.plugin_mgr = PluginManager(context)
    return context


PLUGIN_SOURCE = '''
from core.plugin import BasePlugin
from core.adapter import FeedCapability
from tests.test_adapter_capability_extensions import ExtensionFeed

class CapabilityPlugin(BasePlugin):
    async def initialize(self):
        await self.ctx.register_adapter_capability(
            platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
        )
        if self.plugin_cfg.get("fail"):
            raise RuntimeError("failed after registration")

    async def terminate(self):
        if self.plugin_cfg.get("terminate_fail"):
            raise RuntimeError("termination failed")
'''


@pytest.mark.asyncio
async def test_real_plugin_load_reload_disable_and_uninstall_clean_capabilities(
    plugin_context, manager, tmp_path,
):
    adapter = await account(manager)
    plugins = plugin_context.plugin_mgr
    plugin_root = tmp_path / "plugins" / "capability-plugin"
    plugin_root.mkdir(parents=True)
    (plugin_root / "manifest.json").write_text(
        json.dumps({"plugin_id": "capability-plugin"}), encoding="utf-8",
    )
    (plugin_root / "main.py").write_text(PLUGIN_SOURCE, encoding="utf-8")
    plugins.plugin_dir = plugin_root.parent
    try:
        assert await plugins.load_plugin_from_dir(plugin_root, auto_install=False) == "capability-plugin"
        first = adapter.get_capability(FeedCapability)
        assert registry._plugin_components["capability-plugin"].adapter_capabilities == {
            ("qq", FeedCapability),
        }
        await plugins.prepare_plugin_reload("capability-plugin")
        assert first.closed and FeedCapability not in adapter.capabilities
        await plugins.load_plugin_from_dir(plugin_root, auto_install=False)
        second = adapter.get_capability(FeedCapability)
        assert second is not first
        await plugins.set_plugin_enabled("capability-plugin", False)
        assert second.closed and FeedCapability not in adapter.capabilities
        await plugins.set_plugin_enabled("capability-plugin", True)
        third = adapter.get_capability(FeedCapability)
        await plugins.uninstall_plugin("capability-plugin")
        assert third.closed and not manager.capability_registry._bindings
        future = await account(manager, "future")
        assert FeedCapability not in future.capabilities
    finally:
        await plugins.terminate("capability-plugin")
        plugins._cleanup_plugin_modules("capability-plugin")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_plugin_initialization_failure_or_cancellation_cleans_binding(
    plugin_context, manager, monkeypatch, cancel,
):
    from core.plugin import BasePlugin
    adapter = await account(manager)
    plugins = plugin_context.plugin_mgr

    class FailingPlugin(BasePlugin):
        async def initialize(self):
            await self.ctx.register_adapter_capability(
                platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
            )
            if cancel:
                raise asyncio.CancelledError
            raise RuntimeError("failed after registration")

        async def terminate(self):
            pass

    monkeypatch.setitem(registry._module_to_plugin, __name__, "failing")
    monkeypatch.setitem(registry._plugin_classes, "failing", FailingPlugin)
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            await plugins.init_plugin("failing")
    else:
        await plugins.init_plugin("failing")
    assert "failing" not in plugins.plugin_instances
    assert FeedCapability not in adapter.capabilities
    assert not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_context_ownership_and_unload_despite_plugin_termination_error(
    plugin_context, manager, monkeypatch,
):
    adapter = await account(manager)
    ctx, plugins = plugin_context, plugin_context.plugin_mgr
    with pytest.raises(RuntimeError, match="not associated"):
        await ctx.register_adapter_capability(
            platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
        )
    monkeypatch.setitem(registry._module_to_plugin, __name__, "owner")
    await ctx.register_adapter_capability(
        platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
    )
    feed = adapter.get_capability(FeedCapability)
    monkeypatch.setitem(registry._module_to_plugin, __name__, "other")
    assert not await ctx.unregister_adapter_capability(platform="qq", capability_type=FeedCapability)
    monkeypatch.setitem(registry._module_to_plugin, __name__, "owner")
    assert await ctx.unregister_adapter_capability(platform="qq", capability_type=FeedCapability)
    assert feed.closed
    await ctx.register_adapter_capability(
        platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
    )
    feed = adapter.get_capability(FeedCapability)
    plugins.plugin_instances["owner"] = SimpleNamespace(
        terminate=AsyncMock(side_effect=RuntimeError("termination failed")),
    )
    await plugins.terminate("owner")
    assert feed.closed and not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_initialization_timeout_rolls_back_and_terminates_partial_instance(manager, monkeypatch):
    from core.adapter import capability_registry as module
    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    adapter = await account(manager)
    created = []

    class HungFeed(ExtensionFeed):
        async def initialize(self):
            created.append(self)
            await asyncio.Event().wait()

    with pytest.raises(asyncio.TimeoutError):
        await manager.capability_registry.register("plugin", "qq", FeedCapability, HungFeed)
    assert created[0].closed
    assert FeedCapability not in adapter.capabilities


@pytest.mark.asyncio
async def test_cleanup_timeout_withdraws_all_capabilities_and_restores_policies(manager, monkeypatch):
    from core.adapter import capability_registry as module
    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    adapter = await account(manager)
    cancelled = asyncio.Event()

    class HungCloseFeed(ExtensionFeed):
        async def initialize(self):
            self.adapter.access.set_policy(
                capability_type=FeedCapability, permission="post",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )

        async def terminate(self):
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    await manager.capability_registry.register("plugin", "qq", FeedCapability, HungCloseFeed)
    await manager.capability_registry.unregister_owner("plugin")
    assert cancelled.is_set()
    assert not adapter.access.get_policies(FeedCapability)
    assert FeedCapability not in adapter.capabilities


@pytest.mark.asyncio
async def test_async_factories_are_rejected_without_leaking_coroutines(manager):
    await account(manager)

    async def factory(adapter):
        return ExtensionFeed(adapter)

    class AsyncFactory:
        async def __call__(self, adapter):
            return ExtensionFeed(adapter)

    for invalid in (factory, AsyncFactory(), lambda adapter: factory(adapter)):
        with pytest.raises(TypeError, match="synchronous"):
            await manager.capability_registry.register("plugin", "qq", FeedCapability, invalid)
    assert not manager.capability_registry._bindings


@pytest.mark.asyncio
async def test_registration_and_unregistration_normalize_platform(plugin_context, manager, monkeypatch):
    monkeypatch.setitem(registry._module_to_plugin, __name__, "owner")
    adapter = await account(manager)
    await plugin_context.register_adapter_capability(
        platform=" qq ", capability_type=FeedCapability, factory=ExtensionFeed,
    )
    feed = adapter.get_capability(FeedCapability)
    assert await plugin_context.unregister_adapter_capability(
        platform=" qq ", capability_type=FeedCapability,
    )
    assert feed.closed and not registry._plugin_components["owner"].adapter_capabilities


@pytest.mark.asyncio
@pytest.mark.parametrize("all_plugins", [False, True])
async def test_cancellation_during_plugin_termination_still_removes_owned_bindings(
    plugin_context, manager, monkeypatch, all_plugins,
):
    monkeypatch.setitem(registry._module_to_plugin, __name__, "owner")
    adapter = await account(manager)
    await plugin_context.register_adapter_capability(
        platform="qq", capability_type=FeedCapability, factory=ExtensionFeed,
    )
    feed = adapter.get_capability(FeedCapability)
    entered = asyncio.Event()

    async def terminate():
        entered.set()
        await asyncio.Event().wait()

    plugins = plugin_context.plugin_mgr
    plugins.plugin_instances["owner"] = SimpleNamespace(terminate=terminate)
    task = asyncio.create_task(plugins.terminate(None if all_plugins else "owner"))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert feed.closed and not manager.capability_registry._bindings
    assert "owner" not in plugins.plugin_instances


@pytest.mark.asyncio
async def test_cancellation_during_future_attachment_closes_instance_and_leaves_binding(manager):
    entered = asyncio.Event()
    created = []

    class SlowFeed(ExtensionFeed):
        async def initialize(self):
            created.append(self)
            entered.set()
            await asyncio.Event().wait()

    await manager.capability_registry.register("plugin", "qq", FeedCapability, SlowFeed)
    task = asyncio.create_task(account(manager))
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert created[0].closed and manager.get_adapter("one") is None
    assert not manager._adapter_tasks
    assert not manager.capability_registry._bindings[("qq", FeedCapability)].instances


@pytest.mark.asyncio
async def test_cancellation_before_adapter_runner_executes_closes_extension(manager):
    from core.adapter import AdapterContext
    adapter = ExampleAdapter(AdapterContext(
        AdapterInfo(True, "early", "early", "qq"), asyncio.Queue(),
    ))
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    await manager.capability_registry.attach(adapter)
    manager._adapters["early"] = adapter
    feed = adapter.get_capability(FeedCapability)
    starting = asyncio.create_task(manager.start_adapter("early"))
    await asyncio.sleep(0)
    manager._adapter_tasks["early"].cancel()
    with pytest.raises(asyncio.CancelledError):
        await starting
    assert feed.closed and feed.close_count == 1


@pytest.mark.asyncio
async def test_future_attachment_failure_rolls_back_other_extension_kinds(manager):
    class CustomCapability(BaseCapability):
        async def initialize(self):
            raise RuntimeError("custom init failed")

    await manager.capability_registry.register("feed-plugin", "qq", FeedCapability, ExtensionFeed)
    await manager.capability_registry.register("custom-plugin", "qq", CustomCapability, CustomCapability)
    created = []
    ExtensionFeed.created = created
    try:
        with pytest.raises(RuntimeError, match="custom init failed"):
            await account(manager)
    finally:
        ExtensionFeed.created = None
    assert created[0].closed and manager.get_adapter("one") is None
    assert all(not binding.instances for binding in manager.capability_registry._bindings.values())


@pytest.mark.asyncio
async def test_external_replacement_is_not_removed_or_its_policies_reverted(manager):
    adapter = await account(manager)
    policy = ListAccessPolicy("allow_list", frozenset({"plugin"}))

    class PolicyFeed(ExtensionFeed):
        async def initialize(self):
            self.adapter.access.set_policy(
                capability_type=FeedCapability, permission="post", policy=policy,
            )

    await manager.capability_registry.register("plugin", "qq", FeedCapability, PolicyFeed)
    old = adapter.get_capability(FeedCapability)
    adapter.unregister_capability(FeedCapability, old)
    new = adapter.register_capability(FeedCapability, ExtensionFeed(adapter))
    await manager.capability_registry.unregister_owner("plugin")
    assert old.closed and not new.closed
    assert adapter.get_capability(FeedCapability) is new
    assert adapter.access.get_policies(FeedCapability) == {"post": policy}


@pytest.mark.asyncio
@pytest.mark.parametrize("builtin", [False, True])
async def test_failed_attachment_bounds_native_cleanup_without_masking_registration_error(
    manager, monkeypatch, builtin,
):
    from core.adapter import AdapterContext
    from core.adapter import adapter_registry as module
    monkeypatch.setattr(module, "ADAPTER_STOP_TIMEOUT", 0.01)
    stopped = asyncio.Event()

    class BlockingStopAdapter(ExampleAdapter):
        async def stop(self):
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

    class FailingFeed(ExtensionFeed):
        async def initialize(self):
            raise RuntimeError("original registration error")

    await manager.capability_registry.register("plugin", "qq", FeedCapability, FailingFeed)
    info = AdapterInfo(True, "failure", "failure", "qq")
    with pytest.raises(RuntimeError, match="original registration error"):
        if builtin:
            adapter = BlockingStopAdapter(AdapterContext(info, asyncio.Queue()))
            await asyncio.wait_for(manager.register_builtin_adapter(adapter), 1)
        else:
            manager._registry["qq"] = BlockingStopAdapter
            await asyncio.wait_for(manager.register_adapter(info), 1)
    assert stopped.is_set()
    assert manager.get_adapter("failure") is None
    assert "failure" not in manager._builtin_names
    assert not manager._adapter_tasks


@pytest.mark.asyncio
async def test_cancelling_start_caller_keeps_capabilities_on_live_runner(manager):
    """Cancelling a scheduling caller must not withdraw a live runner's features."""
    from core.adapter import AdapterContext
    adapter = ExampleAdapter(AdapterContext(
        AdapterInfo(True, "caller-cancel", "caller-cancel", "qq"), asyncio.Queue(),
    ))
    await manager.capability_registry.register("plugin", "qq", FeedCapability, ExtensionFeed)
    await manager.capability_registry.attach(adapter)
    manager._adapters[adapter.info.name] = adapter
    feed = adapter.get_capability(FeedCapability)
    starting = asyncio.create_task(manager.start_adapter(adapter.info.name))
    await asyncio.sleep(0)
    starting.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await starting
        assert not manager._adapter_tasks[adapter.info.name].done()
        assert adapter.get_capability(FeedCapability) is feed
        assert not feed.closed
    finally:
        await manager.stop_adapter(adapter.info.name)
    assert feed.closed and feed.close_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("all_plugins", [False, True])
@pytest.mark.parametrize("failure_phase", ["block", "unregister"])
async def test_capability_cleanup_failure_preserves_retry_and_other_plugin_cleanup(
    plugin_context, manager, monkeypatch, all_plugins, failure_phase,
):
    """Registry failures leave retry metadata without stranding other components."""
    from unittest.mock import Mock
    plugins = plugin_context.plugin_mgr
    adapter = await account(manager)
    await plugins.register_plugin_adapter_capability(
        "first", "qq", FeedCapability, ExtensionFeed,
    )
    feed = adapter.get_capability(FeedCapability)
    for owner in ("first", "second"):
        comp = registry._ensure_components(owner)
        comp.register_tool(owner + "_tool", "cleanup test", {}, lambda: None)
        plugins.plugin_instances[owner] = SimpleNamespace(terminate=AsyncMock())
    first = registry._plugin_components["first"]
    first.adapters["test-platform"] = {}
    first.providers["test-format"] = {}
    plugin_context.tool_mgr = Mock()
    errors = []
    extensions = manager.capability_registry
    original_block = extensions.block_owner
    original_unregister = extensions.unregister_owner

    def block(owner):
        if owner == "first" and failure_phase == "block":
            raise RuntimeError("private-token")
        original_block(owner)

    async def unregister(owner):
        if owner == "first" and failure_phase == "unregister":
            raise RuntimeError("private-token")
        await original_unregister(owner)

    try:
        with monkeypatch.context() as patch:
            patch.setattr(extensions, "block_owner", block)
            patch.setattr(extensions, "unregister_owner", unregister)
            patch.setattr(plugin_manager_module.logger, "error", errors.append)
            unregister_adapter = AsyncMock(return_value=True)
            unregister_provider = AsyncMock(return_value=True)
            patch.setattr(plugins, "unregister_plugin_adapter", unregister_adapter)
            patch.setattr(plugins, "unregister_plugin_provider", unregister_provider)
            await plugins.terminate(None if all_plugins else "first")
            unregister_adapter.assert_awaited_once_with("first", "test-platform")
            unregister_provider.assert_awaited_once_with("first", "test-format")

        plugin_context.tool_mgr.unregister_tool.assert_any_call("first_tool")
        if all_plugins:
            plugin_context.tool_mgr.unregister_tool.assert_any_call("second_tool")
            assert not plugins.plugin_instances
        assert errors and "private-token" not in str(errors)
        assert first.adapter_capabilities == {("qq", FeedCapability)}
        assert adapter.get_capability(FeedCapability) is feed and not feed.closed

        # A later cleanup can retry after the registry error has cleared.
        first.adapters.clear()
        first.providers.clear()
        await plugins._cleanup_plugin_runtime_components("first")
        assert feed.closed and not first.adapter_capabilities
    finally:
        first.adapters.clear()
        first.providers.clear()
        await plugins.terminate()


@pytest.mark.asyncio
@pytest.mark.parametrize("all_plugins", [False, True])
async def test_registration_cleanup_survives_unexpected_runtime_cleanup_failure(
    plugin_context, monkeypatch, all_plugins,
):
    """Registration cleanup and later plugins survive unexpected cleanup errors."""
    from unittest.mock import Mock
    plugins = plugin_context.plugin_mgr
    plugin_context.tool_mgr = Mock()
    for owner in ("first", "second"):
        registry._ensure_components(owner).register_tool(owner, "test", {}, lambda: None)
        plugins.plugin_instances[owner] = SimpleNamespace(terminate=AsyncMock())

    original = plugins._cleanup_plugin_runtime_components

    async def cleanup(owner):
        if owner == "first":
            raise RuntimeError("private-token")
        await original(owner)

    errors = []
    with monkeypatch.context() as patch:
        patch.setattr(plugins, "_cleanup_plugin_runtime_components", cleanup)
        patch.setattr(plugin_manager_module.logger, "error", errors.append)
        await plugins.terminate(None if all_plugins else "first")
    plugin_context.tool_mgr.unregister_tool.assert_any_call("first")
    if all_plugins:
        plugin_context.tool_mgr.unregister_tool.assert_any_call("second")
    assert errors and "private-token" not in str(errors)
    await plugins.terminate()


@pytest.mark.asyncio
async def test_capability_cleanup_cancellation_propagates_after_registration_cleanup(
    plugin_context, manager, monkeypatch,
):
    """Cancellation remains observable while non-runtime registrations are removed."""
    from unittest.mock import Mock
    plugins = plugin_context.plugin_mgr
    plugin_context.tool_mgr = Mock()
    await account(manager)
    await plugins.register_plugin_adapter_capability(
        "owner", "qq", FeedCapability, ExtensionFeed,
    )
    comp = registry._plugin_components["owner"]
    comp.register_tool("owner_tool", "test", {}, lambda: None)
    plugins.plugin_instances["owner"] = SimpleNamespace(terminate=AsyncMock())
    with monkeypatch.context() as patch:
        patch.setattr(
            manager.capability_registry, "unregister_owner",
            AsyncMock(side_effect=asyncio.CancelledError),
        )
        with pytest.raises(asyncio.CancelledError):
            await plugins.terminate("owner")
    plugin_context.tool_mgr.unregister_tool.assert_called_once_with("owner_tool")
    assert comp.adapter_capabilities == {("qq", FeedCapability)}
    await plugins.terminate("owner")
    assert not comp.adapter_capabilities


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", [
    "unload", "initialize_error", "factory_error", "invalid_result",
    "foreign_instance", "duplicate", "awaitable",
])
async def test_constructor_policy_changes_are_rolled_back(manager, outcome):
    adapter = await account(manager, enable_qzone=outcome == "duplicate")
    other = await account(manager, "other") if outcome == "foreign_instance" else None
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    permissive = ListAccessPolicy("deny_list", frozenset())
    adapter.access.set_policy(capability_type=FeedCapability, permission="post", policy=original)
    adapter.access.set_policy(capability_type=IMCapability, permission="receive", policy=original)
    native = adapter.capabilities.get(FeedCapability)
    created = []

    class PolicyFeed(ExtensionFeed):
        async def initialize(self):
            if outcome == "initialize_error":
                raise RuntimeError("initialization failed")
            await super().initialize()

    async def asynchronous_result():
        return None

    def factory(target):
        target.access.set_policy(
            capability_type=FeedCapability, permission="post", policy=permissive,
        )
        target.access.set_policy(
            capability_type=FeedCapability, permission="comment", policy=permissive,
        )
        if outcome == "factory_error":
            raise RuntimeError("factory failed")
        if outcome == "invalid_result":
            return object()
        if outcome == "awaitable":
            return asynchronous_result()
        feed = PolicyFeed(other if outcome == "foreign_instance" else target)
        created.append(feed)
        return feed

    capabilities = manager.capability_registry
    if outcome == "unload":
        await capabilities.register("plugin", "qq", FeedCapability, factory)
        assert adapter.access.is_allowed(
            "stranger", capability_type=FeedCapability, permission="post",
        )
        await capabilities.unregister_owner("plugin")
    else:
        error = {
            "initialize_error": RuntimeError, "factory_error": RuntimeError,
            "invalid_result": TypeError, "foreign_instance": ValueError,
            "duplicate": ValueError, "awaitable": TypeError,
        }[outcome]
        with pytest.raises(error):
            await capabilities.register("plugin", "qq", FeedCapability, factory)

    assert adapter.access.get_policies(FeedCapability) == {"post": original}
    assert adapter.access.get_policies(IMCapability) == {"receive": original}
    assert adapter.capabilities.get(FeedCapability) is native
    assert not capabilities._bindings
    if outcome in {"unload", "initialize_error"}:
        assert created[0].close_count == 1
    elif created:
        assert created[0].close_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("future_account", [False, True])
async def test_constructor_policy_rollback_preserves_later_replacements(manager, future_account):
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    later = ListAccessPolicy("allow_list", frozenset({"replacement"}))

    class PolicyFeed(ExtensionFeed):
        def __init__(self, adapter):
            super().__init__(adapter)
            adapter.access.set_policy(
                capability_type=FeedCapability, permission="post",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )
            adapter.access.set_policy(
                capability_type=FeedCapability, permission="comment",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )

    adapter = None if future_account else await account(manager)
    if adapter is not None:
        adapter.access.set_policy(
            capability_type=FeedCapability, permission="post", policy=original,
        )
    await manager.capability_registry.register("plugin", "qq", FeedCapability, PolicyFeed)
    if future_account:
        adapter = await account(manager)
    adapter.access.set_policy(
        capability_type=FeedCapability, permission="comment", policy=later,
    )
    await manager.capability_registry.unregister_owner("plugin")
    expected = {"comment": later}
    if not future_account:
        expected["post"] = original
    assert adapter.access.get_policies(FeedCapability) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("hook_name", ["initialize", "terminate"])
@pytest.mark.parametrize("cancel_caller", [False, True])
async def test_cancellation_resistant_hook_does_not_block_registry(
    manager, monkeypatch, hook_name, cancel_caller,
):
    from core.adapter import capability_registry as module

    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.02)
    monkeypatch.setattr(module, "CAPABILITY_CANCELLATION_GRACE", 0.02)
    adapter = await account(manager)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []
    capabilities = manager.capability_registry

    class StubbornFeed(ExtensionFeed):
        async def stubborn_hook(self):
            tasks.append(asyncio.current_task())
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            raise RuntimeError("late hook failure")

    setattr(StubbornFeed, hook_name, StubbornFeed.stubborn_hook)
    if hook_name == "terminate":
        await capabilities.register("plugin", "qq", FeedCapability, StubbornFeed)
        operation = asyncio.create_task(capabilities.unregister_owner("plugin"))
    else:
        operation = asyncio.create_task(capabilities.register(
            "plugin", "qq", FeedCapability, StubbornFeed,
        ))
    contender = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if cancel_caller:
            operation.cancel()
        await asyncio.wait_for(cancelled.wait(), 1)
        contender = asyncio.create_task(capabilities.register(
            "other-plugin", "other-platform", FeedCapability, ExtensionFeed,
        ))
        done, _ = await asyncio.wait({operation, contender}, timeout=0.5)
        assert operation in done and contender in done
        if cancel_caller:
            with pytest.raises(asyncio.CancelledError):
                await operation
        elif hook_name == "initialize":
            with pytest.raises(asyncio.TimeoutError):
                await operation
        else:
            await operation
        await contender
        assert FeedCapability not in adapter.capabilities
        assert ("qq", FeedCapability) not in capabilities._bindings
        assert tasks[0] in capabilities._hook_tasks and not tasks[0].done()
    finally:
        release.set()
        await asyncio.gather(operation, *tasks, return_exceptions=True)
        if contender is not None:
            await asyncio.gather(contender, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.gather(*capabilities._cleanup_tasks, return_exceptions=True)
    await asyncio.sleep(0)
    assert not capabilities._hook_tasks
    assert not capabilities._pending_cleanup
