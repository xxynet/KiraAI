import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from core.chat.session import Session
from core.plugin.builtin_plugins.session_tools.handoff import HANDOFF_KEY, SessionHandoff
from core.plugin.builtin_plugins.session_tools.main import SessionPlugin


A = "test:gm:a"
B = "test:dm:b"
C = "test:gm:c"


def event(sid, metadata=None, *, user_input=False):
    messages = []
    if metadata is not None:
        messages.append(SimpleNamespace(is_notice=True, extra=metadata))
    if user_input:
        messages.append(SimpleNamespace(is_notice=False, extra=None))
    return SimpleNamespace(sid=sid, messages=messages, extra=None)


@pytest.fixture
def plugin(monkeypatch):
    async def resolve(target):
        return Session(*target.split(":", 2))

    ctx = SimpleNamespace(
        session_mgr=SimpleNamespace(resolve_session=AsyncMock(side_effect=resolve)),
        adapter_mgr=SimpleNamespace(get_adapter=Mock(return_value=SimpleNamespace(
            get_capability=Mock(return_value=SimpleNamespace(is_allowed=Mock(return_value=True))),
        ))),
        publish_notice=AsyncMock(),
    )
    monkeypatch.setattr("core.plugin.builtin_plugins.session_tools.main.logger", Mock())
    return SessionPlugin(ctx, {})


def next_event(plugin, sid):
    return event(sid, plugin.ctx.publish_notice.await_args.kwargs["extra"])


@pytest.mark.anyio
async def test_round_trip_keeps_lineage_and_logs_full_description(plugin):
    from core.plugin.builtin_plugins.session_tools.main import logger

    assert await plugin.session_send(event(A), B, "询问小红今晚是否有空") == "message sent"
    first = next_event(plugin, B)
    assert await plugin.session_send(first, A, "小红答复今晚有空，回来源群告知小明") == "message sent"
    returned = next_event(plugin, A)
    first_trace = first.messages[0].extra[HANDOFF_KEY]
    last_trace = returned.messages[0].extra[HANDOFF_KEY]
    assert last_trace.chain is first_trace.chain
    assert last_trace.hops == 2
    records = [json.loads(call.args[1]) for call in logger.info.call_args_list]
    assert records[1]["parent_id"] == records[0]["transfer_id"]
    assert records[1]["chain_id"] == records[0]["chain_id"]
    assert records[1]["description"] == "小红答复今晚有空，回来源群告知小明"
    assert [item["status"] for item in records] == ["sent", "sent"]
    assert [item["source"] for item in records] == [A, B]
    assert [item["target"] for item in records] == [B, A]


@pytest.mark.anyio
async def test_changed_descriptions_cannot_evade_default_budget(plugin):
    current = event(A)
    for index in range(8):
        target = B if current.sid == A else A
        assert await plugin.session_send(current, target, f"继续讨论第 {index} 步") == "message sent"
        current = next_event(plugin, target)
    assert "chain limit of 8" in await plugin.session_send(current, C, "换个会话继续")
    assert plugin.ctx.publish_notice.await_count == 8


@pytest.mark.anyio
async def test_duplicate_detection_normalizes_whitespace_and_allows_return(plugin):
    root = event(A)
    assert await plugin.session_send(root, B, "请确认 今晚安排") == "message sent"
    at_b = next_event(plugin, B)
    assert await plugin.session_send(at_b, A, "已确认，可以参加") == "message sent"
    returned = next_event(plugin, A)
    assert "repeated source, target and description" in await plugin.session_send(returned, B, "请确认\n 今晚安排")
    assert "repeated source, target and description" in await plugin.session_send(root, B, "请确认 今晚安排")
    assert plugin.ctx.publish_notice.await_count == 2


@pytest.mark.anyio
async def test_duplicate_window_expires_without_resetting_budget(plugin, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr("core.plugin.builtin_plugins.session_tools.handoff.time.time", lambda: clock[0])
    root = event(A)
    assert await plugin.session_send(root, B, "相同内容") == "message sent"
    clock[0] += 301
    assert await plugin.session_send(root, B, "相同内容") == "message sent"
    assert len(SessionHandoff.for_event(root).chain.transfers) == 2


@pytest.mark.anyio
async def test_parallel_branches_share_budget(plugin):
    plugin.plugin_cfg = {"cross_session_send": {"max_transfers": 3}}
    root = event(A)
    assert await plugin.session_send(root, B, "询问私聊") == "message sent"
    at_b = next_event(plugin, B)
    assert await plugin.session_send(root, C, "询问群聊") == "message sent"
    at_c = next_event(plugin, C)
    results = await asyncio.gather(
        plugin.session_send(at_b, C, "转达结果"),
        plugin.session_send(at_c, B, "同步安排"),
    )
    assert results.count("message sent") == 1
    assert sum("chain limit of 3" in result for result in results) == 1
    assert plugin.ctx.publish_notice.await_count == 3


@pytest.mark.anyio
async def test_concurrent_duplicate_reserves_before_publish(plugin):
    started = asyncio.Event()
    release = asyncio.Event()

    async def publish(*args, **kwargs):
        started.set()
        await release.wait()

    plugin.ctx.publish_notice.side_effect = publish
    root = event(A)
    first = asyncio.create_task(plugin.session_send(root, B, "确认时间"))
    await asyncio.wait_for(started.wait(), 2)
    try:
        assert "repeated source, target and description" in await plugin.session_send(root, B, "确认时间")
    finally:
        release.set()
        assert await first == "message sent"
    assert plugin.ctx.publish_notice.await_count == 1


@pytest.mark.anyio
async def test_user_message_resets_chain_even_in_mixed_batch(plugin):
    plugin.plugin_cfg = {"cross_session_send": {"max_transfers": 1}}
    assert await plugin.session_send(event(A), B, "旧任务") == "message sent"
    metadata = plugin.ctx.publish_notice.await_args.kwargs["extra"]
    old_chain = metadata[HANDOFF_KEY].chain
    assert "chain limit" in await plugin.session_send(event(B, metadata), A, "旧任务返回")
    for source in (event(B, user_input=True), event(B, metadata, user_input=True)):
        assert await plugin.session_send(source, A, "用户的新任务") == "message sent"
        assert plugin.ctx.publish_notice.await_args.kwargs["extra"][HANDOFF_KEY].chain is not old_chain


@pytest.mark.anyio
async def test_failed_delivery_can_retry_but_still_consumes_budget(plugin):
    from core.plugin.builtin_plugins.session_tools.main import logger

    plugin.plugin_cfg = {"cross_session_send": {"max_transfers": 2}}
    plugin.ctx.publish_notice.side_effect = RuntimeError("complete failure details")
    root = event(A)
    assert await plugin.session_send(root, B, "重试内容") == "failed to send: complete failure details"
    assert json.loads(logger.info.call_args.args[1])["status"] == "failed"
    plugin.ctx.publish_notice.side_effect = None
    assert await plugin.session_send(root, B, "重试内容") == "message sent"
    assert "chain limit of 2" in await plugin.session_send(root, C, "超过预算")


@pytest.mark.anyio
async def test_permissions_are_checked_and_denials_are_logged(plugin):
    from core.plugin.builtin_plugins.session_tools.main import logger

    plugin.ctx.adapter_mgr.get_adapter.return_value.get_capability.return_value.is_allowed.return_value = False
    root = event(A)
    assert "Permission denied" in await plugin.session_send(root, B, "交接内容")
    plugin.ctx.publish_notice.assert_not_awaited()
    assert SessionHandoff.for_event(root).chain.transfers == []
    record = json.loads(logger.info.call_args.args[1])
    assert record["status"] == "denied" and record["description"] == "交接内容"


@pytest.mark.anyio
async def test_cancellation_is_logged_and_keeps_budget_reservation(plugin):
    from core.plugin.builtin_plugins.session_tools.main import logger

    plugin.plugin_cfg = {"cross_session_send": {"max_transfers": 1}}
    plugin.ctx.publish_notice.side_effect = asyncio.CancelledError()
    root = event(A)
    with pytest.raises(asyncio.CancelledError):
        await plugin.session_send(root, B, "取消的任务")
    assert json.loads(logger.info.call_args.args[1])["status"] == "cancelled"
    assert "chain limit of 1" in await plugin.session_send(root, C, "继续尝试")


@pytest.mark.anyio
async def test_merged_notices_keep_the_most_consumed_chain(plugin):
    plugin.plugin_cfg = {"cross_session_send": {"max_transfers": 2}}
    first = event(A)
    assert await plugin.session_send(first, B, "第一条链") == "message sent"
    first_notice = next_event(plugin, B)
    assert await plugin.session_send(first, B, "第一条链的第二次传递") == "message sent"
    second = event(C)
    assert await plugin.session_send(second, B, "另一条链") == "message sent"
    second_notice = next_event(plugin, B)
    merged = event(B)
    merged.messages = second_notice.messages + first_notice.messages
    assert "chain limit of 2" in await plugin.session_send(merged, A, "合并后仍然受限")
    assert SessionHandoff.for_event(merged).chain is SessionHandoff.for_event(first).chain


@pytest.mark.anyio
@pytest.mark.parametrize("field,value", [("max_transfers", 0), ("max_transfers", True), ("repeat_window_seconds", -1)])
async def test_invalid_policy_does_not_disable_protection(plugin, field, value):
    plugin.plugin_cfg = {"cross_session_send": {field: value}}
    assert "must be a positive integer" in await plugin.session_send(event(A), B, "交接内容")
    plugin.ctx.publish_notice.assert_not_awaited()
