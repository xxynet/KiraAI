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
