import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.adapter import AdapterContext, BaseAdapter
from core.adapter.adapter_info import AdapterInfo
from core.adapter.adapter_registry import AdapterManager
from tests.test_adapter_manager import _SavingConfig
from tests.test_bilibili_adapter import make_adapter as make_bilibili
from tests.test_qq_adapter import FakeQQClient, lifecycle_adapter
from tests.test_qq_official_adapter import make_adapter as make_official
from tests.test_telegram_discord_adapters import adapter_factory
from tests.test_weixin_oc_adapter import make_adapter as make_weixin


@pytest.fixture(params=["QQ", "QQ Official", "Telegram", "Discord", "weixin_oc", "bilibili"])
def running_adapter(request, monkeypatch, adapter_factory):
    ready = asyncio.Event()
    platform = request.param
    if platform == "QQ":
        monkeypatch.setattr("core.adapter.src.qq.qq.NapCatWebSocketClient", FakeQQClient)
        adapter = lifecycle_adapter()
        ready = adapter.bot.entered
    elif platform == "QQ Official":
        class Client:
            def __init__(self, adapter):
                self.closed = False
                self.close_calls = 0

            async def start(self, **kwargs):
                ready.set()
                await asyncio.Event().wait()

            async def close(self):
                self.closed = True
                self.close_calls += 1

        monkeypatch.setattr("core.adapter.src.qq_official.qq_official._QQOfficialClient", Client)
        adapter = make_official()
    elif platform in ("Telegram", "Discord"):
        adapter = adapter_factory(platform)
        if platform == "Telegram":
            original = adapter.app.updater.start_polling.side_effect

            async def poll(**kwargs):
                await original(**kwargs)
                ready.set()

            adapter.app.updater.start_polling.side_effect = poll
        else:
            async def gateway(token):
                ready.set()
                await asyncio.Event().wait()

            adapter.bot.start.side_effect = gateway
    elif platform == "weixin_oc":
        adapter = make_weixin()
        ready = adapter.client.poll_started
    else:
        adapter = make_bilibili(enable_im=False)
        monkeypatch.setattr("core.adapter.src.bilibili.bilibili.get_bilibili_client", Mock())
        adapter._log_login_status = AsyncMock(side_effect=ready.set)
    return SimpleNamespace(adapter=adapter, ready=ready, platform=platform)


def assert_closed(case):
    adapter = case.adapter
    if case.platform == "QQ":
        assert adapter.bot.shutdown_event.is_set()
        assert adapter.bot.close_calls == 1
    elif case.platform == "QQ Official":
        assert adapter._client_close_task.done()
    elif case.platform == "Telegram":
        assert not adapter.app.running
        assert not adapter.app.updater.running
        adapter.app.shutdown.assert_awaited_once()
    elif case.platform == "Discord":
        assert adapter.bot.closed
        adapter.bot.close.assert_awaited_once()
    elif case.platform == "weixin_oc":
        assert adapter.client.close_count == 1
    else:
        assert adapter._run_task.done()
        assert adapter._comment_task is None
        assert adapter._dm_task is None
        assert adapter.listening_task is None


@pytest.mark.asyncio
async def test_start_lives_until_stop_and_duplicate_waiter_cancellation_is_isolated(running_adapter):
    case = running_adapter
    task = asyncio.create_task(case.adapter.start())
    duplicate = None
    try:
        await asyncio.wait_for(case.ready.wait(), 1)
        assert not task.done()
        duplicate = asyncio.create_task(case.adapter.start())
        await asyncio.sleep(0)
        assert not duplicate.done()
        duplicate.cancel()
        with pytest.raises(asyncio.CancelledError):
            await duplicate
        assert not task.done()
        await case.adapter.stop()
        await asyncio.gather(task, return_exceptions=True)
        assert task.done()
        assert_closed(case)
    finally:
        if duplicate and not duplicate.done():
            duplicate.cancel()
        await case.adapter.stop()
        await asyncio.gather(task, *([duplicate] if duplicate else []), return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("before_runner", [False, True])
async def test_cancelling_public_start_waits_for_owned_resource_cleanup(running_adapter, before_runner):
    case = running_adapter
    task = asyncio.create_task(case.adapter.start())
    try:
        if before_runner:
            await asyncio.sleep(0)
        else:
            await asyncio.wait_for(case.ready.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert_closed(case)
    finally:
        await case.adapter.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_manager_keeps_and_observes_public_lifetime_task(running_adapter):
    case = running_adapter
    adapter = case.adapter
    name = adapter.info.name
    manager = AdapterManager.__new__(AdapterManager)
    manager._adapters = {name: adapter}
    manager._adapter_tasks = {}
    manager.kira_config = _SavingConfig({"adapters": {
        adapter.info.adapter_id: {"enabled": True},
    }})
    manager.adas_config = manager.kira_config["adapters"]
    try:
        await manager.start_adapter(name)
        task = manager._adapter_tasks[name]
        await asyncio.wait_for(case.ready.wait(), 1)
        await manager.start_adapter(name)
        assert manager._adapter_tasks[name] is task
        assert not task.done()
        await manager.stop_adapter(name)
        assert task.done()
        assert name not in manager._adapter_tasks
        assert name not in manager._adapters
        assert_closed(case)
    finally:
        await manager.stop_adapter(name)


class LifetimeAdapter(BaseAdapter):
    def __init__(self, ctx, error=None):
        super().__init__(ctx)
        self.release = asyncio.Event()
        self.error = error
        self.cleaned = False

    async def start(self):
        try:
            await self.release.wait()
            if self.error:
                raise self.error
        finally:
            self.cleaned = True

    async def stop(self):
        self.release.set()

    def get_client(self):
        return None


def manager_for(adapter):
    manager = AdapterManager.__new__(AdapterManager)
    manager._adapters = {adapter.info.name: adapter}
    manager._adapter_tasks = {}
    manager.kira_config = _SavingConfig({"adapters": {
        adapter.info.adapter_id: {"enabled": True},
    }})
    manager.adas_config = manager.kira_config["adapters"]
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [None, RuntimeError("private-token")])
async def test_manager_handles_normal_exit_and_failure_without_claiming_startup_success(error, monkeypatch):
    info = AdapterInfo(True, "test", "test", "test")
    adapter = LifetimeAdapter(AdapterContext(info, asyncio.Queue()), error)
    manager = manager_for(adapter)
    logger = Mock()
    monkeypatch.setattr("core.adapter.adapter_registry.logger", logger)
    await manager.start_adapter(info.name)
    task = manager._adapter_tasks[info.name]
    adapter.release.set()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert adapter.cleaned
    assert not manager._adapters and not manager._adapter_tasks
    assert manager.kira_config["adapters"][info.adapter_id]["enabled"] is (error is None)
    assert "Started adapter" not in str(logger.mock_calls)
    assert "private-token" not in str(logger.mock_calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["return", "error", "cancel"])
async def test_old_run_completion_does_not_remove_or_disable_a_replacement(outcome):
    info = AdapterInfo(True, "same-id", "same-name", "test")
    old = LifetimeAdapter(AdapterContext(info, asyncio.Queue()), RuntimeError("old failure") if outcome == "error" else None)
    replacement = LifetimeAdapter(AdapterContext(info, asyncio.Queue()))
    manager = manager_for(old)
    await manager.start_adapter(info.name)
    old_task = manager._adapter_tasks[info.name]
    manager._adapters[info.name] = replacement
    manager._adapter_tasks.pop(info.name)
    await manager.start_adapter(info.name)
    replacement_task = manager._adapter_tasks[info.name]
    try:
        if outcome == "cancel":
            old_task.cancel()
        else:
            old.release.set()
        await asyncio.gather(old_task, return_exceptions=True)
        await asyncio.sleep(0)
        assert manager.get_adapter(info.name) is replacement
        assert manager._adapter_tasks[info.name] is replacement_task
        assert manager.kira_config["adapters"][info.adapter_id]["enabled"] is True
        assert manager.kira_config.save_count == 0
    finally:
        await manager.stop_adapter(info.name)


@pytest.mark.asyncio
async def test_cancelled_run_removes_the_instance_without_disabling_its_configuration():
    info = AdapterInfo(True, "cancelled", "cancelled", "test")
    adapter = LifetimeAdapter(AdapterContext(info, asyncio.Queue()))
    manager = manager_for(adapter)
    await manager.start_adapter(info.name)
    task = manager._adapter_tasks[info.name]
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await asyncio.sleep(0)
    assert adapter.cleaned
    assert manager.get_adapter(info.name) is None
    assert not manager._adapter_tasks
    assert manager.kira_config["adapters"][info.adapter_id]["enabled"] is True
    assert manager.kira_config.save_count == 0


@pytest.mark.asyncio
async def test_unrecoverable_platform_failure_reaches_manager_after_cleanup(running_adapter, monkeypatch):
    case = running_adapter
    adapter = case.adapter
    failure = RuntimeError("private-token")
    if case.platform == "QQ":
        adapter.bot.run = AsyncMock(side_effect=failure)
    elif case.platform == "QQ Official":
        async def fail(*args, **kwargs):
            raise failure
        monkeypatch.setattr("core.adapter.src.qq_official.qq_official._QQOfficialClient.start", fail)
    elif case.platform == "Telegram":
        adapter.app.initialize.side_effect = failure
    elif case.platform == "Discord":
        adapter.bot.start.side_effect = failure
    elif case.platform == "weixin_oc":
        adapter._run_loop = AsyncMock(side_effect=failure)
    else:
        adapter._log_login_status.side_effect = failure
    manager = manager_for(adapter)
    name = adapter.info.name
    await manager.start_adapter(name)
    task = manager._adapter_tasks[name]
    try:
        with pytest.raises(RuntimeError) as caught:
            await asyncio.wait_for(task, 1)
        assert caught.value is failure
        await asyncio.sleep(0)
        assert_closed(case)
        assert name not in manager._adapters
        assert name not in manager._adapter_tasks
        assert manager.kira_config["adapters"][adapter.info.adapter_id]["enabled"] is False
        assert manager.kira_config.save_count == 1
    finally:
        await adapter.stop()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_immediate_registration_failure_is_persisted_once(monkeypatch):
    class FailingAdapter(LifetimeAdapter):
        async def start(self):
            raise ValueError("invalid credentials")
    info = AdapterInfo(True, "failure", "failure", "failure")
    manager = manager_for(LifetimeAdapter(AdapterContext(info, asyncio.Queue())))
    manager._adapters.clear()
    manager.event_queue = asyncio.Queue()
    monkeypatch.setattr(manager, "get_adapter_class", lambda _: FailingAdapter)
    with pytest.raises(ValueError, match="invalid credentials"):
        await manager.register_adapter(info)
    await asyncio.sleep(0)
    assert not manager._adapters and not manager._adapter_tasks
    assert manager.kira_config["adapters"][info.adapter_id]["enabled"] is False
    assert manager.kira_config.save_count == 1

@pytest.mark.asyncio
async def test_bilibili_listener_failure_cancels_other_owned_listeners(monkeypatch):
    from core.adapter.src.bilibili import bilibili as platform

    monkeypatch.setattr(platform, "get_bilibili_client", Mock())
    adapter = make_bilibili(sessdata="test-session", bot_uid="123", enable_comment_notifications=True)
    adapter._log_login_status = AsyncMock()
    dm_started = asyncio.Event()
    dm_stopped = asyncio.Event()

    async def dm():
        dm_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            dm_stopped.set()

    async def comments():
        await dm_started.wait()
        raise RuntimeError("comment listener failed")

    adapter._start_im = dm
    adapter._start_comment_notifications = comments
    with pytest.raises(RuntimeError, match="comment listener failed"):
        await asyncio.wait_for(adapter.start(), 1)
    assert dm_stopped.is_set()
    assert adapter._dm_task is None and adapter._comment_task is None
    await adapter.stop()
