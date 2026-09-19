"""Tests for the NapCat WebSocket client (core/adapter/src/qq/napcat_client/client.py).

Focuses on the reconnect/close concurrency paths: malformed frames must not
trigger reconnects, close() must fail pending requests immediately, reconnect
exhaustion must notify exactly once, and a close() racing a successful
reconnect must not leave a half-alive connection behind.
"""

import asyncio
import contextlib
import inspect
import json
import time
from typing import Any, Callable, Dict, List, Optional
from unittest.mock import AsyncMock

import pytest
import websockets

from core.adapter.src.qq.napcat_client import client as napcat_client
from core.adapter.src.qq.napcat_client.client import (
    NapCatWebSocketClient,
    _detect_headers_kwarg,
    ws_compatible_connect,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes and helpers
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Scripted stand-in for a websockets client connection.

    Script items are outbound frames (str) or exception instances to raise
    from the receive iterator. Once the script runs out, the iterator blocks
    until close() and then raises ConnectionClosed (like the real library) —
    or raises StopAsyncIteration right away when ``end_instead_of_close`` is
    set.
    """

    def __init__(self, script=(), end_instead_of_close: bool = False) -> None:
        self._script: List[Any] = list(script)
        self.end_instead_of_close = end_instead_of_close
        self.sent: List[str] = []
        self.actions: List[dict] = []
        self.closed = False
        self.close_count = 0
        self._wake = asyncio.Event()

    def push(self, item: Any) -> None:
        self._script.append(item)
        self._wake.set()

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        while True:
            if self._script:
                item = self._script.pop(0)
                if isinstance(item, Exception):
                    raise item
                return item
            if self.closed:
                if self.end_instead_of_close:
                    raise StopAsyncIteration
                raise websockets.exceptions.ConnectionClosed(None, None)
            await self._wake.wait()
            self._wake.clear()

    async def send(self, payload: str) -> None:
        self.sent.append(payload)
        self.actions.append(json.loads(payload))

    async def close(self) -> None:
        self.close_count += 1
        self.closed = True
        self._wake.set()


def make_client(token: Optional[str] = None) -> NapCatWebSocketClient:
    return NapCatWebSocketClient("ws://localhost:3001", access_token=token)


def script_connect(
    monkeypatch: pytest.MonkeyPatch,
    client: NapCatWebSocketClient,
    script: List[Any],
) -> List[int]:
    """Replace ``client.connect`` with a scripted fake.

    Script items are consumed in order; the last item repeats when the script
    runs out. Items: FakeWebSocket -> {"status": "ok"} (assigned to
    client.websocket); str -> {"status": "failed", "message": item};
    callable(n) -> whatever dict it returns.
    """
    calls: List[int] = []
    queue: List[Any] = list(script)
    state: Dict[str, Any] = {"last": None}

    async def fake_connect() -> dict:
        calls.append(len(calls) + 1)
        item = queue.pop(0) if queue else state["last"]
        state["last"] = item
        if callable(item):
            return item(len(calls))
        if isinstance(item, FakeWebSocket):
            client.websocket = item
            return {"status": "ok"}
        return {"status": "failed", "message": str(item)}

    monkeypatch.setattr(client, "connect", fake_connect)
    return calls


def patch_ws_factory(monkeypatch: pytest.MonkeyPatch, ws: FakeWebSocket) -> List[tuple]:
    """Replace the module-level ws_compatible_connect with one returning ``ws``."""
    calls: List[tuple] = []

    async def fake_wrapper(uri, *, extra_headers=None, **kwargs):
        calls.append((uri, extra_headers))
        return ws

    monkeypatch.setattr(napcat_client, "ws_compatible_connect", fake_wrapper)
    return calls


@pytest.fixture
def fast_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make reconnect backoff sleeps instantaneous (sleep(0) still yields)."""
    real_sleep = asyncio.sleep

    async def instant_sleep(delay=0, *args, **kwargs):
        if delay:
            return
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", instant_sleep)


async def wait_until(pred: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met within timeout")


async def await_listener(listener: asyncio.Task) -> None:
    """Await a listener task that close() may have cancelled."""
    with contextlib.suppress(asyncio.CancelledError):
        await asyncio.wait_for(listener, timeout=2)


def track_notify(client: NapCatWebSocketClient) -> List[int]:
    fired: List[int] = []
    client.on_permanent_disconnect = lambda: fired.append(1)
    return fired


def lifecycle_meta_frame() -> str:
    return json.dumps({"post_type": "meta_event", "meta_event_type": "lifecycle"})


# ---------------------------------------------------------------------------
# connect() and the websockets compatibility wrapper
# ---------------------------------------------------------------------------


async def test_connect_sends_bearer_token_header(monkeypatch: pytest.MonkeyPatch):
    captured: Dict[str, Any] = {}

    async def fake_wrapper(uri, *, extra_headers=None, **kwargs):
        captured["uri"] = uri
        captured["extra_headers"] = extra_headers
        return FakeWebSocket()

    monkeypatch.setattr(napcat_client, "ws_compatible_connect", fake_wrapper)

    client = make_client(token="secret")
    resp = await client.connect()

    assert resp == {"status": "ok"}
    assert captured["uri"] == "ws://localhost:3001"
    assert captured["extra_headers"] == {"Authorization": "Bearer secret"}
    assert isinstance(client.websocket, FakeWebSocket)


async def test_connect_without_token_sends_empty_headers(monkeypatch: pytest.MonkeyPatch):
    captured: Dict[str, Any] = {}

    async def fake_wrapper(uri, *, extra_headers=None, **kwargs):
        captured["extra_headers"] = extra_headers
        return FakeWebSocket()

    monkeypatch.setattr(napcat_client, "ws_compatible_connect", fake_wrapper)

    resp = await make_client().connect()

    assert resp == {"status": "ok"}
    assert captured["extra_headers"] == {}


async def test_connect_failure_returns_failed_status(monkeypatch: pytest.MonkeyPatch):
    async def fake_wrapper(uri, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(napcat_client, "ws_compatible_connect", fake_wrapper)

    client = make_client()
    resp = await client.connect()

    assert resp == {"status": "failed", "message": "boom"}
    assert client.websocket is None


async def test_headers_kwarg_detection_matches_installed_websockets():
    detected = _detect_headers_kwarg()
    params = inspect.signature(websockets.connect).parameters
    if "additional_headers" in params:
        assert detected == "additional_headers"
    else:
        assert detected == "extra_headers"


async def test_ws_compatible_connect_forwards_under_detected_name(
    monkeypatch: pytest.MonkeyPatch,
):
    detected = _detect_headers_kwarg()
    captured: Dict[str, Any] = {}

    async def fake_connect(uri, **kwargs):
        captured.update(kwargs)
        return "connection"

    monkeypatch.setattr(websockets, "connect", fake_connect)

    result = await ws_compatible_connect("ws://x", extra_headers={"A": "1"}, open_timeout=1)

    assert result == "connection"
    assert captured[detected] == {"A": "1"}
    other = "extra_headers" if detected == "additional_headers" else "additional_headers"
    assert other not in captured


# ---------------------------------------------------------------------------
# send_action()
# ---------------------------------------------------------------------------


async def test_send_action_raises_immediately_without_socket():
    client = make_client()

    with pytest.raises(ConnectionError, match="get_login_info"):
        await client.send_action("get_login_info", {})


async def test_send_action_roundtrip_resolves_future():
    client = make_client()
    ws = FakeWebSocket()
    client.websocket = ws
    client.login_success_event.set()
    listener = asyncio.create_task(client.listen_messages())

    task = asyncio.create_task(client.send_action("get_login_info", {}, timeout=2))
    await wait_until(lambda: bool(ws.actions))

    assert ws.actions[0]["action"] == "get_login_info"
    echo = ws.actions[0]["echo"]
    ws.push(json.dumps({"status": "ok", "retcode": 0, "data": {"user_id": 1}, "echo": echo}))

    resp = await asyncio.wait_for(task, timeout=2)
    assert resp["data"] == {"user_id": 1}
    assert echo not in client.response_futures

    await client.close()
    await await_listener(listener)


async def test_send_action_response_timeout_discards_future():
    client = make_client()
    client.websocket = FakeWebSocket()
    client.login_success_event.set()

    with pytest.raises(TimeoutError, match="get_login_info"):
        await client.send_action("get_login_info", {}, timeout=0.05)
    assert client.response_futures == {}


async def test_send_action_blocked_on_login_wakes_on_close():
    client = make_client()
    client.websocket = FakeWebSocket()

    task = asyncio.create_task(client.send_action("get_login_info", {}))
    await asyncio.sleep(0.05)
    assert not task.done()

    await client.close()
    with pytest.raises(ConnectionError, match="连接已关闭"):
        await asyncio.wait_for(task, timeout=2)


async def test_send_action_login_wait_times_out(monkeypatch: pytest.MonkeyPatch):
    client = make_client()
    client.websocket = FakeWebSocket()

    # The production code hardcodes a 10s login wait; clamp it so the test
    # stays fast while still pinning the TimeoutError contract.
    real_wait = asyncio.wait

    async def clamped_wait(fs, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout is not None:
            kwargs["timeout"] = min(timeout, 0.05)
        return await real_wait(fs, **kwargs)

    monkeypatch.setattr(asyncio, "wait", clamped_wait)

    with pytest.raises(asyncio.TimeoutError, match="登录成功事件"):
        await client.send_action("get_login_info", {})


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


async def test_close_fails_pending_futures_immediately():
    client = make_client()
    client.websocket = FakeWebSocket()
    fut = asyncio.get_running_loop().create_future()
    client.response_futures["e1"] = fut

    await client.close()

    assert fut.done() and isinstance(fut.exception(), ConnectionError)
    assert client.response_futures == {}
    assert client.shutdown_event.is_set()
    assert client.websocket is None


async def test_close_is_idempotent():
    client = make_client()
    ws = FakeWebSocket()
    client.websocket = ws

    await client.close()
    await client.close()

    assert ws.close_count == 1


async def test_close_cancels_running_listener():
    client = make_client()
    client.websocket = FakeWebSocket()  # receive iterator blocks until close

    listener = asyncio.create_task(client.listen_messages())
    client._listening_task = listener  # run() registers the task the same way
    await asyncio.sleep(0.05)
    assert not listener.done()

    await client.close()
    assert listener.cancelled()


# ---------------------------------------------------------------------------
# _reconnect()
# ---------------------------------------------------------------------------


async def test_reconnect_success_sets_login_event_and_closes_old_socket(
    monkeypatch: pytest.MonkeyPatch, fast_backoff
):
    client = make_client()
    old_ws = FakeWebSocket()
    client.websocket = old_ws
    calls = script_connect(monkeypatch, client, ["first failure", FakeWebSocket()])

    ok = await client._reconnect()

    assert ok is True
    assert client.login_success_event.is_set()
    assert old_ws.close_count == 1
    assert len(calls) == 2
    assert client.websocket is not None and client.websocket is not old_ws


async def test_reconnect_exhaustion_notifies_exactly_once(
    monkeypatch: pytest.MonkeyPatch, fast_backoff
):
    client = make_client()
    fired = track_notify(client)
    client.MAX_RECONNECT_ATTEMPTS = 3
    calls = script_connect(
        monkeypatch, client, [lambda n: {"status": "failed", "message": "down"}]
    )

    ok = await client._reconnect()

    assert ok is False
    assert fired == [1]
    assert len(calls) == 3
    assert client.websocket is None


async def test_reconnect_aborts_without_notify_when_shutdown_set_mid_retry(
    monkeypatch: pytest.MonkeyPatch, fast_backoff
):
    client = make_client()
    fired = track_notify(client)
    calls = script_connect(
        monkeypatch,
        client,
        [
            lambda n: {"status": "failed", "message": "down"},
            lambda n: (client.shutdown_event.set(), {"status": "failed", "message": "down"})[1],
        ],
    )

    ok = await client._reconnect()

    assert ok is False
    assert fired == []
    assert len(calls) == 2


async def test_reconnect_discards_fresh_socket_when_shutdown_raced(
    monkeypatch: pytest.MonkeyPatch,
):
    # Regression for O-1: a successful reconnect landing after close() must
    # not leave the fresh socket open nor fake a successful login.
    client = make_client()
    fresh = FakeWebSocket()

    def connect_once(n):
        client.shutdown_event.set()
        client.websocket = fresh
        return {"status": "ok"}

    script_connect(monkeypatch, client, [connect_once])

    ok = await client._reconnect()

    assert ok is False
    assert not client.login_success_event.is_set()
    assert fresh.close_count == 1
    assert client.websocket is None


async def test_notify_permanent_disconnect_swallows_callback_errors():
    client = make_client()

    def boom():
        raise RuntimeError("callback exploded")

    client.on_permanent_disconnect = boom

    client._notify_permanent_disconnect()  # must not raise


# ---------------------------------------------------------------------------
# listen_messages()
# ---------------------------------------------------------------------------


async def test_listen_skips_malformed_frames_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
):
    client = make_client()
    calls = script_connect(
        monkeypatch, client, [lambda n: {"status": "failed", "message": "must not be called"}]
    )
    received: List[dict] = []
    got = asyncio.Event()

    @client.group_event()
    async def on_group(msg):
        received.append(msg)
        got.set()

    valid = {"post_type": "message", "message_type": "group", "raw_message": "hello"}
    frames = ["not json", "null", "[1, 2]", "123", json.dumps(valid)]
    ws = FakeWebSocket(frames)
    client.websocket = ws

    listener = asyncio.create_task(client.listen_messages())
    await asyncio.wait_for(got.wait(), timeout=2)
    await client.close()
    await await_listener(listener)

    assert received == [valid]
    assert calls == []  # bad frames must not trigger a reconnect
    assert ws.close_count == 1


async def test_listen_reconnects_and_resumes_after_connection_closed(
    monkeypatch: pytest.MonkeyPatch,
):
    client = make_client()
    received: List[dict] = []
    got = asyncio.Event()

    @client.group_event()
    async def on_group(msg):
        received.append(msg)
        got.set()

    ws1 = FakeWebSocket([websockets.exceptions.ConnectionClosed(None, None)])
    ws2 = FakeWebSocket([json.dumps({"post_type": "message", "message_type": "group"})])
    client.websocket = ws1
    calls = script_connect(monkeypatch, client, [ws2])

    listener = asyncio.create_task(client.listen_messages())
    await asyncio.wait_for(got.wait(), timeout=2)
    # _reconnect() sets the login event on success; close() clears it again,
    # so assert before shutting down.
    assert client.login_success_event.is_set()
    await client.close()
    await await_listener(listener)

    assert len(received) == 1
    assert len(calls) == 1
    assert ws1.close_count == 1  # reconnect closed the old socket


async def test_listen_stops_after_exhausted_reconnect_from_within(
    monkeypatch: pytest.MonkeyPatch, fast_backoff
):
    client = make_client()
    fired = track_notify(client)
    client.MAX_RECONNECT_ATTEMPTS = 2
    script_connect(
        monkeypatch, client, [lambda n: {"status": "failed", "message": "down"}]
    )
    ws1 = FakeWebSocket([websockets.exceptions.ConnectionClosed(None, None)])
    client.websocket = ws1

    listener = asyncio.create_task(client.listen_messages())
    await asyncio.wait_for(listener, timeout=2)

    assert not listener.cancelled()
    assert client.shutdown_event.is_set()
    assert fired == [1]


# ---------------------------------------------------------------------------
# handle_message()
# ---------------------------------------------------------------------------


async def test_handle_message_resolves_echo_future():
    client = make_client()
    fut = asyncio.get_running_loop().create_future()
    client.response_futures["e1"] = fut

    await client.handle_message({"echo": "e1", "status": "ok", "data": {"x": 1}})

    assert fut.result() == {"echo": "e1", "status": "ok", "data": {"x": 1}}
    assert client.response_futures == {}


async def test_handle_message_ignores_cancelled_echo_future():
    client = make_client()
    fut = asyncio.get_running_loop().create_future()
    fut.cancel()
    client.response_futures["e2"] = fut

    await client.handle_message({"echo": "e2", "status": "ok"})

    assert client.response_futures == {}


async def test_handle_message_dispatches_events_without_blocking():
    client = make_client()
    seen: Dict[str, List[dict]] = {}
    events = {key: asyncio.Event() for key in ("group", "private", "notice", "meta", "napcat")}

    for key in ("group", "private", "notice", "meta", "napcat"):
        def make_cb(k):
            async def cb(msg):
                seen.setdefault(k, []).append(msg)
                events[k].set()

            return cb

        getattr(client, f"{key}_event")()(make_cb(key))

    payloads = {
        "group": {"post_type": "message", "message_type": "group"},
        "private": {"post_type": "message", "message_type": "private"},
        "notice": {"post_type": "notice"},
        "meta": {"post_type": "meta_event"},
        "napcat": {"status": "failed"},
    }
    for key, payload in payloads.items():
        await client.handle_message(dict(payload))
        await asyncio.wait_for(events[key].wait(), timeout=2)

    assert {k: len(v) for k, v in seen.items()} == {k: 1 for k in payloads}

    before = {k: list(v) for k, v in seen.items()}
    await client.handle_message({"post_type": "something_else"})
    await asyncio.sleep(0)
    assert seen == before  # unknown post_type dispatches nowhere


# ---------------------------------------------------------------------------
# Action helper param building
# ---------------------------------------------------------------------------


async def test_action_helpers_build_expected_params(monkeypatch: pytest.MonkeyPatch):
    client = make_client()
    mock = AsyncMock(return_value={"status": "ok"})
    monkeypatch.setattr(client, "send_action", mock)

    await client.send_poke("u1", "g1")
    mock.assert_awaited_with("send_poke", {"user_id": "u1", "group_id": "g1"})

    await client.send_poke("u2")
    mock.assert_awaited_with("send_poke", {"user_id": "u2"})

    segments = [{"type": "text", "data": {"text": "hi"}}]
    await client.send_group_segments("gid", segments)
    mock.assert_awaited_with("send_group_msg", {"group_id": "gid", "message": segments})

    await client.send_direct_segments("uid", segments)
    mock.assert_awaited_with("send_private_msg", {"user_id": "uid", "message": segments})


# ---------------------------------------------------------------------------
# run() lifecycle
# ---------------------------------------------------------------------------


async def test_run_reaches_ready_and_stays_alive_until_close(
    monkeypatch: pytest.MonkeyPatch,
):
    client = make_client()
    ws = FakeWebSocket([lifecycle_meta_frame()])
    calls = patch_ws_factory(monkeypatch, ws)

    runner = asyncio.create_task(client.run("10000", "ws://fake"))
    await wait_until(lambda: bool(ws.actions))  # get_login_info request written
    echo = ws.actions[0]["echo"]
    ws.push(json.dumps({"status": "ok", "retcode": 0, "data": {"user_id": 10000}, "echo": echo}))
    await asyncio.sleep(0.05)

    assert len(calls) == 1
    assert not runner.done()  # ready clients stay alive until closed

    await client.close()
    await asyncio.wait_for(runner, timeout=2)
    assert runner.exception() is None
    assert ws.close_count >= 1


async def test_run_exits_after_account_mismatch(monkeypatch: pytest.MonkeyPatch):
    client = make_client()
    ws = FakeWebSocket([lifecycle_meta_frame()])
    patch_ws_factory(monkeypatch, ws)

    runner = asyncio.create_task(client.run("999", "ws://fake"))
    await wait_until(lambda: bool(ws.actions))
    echo = ws.actions[0]["echo"]
    ws.push(json.dumps({"status": "ok", "retcode": 0, "data": {"user_id": 10000}, "echo": echo}))

    await asyncio.wait_for(runner, timeout=2)

    assert runner.exception() is None
    assert client.shutdown_event.is_set()


async def test_run_shuts_down_on_invalid_token_event(monkeypatch: pytest.MonkeyPatch):
    client = make_client()
    ws = FakeWebSocket([json.dumps({"status": "failed", "retcode": 1403})])
    patch_ws_factory(monkeypatch, ws)

    runner = asyncio.create_task(client.run("10000", "ws://fake"))

    with pytest.raises(ConnectionError):
        await asyncio.wait_for(runner, timeout=2)
    assert client.shutdown_event.is_set()


async def test_dispatch_event_logs_callback_exception_without_killing_dispatch(monkeypatch: pytest.MonkeyPatch):
    """A raising handler degrades to a logged error: sibling callbacks still
    see the event and no exception escapes as an unretrieved task."""

    class RecordLogger:
        def __init__(self) -> None:
            self.errors: List[str] = []

        def error(self, message: str) -> None:
            self.errors.append(str(message))

    client = make_client()
    record_logger = RecordLogger()
    monkeypatch.setattr(napcat_client, "logger", record_logger)

    seen: List[dict] = []
    good_event = asyncio.Event()

    @client.group_event()
    async def raising_handler(msg: dict) -> None:
        raise RuntimeError("boom")

    @client.group_event()
    async def working_handler(msg: dict) -> None:
        seen.append(msg)
        good_event.set()

    await client.handle_message({"post_type": "message", "message_type": "group"})
    await asyncio.wait_for(good_event.wait(), timeout=2)
    await wait_until(lambda: bool(record_logger.errors))

    assert len(seen) == 1
    assert any("boom" in err for err in record_logger.errors)
