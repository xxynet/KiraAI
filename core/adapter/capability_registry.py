"""Plugin capability factories and shared native/extension resource lifecycles."""

from __future__ import annotations

import asyncio
import inspect
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Callable

from core.logging_manager import get_logger
from .access import AccessPolicy
from .base import BaseAdapter, BaseCapability

logger = get_logger("adapter_capabilities", "blue")
CAPABILITY_LIFECYCLE_TIMEOUT = 15.0
CAPABILITY_CANCELLATION_GRACE = 1.0
_active_registry: ContextVar[object | None] = ContextVar("active_capability_registry", default=None)


@dataclass(eq=False)
class _Attachment:
    adapter: BaseAdapter
    kind: type[BaseCapability]
    capability: BaseCapability
    original_policies: dict[str, AccessPolicy]
    applied_policies: dict[str, AccessPolicy] = field(default_factory=dict)
    unregister_on_cleanup: bool = True


@dataclass
class _Binding:
    owner: str
    platform: str
    kind: type[BaseCapability]
    factory: Callable[[BaseAdapter], BaseCapability]
    instances: dict[BaseAdapter, _Attachment] = field(default_factory=dict)


class AdapterCapabilityRegistry:
    """Serialize extension mutations and optional capability lifecycle hooks.

    Factories are synchronous resource-free constructors. Lifecycle hooks are
    asynchronous and must not mutate this registry, directly or through tasks.
    Read-only adapter and capability lookups remain available from hooks.
    """

    def __init__(self, manager):
        self.manager = manager
        self._bindings: dict[tuple[str, type[BaseCapability]], _Binding] = {}
        self._native_instances: dict[BaseAdapter, list[_Attachment]] = {}
        self._blocked_owners: set[str] = set()
        self._lock = asyncio.Lock()
        self._hook_tasks: set[asyncio.Task] = set()

    def _check_reentrancy(self):
        if _active_registry.get() is self:
            raise RuntimeError("Capability lifecycle hooks cannot mutate capability registrations")

    def block_owner(self, owner: str):
        """Prevent registrations while a plugin is shutting down."""
        self._check_reentrancy()
        self._blocked_owners.add(owner)

    def allow_owner(self, owner: str):
        self._check_reentrancy()
        self._blocked_owners.discard(owner)

    def _check_owner(self, owner: str):
        if owner in self._blocked_owners:
            raise RuntimeError("Plugin capability registrations are shutting down")

    @staticmethod
    def _validate_key(platform, kind):
        if not isinstance(platform, str) or not platform.strip():
            raise ValueError("Adapter platform must be a non-empty string")
        if not isinstance(kind, type) or not issubclass(kind, BaseCapability):
            raise TypeError("capability_type must be a BaseCapability subclass")
        return platform.strip()

    async def _prepare(self, binding, adapter, prepared):
        token = _active_registry.set(self)
        try:
            original_policies = adapter.access.get_policies(binding.kind)
            try:
                capability = binding.factory(adapter)
                if inspect.isawaitable(capability):
                    if inspect.iscoroutine(capability):
                        capability.close()
                    raise TypeError("Capability factory must return an instance synchronously")
                adapter._validate_capability_registration(binding.kind, capability)
            except BaseException:
                adapter.access.restore_policies(
                    binding.kind, original_policies, adapter.access.get_policies(binding.kind),
                )
                raise
            attachment = await self._initialize(
                adapter, binding.kind, capability, prepared, original_policies=original_policies,
            )
            self._check_owner(binding.owner)
            return attachment
        finally:
            _active_registry.reset(token)

    async def _initialize(
        self, adapter, kind, capability, prepared, *, unregister_on_cleanup=True,
        original_policies=None,
    ):
        if original_policies is None:
            original_policies = adapter.access.get_policies(kind)
        attachment = _Attachment(
            adapter, kind, capability, original_policies,
            unregister_on_cleanup=unregister_on_cleanup,
        )
        prepared.append(attachment)
        try:
            await self._call_hook(capability, "initialize")
        finally:
            attachment.applied_policies = adapter.access.get_policies(kind)
        return attachment

    async def _call_hook(self, capability, name):
        hook = getattr(capability, name)
        # Optional inherited no-ops need no task or scheduling point.
        if getattr(hook, "__func__", None) is getattr(BaseCapability, name):
            return
        task = asyncio.create_task(hook())
        self._hook_tasks.add(task)
        task.add_done_callback(self._hook_done)
        try:
            done, _ = await asyncio.wait({task}, timeout=CAPABILITY_LIFECYCLE_TIMEOUT)
            if not done:
                raise asyncio.TimeoutError
            task.result()
        finally:
            if not task.done():
                task.cancel()
                # Cancellation is cooperative; a hook must not hold the registry forever.
                done, _ = await asyncio.wait({task}, timeout=CAPABILITY_CANCELLATION_GRACE)
                if not done:
                    logger.warning(
                        f"Capability {name} hook did not stop after cancellation; "
                        "task remains tracked until completion"
                    )

    def _hook_done(self, task):
        self._hook_tasks.discard(task)
        if not task.cancelled():
            # Also observe failures from hooks that outlive their cancellation grace.
            task.exception()

    async def _prepare_native(self, adapter, prepared):
        token = _active_registry.set(self)
        try:
            extensions = [
                attachment.capability for binding in self._bindings.values()
                for attachment in binding.instances.values() if attachment.adapter is adapter
            ]
            for kind, capability in adapter.get_capabilities().items():
                if not any(capability is extension for extension in extensions):
                    await self._initialize(
                        adapter, kind, capability, prepared, unregister_on_cleanup=False,
                    )
        finally:
            _active_registry.reset(token)

    async def initialize_native(self, adapter: BaseAdapter) -> None:
        """Initialize native capabilities once before the adapter runner starts."""
        self._check_reentrancy()
        async with self._lock:
            if adapter in self._native_instances:
                return
            prepared = []
            try:
                await self._prepare_native(adapter, prepared)
                self._native_instances[adapter] = prepared
            except BaseException:
                await self._cleanup(prepared)
                raise

    async def _dispose(self, attachments):
        token = _active_registry.set(self)
        try:
            # Withdraw the whole transaction before awaiting any resource cleanup.
            for attachment in attachments:
                if attachment.unregister_on_cleanup:
                    attachment.adapter.unregister_capability(attachment.kind, attachment.capability)
            for attachment in reversed(attachments):
                try:
                    await self._call_hook(attachment.capability, "terminate")
                except (Exception, asyncio.CancelledError) as exc:
                    # Never log exception text from platform clients or credentials.
                    logger.error(
                        f"Capability cleanup failed ({type(exc).__name__}) "
                        f"for adapter {attachment.adapter.info.name}"
                    )
                finally:
                    registered = attachment.adapter.capabilities.get(attachment.kind)
                    if registered is None or (
                        not attachment.unregister_on_cleanup and registered is attachment.capability
                    ):
                        attachment.adapter.access.restore_policies(
                            attachment.kind, attachment.original_policies,
                            attachment.applied_policies,
                        )
        finally:
            _active_registry.reset(token)

    async def _cleanup(self, attachments):
        if not attachments:
            return
        task = asyncio.create_task(self._dispose(attachments))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # A cancelled registration/unload must still finish owned cleanup.
            await asyncio.shield(task)
            raise

    async def register(self, owner, platform, capability_type, factory) -> None:
        self._check_reentrancy()
        platform = self._validate_key(platform, capability_type)
        if not callable(factory) or inspect.iscoroutinefunction(factory) or inspect.iscoroutinefunction(
            getattr(factory, "__call__", None),
        ):
            raise TypeError("Capability factory must be a synchronous callable")
        binding = _Binding(owner, platform, capability_type, factory)
        key = (platform, capability_type)
        async with self._lock:
            self._check_owner(owner)
            kinds = {
                cls for cls in capability_type.__mro__ if BaseCapability in cls.__bases__
            } or {BaseCapability}
            for existing in self._bindings.values():
                existing_kinds = {
                    cls for cls in existing.kind.__mro__ if BaseCapability in cls.__bases__
                } or {BaseCapability}
                if existing.platform == platform and (
                    existing.kind is capability_type or kinds & existing_kinds
                ):
                    raise ValueError("A capability of this kind is already registered for this platform")
            prepared = []
            try:
                adapters = list(self.manager.get_adapters().values())
                for adapter in adapters:
                    if adapter.info.platform == platform:
                        await self._prepare(binding, adapter, prepared)
                self._check_owner(owner)
                for attachment in prepared:
                    if self.manager.get_adapter(attachment.adapter.info.name) is not attachment.adapter:
                        raise RuntimeError("Adapter changed during capability initialization")
                    attachment.adapter.register_capability(capability_type, attachment.capability)
                    binding.instances[attachment.adapter] = attachment
                self._bindings[key] = binding
            except BaseException:
                await self._cleanup(prepared)
                raise

    async def unregister(self, owner, platform, capability_type) -> bool:
        self._check_reentrancy()
        platform = self._validate_key(platform, capability_type)
        key = (platform, capability_type)
        async with self._lock:
            binding = self._bindings.get(key)
            if binding is None or binding.owner != owner:
                return False
            del self._bindings[key]
            await self._cleanup(list(binding.instances.values()))
            binding.instances.clear()
            return True

    async def unregister_owner(self, owner) -> None:
        self._check_reentrancy()
        async with self._lock:
            bindings = [
                binding for binding in self._bindings.values() if binding.owner == owner
            ]
            attachments = []
            for binding in bindings:
                del self._bindings[(binding.platform, binding.kind)]
                attachments.extend(binding.instances.values())
                binding.instances.clear()
            await self._cleanup(attachments)

    async def attach(self, adapter: BaseAdapter) -> None:
        """Apply active factories before publishing a newly constructed adapter."""
        self._check_reentrancy()
        async with self._lock:
            prepared = []
            selected = []
            native = None
            try:
                if adapter not in self._native_instances:
                    await self._prepare_native(adapter, prepared)
                    native = list(prepared)
                for binding in self._bindings.values():
                    if (
                        binding.platform != adapter.info.platform
                        or binding.owner in self._blocked_owners
                        or adapter in binding.instances
                    ):
                        continue
                    attachment = await self._prepare(binding, adapter, prepared)
                    selected.append((binding, attachment))
                for binding, attachment in selected:
                    self._check_owner(binding.owner)
                    adapter.register_capability(binding.kind, attachment.capability)
                    binding.instances[adapter] = attachment
                if native is not None:
                    self._native_instances[adapter] = native
            except BaseException:
                for binding, _ in selected:
                    binding.instances.pop(adapter, None)
                await self._cleanup(prepared)
                raise

    async def detach(self, adapter: BaseAdapter) -> None:
        self._check_reentrancy()
        async with self._lock:
            attachments = self._native_instances.pop(adapter, [])
            for binding in self._bindings.values():
                attachment = binding.instances.pop(adapter, None)
                if attachment is not None:
                    attachments.append(attachment)
            await self._cleanup(attachments)
