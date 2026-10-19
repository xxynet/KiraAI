"""Optional lifecycle hooks shared by native and plugin-provided capabilities."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from core.adapter import AdapterContext, BaseCapability, IMCapability
from core.adapter.access import ListAccessPolicy
from core.adapter.adapter_info import AdapterInfo
from tests.test_adapter_base import ExampleAdapter
from tests.test_adapter_capability_extensions import manager


@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["native", "plugin"])
@pytest.mark.parametrize("hooks", [(), ("initialize",), ("terminate",), ("initialize", "terminate")])
async def test_both_origins_allow_zero_one_or_both_lifecycle_hooks(manager, tmp_path, origin, hooks):
    events = []

    async def initialize(self):
        events.append(("initialize", self))

    async def terminate(self):
        events.append(("terminate", self))

    methods = {"initialize": initialize, "terminate": terminate}
    capability_type = type("OptionalCapability", (BaseCapability,), {
        name: methods[name] for name in hooks
    })

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            if origin == "native":
                self.register_capability(capability_type, capability_type(self))

    manager.register_adapter_type("optional", NativeAdapter, {"name": "optional"}, tmp_path)
    if origin == "plugin":
        await manager.capability_registry.register("plugin", "optional", capability_type, capability_type)
    info = AdapterInfo(True, "optional", "optional", "optional")
    await manager.register_adapter(info)
    adapter = manager.get_adapter("optional")
    capability = adapter.get_capability(capability_type)
    assert [name for name, _ in events] == (["initialize"] if "initialize" in hooks else [])
    await manager.start_adapter("optional")
    await manager.capability_registry.attach(adapter)
    assert [name for name, _ in events] == (["initialize"] if "initialize" in hooks else [])
    await manager.stop_adapter("optional")
    await manager.capability_registry.detach(adapter)
    assert events == [(name, capability) for name in ("initialize", "terminate") if name in hooks]
    assert (capability_type in adapter.capabilities) is (origin == "native")
    assert not manager.capability_registry._native_instances


@pytest.mark.asyncio
async def test_native_hooks_bracket_adapter_runner_and_reinitialize_on_restart(manager, tmp_path):
    events = []
    started = asyncio.Event()

    class NativeCapability(BaseCapability):
        async def initialize(self):
            assert self.adapter.get_capability(NativeCapability) is self
            events.append("initialize")

        async def terminate(self):
            assert self.adapter.get_capability(NativeCapability) is self
            events.append("terminate")

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(NativeCapability, NativeCapability(self))

        async def start(self):
            events.append("start")
            started.set()
            try:
                await super().start()
            finally:
                events.append("runner-finished")

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    info = AdapterInfo(True, "native", "native", "native")
    await manager.register_adapter(info)
    adapter = manager.get_adapter("native")
    capability = adapter.get_capability(NativeCapability)
    assert events == ["initialize", "start"]
    await manager.stop_adapter("native")
    assert events == ["initialize", "start", "runner-finished", "terminate"]
    # Existing-instance startup goes through the same lifecycle as registration.
    manager._adapters["native"] = adapter
    started.clear()
    await manager.start_adapter("native")
    await asyncio.wait_for(started.wait(), 1)
    assert adapter.get_capability(NativeCapability) is capability
    await manager.stop_adapter("native")
    assert events == ["initialize", "start", "runner-finished", "terminate"] * 2


@pytest.mark.asyncio
async def test_application_owned_webchat_can_use_optional_native_hooks(manager, monkeypatch):
    from core.adapter.builtin.webchat.im import WebChatIMCapability
    from core.adapter.builtin.webchat.webchat import WebChatAdapter

    initialize, terminate = AsyncMock(), AsyncMock()
    monkeypatch.setattr(WebChatIMCapability, "initialize", initialize)
    monkeypatch.setattr(WebChatIMCapability, "terminate", terminate)
    adapter = WebChatAdapter(
        AdapterContext(AdapterInfo(True, "webchat", "webchat", "WebChat"), asyncio.Queue()),
        object(),
    )
    await manager.register_builtin_adapter(adapter)
    capability = adapter.get_capability(IMCapability)
    initialize.assert_awaited_once()
    terminate.assert_not_awaited()
    await manager.stop_adapter("webchat")
    terminate.assert_awaited_once()
    assert adapter.get_capability(IMCapability) is capability


@pytest.mark.asyncio
async def test_plugin_unload_does_not_terminate_native_capabilities(manager, tmp_path):
    class NativeCapability(BaseCapability):
        initialize = AsyncMock()
        terminate = AsyncMock()

    class PluginCapability(BaseCapability):
        initialize = AsyncMock()
        terminate = AsyncMock()

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(NativeCapability, NativeCapability(self))

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    adapter = manager.get_adapter("native")
    await manager.capability_registry.register("plugin", "native", PluginCapability, PluginCapability)
    await manager.capability_registry.unregister_owner("plugin")
    PluginCapability.terminate.assert_awaited_once()
    NativeCapability.initialize.assert_awaited_once()
    NativeCapability.terminate.assert_not_awaited()
    await manager.stop_adapter("native")
    NativeCapability.terminate.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["error", "cancel", "timeout"])
async def test_native_initialization_failure_rolls_back_only_attempted_capabilities(
    manager, tmp_path, monkeypatch, failure,
):
    from core.adapter import capability_registry as module
    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    events, created = [], []

    class FirstCapability(BaseCapability):
        async def initialize(self):
            events.append("first-init")

        async def terminate(self):
            events.append("first-close")

    class FailingCapability(BaseCapability):
        async def initialize(self):
            events.append("failing-init")
            self.adapter.access.set_policy(
                capability_type=FailingCapability, permission="post",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "timeout":
                await asyncio.Event().wait()
            raise RuntimeError("native init failed")

        async def terminate(self):
            events.append("failing-close")

    class LaterCapability(BaseCapability):
        async def initialize(self):
            events.append("later-init")

        async def terminate(self):
            events.append("later-close")

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            created.append(self)
            for kind in (FirstCapability, FailingCapability, LaterCapability):
                self.register_capability(kind, kind(self))

        async def start(self):
            events.append("start")
            await super().start()

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    expected = {
        "error": RuntimeError, "cancel": asyncio.CancelledError, "timeout": asyncio.TimeoutError,
    }[failure]
    with pytest.raises(expected):
        await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    assert events == ["first-init", "failing-init", "failing-close", "first-close"]
    adapter = created[0]
    assert adapter.get_capability(FirstCapability).adapter is adapter
    assert not adapter.access.get_policies(FailingCapability)
    assert manager.get_adapter("native") is None
    assert not manager.capability_registry._native_instances


@pytest.mark.asyncio
async def test_extension_failure_rolls_back_native_hooks_without_removing_native_registration(
    manager, tmp_path,
):
    created = []

    class NativeCapability(BaseCapability):
        initialize = AsyncMock()
        terminate = AsyncMock()

    class FailingExtension(BaseCapability):
        async def initialize(self):
            raise RuntimeError("extension init failed")

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            created.append(self)
            self.register_capability(NativeCapability, NativeCapability(self))

    await manager.capability_registry.register(
        "plugin", "native", FailingExtension, FailingExtension,
    )
    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    with pytest.raises(RuntimeError, match="extension init failed"):
        await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    NativeCapability.initialize.assert_awaited_once()
    NativeCapability.terminate.assert_awaited_once()
    assert NativeCapability in created[0].capabilities
    assert not manager.capability_registry._native_instances


@pytest.mark.asyncio
async def test_native_cleanup_failure_does_not_skip_other_hooks_or_leak_error_text(
    manager, tmp_path, monkeypatch,
):
    from core.adapter import capability_registry as module
    errors = []
    monkeypatch.setattr(module.logger, "error", errors.append)

    class FirstCapability(BaseCapability):
        terminate = AsyncMock()

    class FailingCapability(BaseCapability):
        async def terminate(self):
            raise RuntimeError("private-token")

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(FirstCapability, FirstCapability(self))
            self.register_capability(FailingCapability, FailingCapability(self))

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    await manager.stop_adapter("native")
    FirstCapability.terminate.assert_awaited_once()
    assert errors and "private-token" not in str(errors)
    assert not manager.capability_registry._native_instances


@pytest.mark.asyncio
async def test_native_permission_changes_restore_on_stop(manager, tmp_path):
    original = ListAccessPolicy("allow_list", frozenset({"old"}))

    class NativeCapability(BaseCapability):
        async def initialize(self):
            self.adapter.access.set_policy(
                capability_type=NativeCapability, permission="post",
                policy=ListAccessPolicy("allow_list", frozenset({"new"})),
            )

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(NativeCapability, NativeCapability(self))
            self.access.set_policy(
                capability_type=NativeCapability, permission="post", policy=original,
            )

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    adapter = manager.get_adapter("native")
    capability = adapter.get_capability(NativeCapability)
    assert capability.is_allowed("new", permission="post")
    await manager.stop_adapter("native")
    assert adapter.access.get_policies(NativeCapability) == {"post": original}


@pytest.mark.asyncio
async def test_cancelled_native_cleanup_waits_for_owned_cleanup_to_finish(manager, tmp_path):
    entered, release = asyncio.Event(), asyncio.Event()

    class NativeCapability(BaseCapability):
        async def terminate(self):
            entered.set()
            await release.wait()

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(NativeCapability, NativeCapability(self))

    manager.register_adapter_type("native", NativeAdapter, {"name": "native"}, tmp_path)
    await manager.register_adapter(AdapterInfo(True, "native", "native", "native"))
    adapter = manager.get_adapter("native")
    stopping = asyncio.create_task(manager.capability_registry.detach(adapter))
    await asyncio.wait_for(entered.wait(), 1)
    stopping.cancel()
    await asyncio.sleep(0)
    assert not stopping.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    assert NativeCapability in adapter.capabilities
    assert not manager.capability_registry._native_instances


@pytest.mark.asyncio
async def test_stop_during_native_initialization_completion_does_not_start_runner(manager, monkeypatch):
    from core.adapter import adapter_registry as module
    monkeypatch.setattr(module, "ADAPTER_STOP_TIMEOUT", 0.1)
    entered, release = asyncio.Event(), asyncio.Event()
    events = []

    class NativeCapability(BaseCapability):
        async def initialize(self):
            entered.set()
            await release.wait()

        async def terminate(self):
            events.append("terminate")

    class NativeAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(NativeCapability, NativeCapability(self))

        async def start(self):
            events.append("start")
            await super().start()

    adapter = NativeAdapter(AdapterContext(
        AdapterInfo(True, "native", "native", "native"), asyncio.Queue(),
    ))
    manager._adapters["native"] = adapter
    await manager.start_adapter("native")
    await asyncio.wait_for(entered.wait(), 1)
    release.set()
    await asyncio.sleep(0)
    await manager.stop_adapter("native")
    assert events == ["terminate"]
    assert not manager.capability_registry._native_instances

@pytest.mark.asyncio
@pytest.mark.parametrize("origin", ["native", "plugin"])
@pytest.mark.parametrize("late_failure", [False, True])
@pytest.mark.parametrize("cancellation", ["timeout", "once", "repeated"])
async def test_late_initialization_finishes_before_owned_cleanup(
    manager, monkeypatch, origin, late_failure, cancellation,
):
    from core.adapter import capability_registry as module
    from tests.test_adapter_capability_extensions import account

    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "CAPABILITY_CANCELLATION_GRACE", 0.01)
    entered, release = asyncio.Event(), asyncio.Event()
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    created = []
    tasks = []
    capabilities = manager.capability_registry

    class LateCapability(BaseCapability):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.resource = None
            self.close_count = 0
            created.append(self)

        async def initialize(self):
            tasks.append(asyncio.current_task())
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            self.resource = object()
            self.adapter.access.set_policy(
                capability_type=LateCapability, permission="post",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )
            if late_failure:
                raise RuntimeError("late initialization failure")

        async def terminate(self):
            self.resource = None
            self.close_count += 1

    adapter = await account(manager) if origin == "plugin" else ExampleAdapter(AdapterContext(
        AdapterInfo(True, "native", "native", "qq"), asyncio.Queue(),
    ))
    adapter.access.set_policy(
        capability_type=LateCapability, permission="post", policy=original,
    )
    if origin == "native":
        adapter.register_capability(LateCapability, LateCapability(adapter))
        operation = capabilities.initialize_native(adapter)
    else:
        operation = capabilities.register("plugin", "qq", LateCapability, LateCapability)
    pending = asyncio.create_task(operation)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        if cancellation != "timeout":
            for _ in range(3 if cancellation == "repeated" else 1):
                pending.cancel()
                await asyncio.sleep(0)
        expected = asyncio.TimeoutError if cancellation == "timeout" else asyncio.CancelledError
        with pytest.raises(expected):
            await pending
        assert created[0].close_count == 0
        await capabilities.register("other", "unrelated", LateCapability, LateCapability)
        if origin == "plugin":
            with pytest.raises(RuntimeError, match="cleanup"):
                await capabilities.register("replacement", "qq", LateCapability, LateCapability)
        else:
            with pytest.raises(RuntimeError, match="cleanup"):
                await capabilities.initialize_native(adapter)
    finally:
        release.set()
        await asyncio.gather(pending, *tasks, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.gather(*getattr(capabilities, "_cleanup_tasks", ()), return_exceptions=True)
        await asyncio.sleep(0)

    assert created[0].resource is None and created[0].close_count == 1
    assert adapter.access.get_policies(LateCapability) == {"post": original}
    assert (LateCapability in adapter.capabilities) is (origin == "native")
    assert not capabilities._hook_tasks
    assert not capabilities._pending_cleanup
    late_failure = False
    if origin == "plugin":
        await capabilities.register("replacement", "qq", LateCapability, LateCapability)
        await capabilities.unregister_owner("replacement")
    else:
        await capabilities.initialize_native(adapter)
        await capabilities.detach(adapter)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["unregister", "unregister_owner", "detach"])
async def test_repeated_cancellation_keeps_cleanup_and_policy_rollback_serialized(
    manager, operation,
):
    from tests.test_adapter_capability_extensions import account

    adapter = await account(manager)
    capabilities = manager.capability_registry
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    old_policy = ListAccessPolicy("deny_list", frozenset())
    new_policy = ListAccessPolicy("allow_list", frozenset({"replacement"}))
    entered, release = asyncio.Event(), asyncio.Event()
    cleanup = replacement = None
    tasks = []

    class Kind(BaseCapability):
        pass

    def install(policy):
        adapter.access.set_policy(capability_type=Kind, permission="post", policy=policy)

    class Old(Kind):
        async def initialize(self):
            install(old_policy)

        async def terminate(self):
            tasks.append(asyncio.current_task())
            entered.set()
            await release.wait()

    class New(Kind):
        async def initialize(self):
            install(new_policy)

    install(original)
    await capabilities.register("old", "qq", Kind, Old)
    if operation == "unregister":
        pending = capabilities.unregister("old", "qq", Kind)
    elif operation == "unregister_owner":
        pending = capabilities.unregister_owner("old")
    else:
        pending = capabilities.detach(adapter)
    cleanup = asyncio.create_task(pending)
    try:
        await asyncio.wait_for(entered.wait(), 1)
        for _ in range(3):
            cleanup.cancel()
            await asyncio.sleep(0)
        assert not cleanup.done()
        assert capabilities._lock.locked()
        if operation == "detach":
            replacement = asyncio.create_task(capabilities.attach(adapter))
        else:
            replacement = asyncio.create_task(capabilities.register("new", "qq", Kind, New))
        await asyncio.sleep(0)
        assert not replacement.done()
    finally:
        release.set()
        await asyncio.gather(cleanup, *tasks, return_exceptions=True)
        if replacement is not None:
            await replacement

    with pytest.raises(asyncio.CancelledError):
        await cleanup
    await capabilities.unregister_owner("old" if operation == "detach" else "new")
    assert adapter.access.get_policies(Kind) == {"post": original}
    assert not capabilities._hook_tasks


@pytest.mark.asyncio
@pytest.mark.parametrize("later_change", [False, True])
async def test_late_termination_reserves_scope_until_policy_restoration(
    manager, monkeypatch, later_change,
):
    from core.adapter import capability_registry as module
    from tests.test_adapter_capability_extensions import account

    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "CAPABILITY_CANCELLATION_GRACE", 0.01)
    adapter = await account(manager)
    capabilities = manager.capability_registry
    release = asyncio.Event()
    tasks = []
    original = ListAccessPolicy("allow_list", frozenset({"owner"}))
    later = ListAccessPolicy("allow_list", frozenset({"later"}))

    class Kind(BaseCapability):
        pass

    class Old(Kind):
        async def initialize(self):
            adapter.access.set_policy(
                capability_type=Kind, permission="post",
                policy=ListAccessPolicy("deny_list", frozenset()),
            )

        async def terminate(self):
            tasks.append(asyncio.current_task())
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()

    adapter.access.set_policy(capability_type=Kind, permission="post", policy=original)
    await capabilities.register("old", "qq", Kind, Old)
    try:
        await capabilities.unregister_owner("old")
        with pytest.raises(RuntimeError, match="cleanup"):
            await capabilities.register("new", "qq", Kind, Kind)
        await capabilities.register("other", "unrelated", Kind, Kind)
        if later_change:
            adapter.access.set_policy(capability_type=Kind, permission="post", policy=later)
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.gather(*getattr(capabilities, "_cleanup_tasks", ()), return_exceptions=True)
        await asyncio.sleep(0)
    assert adapter.access.get_policies(Kind) == {"post": later if later_change else original}
    await capabilities.register("new", "qq", Kind, Kind)
    await capabilities.unregister_owner("new")
    assert adapter.access.get_policies(Kind) == {"post": later if later_change else original}


@pytest.mark.asyncio
@pytest.mark.parametrize("termination_failure", [False, True])
async def test_deferred_initialization_and_termination_finish_one_lifecycle(
    manager, monkeypatch, termination_failure,
):
    from core.adapter import capability_registry as module
    from tests.test_adapter_capability_extensions import account

    monkeypatch.setattr(module, "CAPABILITY_LIFECYCLE_TIMEOUT", 0.01)
    monkeypatch.setattr(module, "CAPABILITY_CANCELLATION_GRACE", 0.01)
    adapter = await account(manager)
    capabilities = manager.capability_registry
    initialize_release, terminate_release, terminating = (
        asyncio.Event(), asyncio.Event(), asyncio.Event(),
    )
    tasks, created = [], []

    class Kind(BaseCapability):
        def __init__(self, adapter):
            super().__init__(adapter)
            self.resource = None
            self.closed = 0
            created.append(self)

        async def initialize(self):
            tasks.append(asyncio.current_task())
            try:
                await initialize_release.wait()
            except asyncio.CancelledError:
                await initialize_release.wait()
            self.resource = object()

        async def terminate(self):
            tasks.append(asyncio.current_task())
            terminating.set()
            try:
                await terminate_release.wait()
            except asyncio.CancelledError:
                await terminate_release.wait()
            self.resource = None
            self.closed += 1
            if termination_failure:
                raise RuntimeError("late termination failure")

    try:
        with pytest.raises(asyncio.TimeoutError):
            await capabilities.register("plugin", "qq", Kind, Kind)
        initialize_release.set()
        await asyncio.wait_for(terminating.wait(), 1)
        await asyncio.gather(*capabilities._cleanup_tasks, return_exceptions=True)
        assert created[0].resource is not None and created[0].closed == 0
        with pytest.raises(RuntimeError, match="cleanup"):
            await capabilities.register("replacement", "qq", Kind, Kind)
        assert len(created) == 1
    finally:
        initialize_release.set()
        terminate_release.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await asyncio.sleep(0)
        await asyncio.gather(*capabilities._cleanup_tasks, return_exceptions=True)
        await asyncio.sleep(0)
    assert created[0].resource is None and created[0].closed == 1
    assert not capabilities._hook_tasks
    assert not capabilities._cleanup_tasks
    assert not capabilities._pending_cleanup


@pytest.mark.asyncio
async def test_builtin_reserves_name_before_native_initialization(manager):
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    class SlowCapability(BaseCapability):
        async def initialize(self):
            entered.set()
            await release.wait()

    class BuiltinAdapter(ExampleAdapter):
        async def start(self):
            started.append(self)
            await super().start()

    info = AdapterInfo(True, "reserved", "reserved", "qq")
    first = BuiltinAdapter(AdapterContext(info, asyncio.Queue()))
    second = BuiltinAdapter(AdapterContext(info, asyncio.Queue()))
    first.register_capability(SlowCapability, SlowCapability(first))
    pending = asyncio.create_task(manager.register_builtin_adapter(first))
    contender = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        contender = asyncio.create_task(manager.register_builtin_adapter(second))
        done, _ = await asyncio.wait({contender}, timeout=0.1)
        assert contender in done
        with pytest.raises(ValueError, match="already in use"):
            await contender
        assert manager.get_adapter("reserved") is None
        release.set()
        await pending
        assert manager.get_adapter("reserved") is first
        assert started == [first]
        assert second not in manager.capability_registry._native_instances
    finally:
        release.set()
        await asyncio.gather(
            pending, *([contender] if contender is not None else []), return_exceptions=True,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_builtin_registration_releases_reserved_name(manager, cancel):
    entered, release = asyncio.Event(), asyncio.Event()

    class FailingCapability(BaseCapability):
        async def initialize(self):
            entered.set()
            await release.wait()
            raise RuntimeError("initialization failed")

    info = AdapterInfo(True, "reserved", "reserved", "qq")
    first = ExampleAdapter(AdapterContext(info, asyncio.Queue()))
    first.register_capability(FailingCapability, FailingCapability(first))
    pending = asyncio.create_task(manager.register_builtin_adapter(first))
    try:
        await asyncio.wait_for(entered.wait(), 1)
        assert "reserved" in manager._builtin_names
        if cancel:
            pending.cancel()
        else:
            release.set()
        with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
            await pending
        assert "reserved" not in manager._builtin_names
        replacement = ExampleAdapter(AdapterContext(info, asyncio.Queue()))
        await manager.register_builtin_adapter(replacement)
        assert manager.get_adapter("reserved") is replacement
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


@pytest.mark.asyncio
async def test_builtin_reservation_wins_over_unpublished_configured_adapter(manager):
    entered, release = asyncio.Event(), asyncio.Event()
    started = []

    class SlowCapability(BaseCapability):
        async def initialize(self):
            entered.set()
            await release.wait()

    class SlowAdapter(ExampleAdapter):
        def __init__(self, ctx):
            super().__init__(ctx)
            self.register_capability(SlowCapability, SlowCapability(self))

        async def start(self):
            started.append(self)
            await super().start()

    manager._registry["qq"] = SlowAdapter
    info = AdapterInfo(True, "reserved", "reserved", "qq")
    builtin = ExampleAdapter(AdapterContext(info, asyncio.Queue()))
    configured = asyncio.create_task(manager.register_adapter(info))
    contender = None
    try:
        await asyncio.wait_for(entered.wait(), 1)
        contender = asyncio.create_task(manager.register_builtin_adapter(builtin))
        await asyncio.sleep(0)
        assert "reserved" in manager._builtin_names
        release.set()
        results = await asyncio.wait_for(
            asyncio.gather(configured, contender, return_exceptions=True), 1,
        )
        assert isinstance(results[0], ValueError)
        assert results[1] is None
        assert manager.get_adapter("reserved") is builtin
        assert not started
        assert "reserved" in manager._builtin_names
        assert builtin in manager.capability_registry._native_instances
        assert len(manager.capability_registry._native_instances) == 1
    finally:
        release.set()
        await asyncio.gather(
            configured, *([contender] if contender is not None else []), return_exceptions=True,
        )
