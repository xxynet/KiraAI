import asyncio
import inspect
import json
import traceback
import uuid
import websockets
from core.logging_manager import get_logger
from typing import Any, Union, Optional, Literal, Callable
from .utils import QQMessageChain


logger = get_logger("napcat", "blue")


def _detect_headers_kwarg() -> str:
    """Detect which keyword name ``websockets.connect`` accepts for request headers.

    The new asyncio implementation renamed ``extra_headers`` to
    ``additional_headers``. Inspecting the signature is more robust than
    comparing implementations: it also works when the installed version is a
    deprecated wrapper or a future re-export.
    """
    try:
        params = inspect.signature(websockets.connect).parameters
    except (TypeError, ValueError):  # non-introspectable signature; assume the legacy name
        return "extra_headers"
    return "additional_headers" if "additional_headers" in params else "extra_headers"


_HEADERS_KWARG = _detect_headers_kwarg()


def ws_compatible_connect(uri, *, extra_headers, **kwargs):
    """Connect while staying compatible with both old and new websockets versions.

    Callers always pass headers as ``extra_headers``; it is forwarded under the
    parameter name that the installed websockets version actually accepts.
    """
    kwargs[_HEADERS_KWARG] = extra_headers
    return websockets.connect(uri, **kwargs)


class NapCatWebSocketClient:
    # Reconnect policy: maximum attempts and per-attempt backoff cap (seconds)
    MAX_RECONNECT_ATTEMPTS = 20
    MAX_RECONNECT_BACKOFF = 60

    def __init__(self, ws_url: str = "ws://localhost:3001", access_token: Optional[str] = None) -> None:
        self.ws_url = ws_url
        self.access_token = access_token
        self.self_id = None
        self.websocket = None
        self.response_futures: dict[str, asyncio.Future] = {}
        self.shutdown_event = asyncio.Event()
        self.last_heartbeat: Optional[int] = None
        self.login_success_event: asyncio.Event = asyncio.Event()
        self._listening_task: Optional[asyncio.Task] = None
        # 重连耗尽回调：宿主注册后可在连接永久失败时感知（发布事件/
        # 状态标记），原实现只 log、宿主与用户均无从得知
        self.on_permanent_disconnect: Optional[Callable[[], None]] = None
        self.event_callbacks: dict[str, list[Callable]] = {
            "group": [],
            "private": [],
            "notice": [],
            "napcat": [],
            "meta": []
        }

    async def run(self, bt_uin: str, ws_uri: str, ws_token: Optional[str] = None, ws_listen_ip: str = "0.0.0.0") -> None:
        self.self_id = bt_uin
        self.ws_url = ws_uri
        self.access_token = ws_token

        @self.meta_event()
        async def on_meta_message(msg: dict) -> None:
            if msg.get("meta_event_type") == "lifecycle":
                self.login_success_event.set()

        @self.napcat_event()
        async def on_napcat_message(msg: dict) -> None:
            if msg.get("status", "") == "failed":
                if msg.get("retcode") == 1403:
                    logger.error("WebSocket 服务器 Token 无效")
                    await self.close()

        con_resp = await self.connect()
        if con_resp.get("status") != "ok":
            # Entering reconnect on the first connect failure is intentional, but that
            # retry loop runs inline: run() does not return until it is over, so the
            # log has to make that explicit instead of looking like a stuck startup.
            logger.warning(
                f"初次连接失败：{con_resp.get('message')}，进入重连"
                f"（最多 {self.MAX_RECONNECT_ATTEMPTS} 次退避重试，"
                f"期间 run() 不会返回）"
            )
            if not await self._reconnect():      # 耗尽时内部已上报
                return

        self._listening_task = asyncio.create_task(self.listen_messages())

        login_info = await self.get_login_info()
        login_id = login_info.get("data", {}).get("user_id")
        if str(login_id) != str(bt_uin):
            logger.error("配置的账号与 NapCat 登录账号不一致")
            await self.close()
            return

        logger.info(f"等待账号 {bt_uin} 的登录成功事件")
        try:
            await asyncio.wait_for(self.login_success_event.wait(), timeout=5)
            logger.info(f"账号 {bt_uin} 登录成功")
        except asyncio.TimeoutError:
            logger.error(f"账号 {bt_uin} 登录超时")
            await self.close()
            return

        # run() must stay alive until the listening task ends: returning the task
        # object instead leaves it un-awaited, so its exceptions only surface as
        # "Task exception was never retrieved" during GC, invisible to the host.
        # asyncio.wait instead of a bare await: an external close() cancels the
        # listening task, and awaiting it directly would raise CancelledError into
        # whoever awaited run().
        await asyncio.wait({self._listening_task})
        if self._listening_task.done() and not self._listening_task.cancelled():
            exc = self._listening_task.exception()
            if exc is not None:
                logger.error(f"监听任务异常结束: {exc}")

    async def connect(self) -> dict[str, str]:
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        logger.info(f"连接到 {self.ws_url}")
        try:
            self.websocket = await ws_compatible_connect(self.ws_url, extra_headers=headers, max_size=2**24, open_timeout=5.0, ping_timeout=10.0)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "failed", "message": str(e)}

    async def _reconnect(self) -> bool:
        attempt = 0
        while not self.shutdown_event.is_set() and attempt < self.MAX_RECONNECT_ATTEMPTS:
            attempt += 1
            logger.warning(
                f"🔄 WebSocket 连接断开，正在尝试第 {attempt}/{self.MAX_RECONNECT_ATTEMPTS} 次重连"
            )
            ws, self.websocket = self.websocket, None
            if ws is not None:
                try:
                    await ws.close()
                except Exception:
                    pass
            resp = await self.connect()
            if resp.get("status") == "ok":
                if self.shutdown_event.is_set():
                    # close() raced with this reconnect: discard the fresh socket
                    # instead of leaving a half-alive connection that nobody
                    # reads from, and do not fake a successful login.
                    ws, self.websocket = self.websocket, None
                    if ws is not None:
                        try:
                            await ws.close()
                        except Exception:
                            pass
                    return False
                logger.info("✅ WebSocket 重连成功")
                self.login_success_event.set()
                return True
            elif resp.get("status") == "failed":
                logger.warning(f"WebSocket 重连失败: {resp.get('message')}")
            # No backoff after the final attempt, otherwise reporting a permanent
            # failure would still wait out one more full backoff period.
            if attempt < self.MAX_RECONNECT_ATTEMPTS:
                await asyncio.sleep(min(2 ** attempt, self.MAX_RECONNECT_BACKOFF))
        if attempt >= self.MAX_RECONNECT_ATTEMPTS and not self.shutdown_event.is_set():
            self._notify_permanent_disconnect()
        return False

    def _notify_permanent_disconnect(self) -> None:
        """重连耗尽上报"""
        logger.error("❌ WebSocket 重连次数达到上限，连接永久失败！")
        if self.on_permanent_disconnect:
            try:
                self.on_permanent_disconnect()
            except Exception as e:
                logger.error(f"重连耗尽回调异常: {e}")

    def group_event(self) -> Callable[..., Any]:
        def wrapper(func):
            self.event_callbacks["group"].append(func)
            return func
        return wrapper

    def private_event(self) -> Callable[..., Any]:
        def wrapper(func):
            self.event_callbacks["private"].append(func)
            return func
        return wrapper

    def notice_event(self) -> Callable[..., Any]:
        def wrapper(func):
            self.event_callbacks["notice"].append(func)
            return func
        return wrapper

    def napcat_event(self) -> Callable[..., Any]:
        def wrapper(func):
            self.event_callbacks["napcat"].append(func)
            return func
        return wrapper

    def meta_event(self) -> Callable[..., Any]:
        def wrapper(func):
            self.event_callbacks["meta"].append(func)
            return func
        return wrapper

    async def listen_messages(self) -> None:
        """唯一的消息接收入口"""
        logger.info(f"🎧 开始监听账号 {self.self_id} 的消息...")
        while not self.shutdown_event.is_set():
            try:
                if self.websocket is None:
                    logger.error("监听循环内 websocket 为空，退出监听")
                    break
                async for message in self.websocket:
                    try:
                        data = json.loads(message)
                        if not isinstance(data, dict):
                            # `null` / arrays / bare scalars are valid JSON but carry no
                            # OneBot payload, and handle_message() assumes a mapping
                            logger.error(f"❌ 忽略非对象消息: {message}")
                            continue
                        await self.handle_message(data)
                    except json.JSONDecodeError:
                        logger.error(f"❌ 无法解析消息: {message}")
                    except Exception as e:
                        # A malformed payload must not tear down a healthy connection:
                        # log it, drop that message, keep listening. Only iterator and
                        # connection failures below are worth a reconnect.
                        logger.error(f"❌ 处理消息失败，已跳过该消息: {e}")
            except websockets.exceptions.ConnectionClosed:
                logger.warning("🔌 WebSocket 连接已关闭")
                success = await self._reconnect()
                if not success and not self.shutdown_event.is_set():
                    logger.error("❌ 重连次数达到上限，WebSocket 重连失败！")
                    await self.close()
                    break
                continue
            except Exception as e:
                # Iterator / connection-level failure (individual messages are handled
                # inside the loop above), so a reconnect is the right response.
                logger.error(f"❌ 监听错误: {e}，尝试重连")
                if not await self._reconnect():
                    await self.close()
                    break
                continue

    def _dispatch_event(self, callback: Callable, data: dict) -> None:
        """Dispatch one event callback as a background task.

        An exception escaping the callback would otherwise surface only as an
        unretrieved-task traceback at garbage collection; catch it here so a
        failing handler degrades to one readable error log while the
        connection and the receive loop keep running.
        """

        async def runner():
            try:
                await callback(data)
            except Exception:
                logger.error(f"事件回调处理失败，已跳过该事件:\n{traceback.format_exc()}")

        asyncio.create_task(runner())

    async def handle_message(self, data: dict) -> None:
        """处理收到的消息"""

        # Check if this is an API response - must be handled synchronously
        # to ensure response futures are set before event callbacks execute
        echo = data.get("echo")
        if echo and echo in self.response_futures:
            future = self.response_futures.pop(echo)
            if not future.cancelled():
                future.set_result(data)
            return

        # Handle event messages - use create_task to avoid blocking message reception
        # This allows API response messages to be received even when event callbacks are executing
        if "post_type" in data:
            post_type = data.get("post_type")
            if post_type == "message":
                message_type = data.get('message_type')
                if message_type == "group":
                    if self.event_callbacks["group"]:
                        # Create task to run event callback non-blockingly
                        # This ensures listen_messages can continue receiving messages
                        for func in self.event_callbacks["group"]:
                            self._dispatch_event(func, data)
                elif message_type == "private":
                    if self.event_callbacks["private"]:
                        for func in self.event_callbacks["private"]:
                            self._dispatch_event(func, data)
            elif post_type == "notice":
                if self.event_callbacks["notice"]:
                    for func in self.event_callbacks["notice"]:
                        self._dispatch_event(func, data)
            elif post_type == "meta_event":
                if self.event_callbacks["meta"]:
                    for func in self.event_callbacks["meta"]:
                        self._dispatch_event(func, data)
                # if data.get("meta_event_type") == "heartbeat":
                #     if not self.last_heartbeat:
                #         self.last_heartbeat = data.get('time')
                #     else:
                #         cur_heartbeat = data.get('time')
                #         print(f"heartbeat间隔：{cur_heartbeat - self.last_heartbeat}")
                #         self.last_heartbeat = cur_heartbeat
                #     print(f"   💓 心跳事件 (间隔: {data.get('interval')}ms)")
                # elif data.get("meta_event_type") == "lifecycle":
                #     print("启动成功")
                else:
                    pass
                    # print(f"   元事件: {json.dumps(data, ensure_ascii=False, indent=2)}")
            else:
                pass
                # print(f"   完整数据: {json.dumps(data, ensure_ascii=False, indent=2)}")
            return

        # Other messages
        # print(f"❓ [{timestamp}] 未知消息:")
        # print(f"   {json.dumps(data, ensure_ascii=False, indent=2)}")

        if self.event_callbacks["napcat"]:
            for func in self.event_callbacks["napcat"]:
                self._dispatch_event(func, data)

    async def send_group_message(self, group_id: str, msg: QQMessageChain):
        return await self.send_group_segments(group_id=group_id, message=msg.to_list())

    async def send_group_segments(self, group_id: Union[str, int], message: list[dict]):
        """Send a pre-built OneBot message segment list to a group."""
        message_dict = {
            "group_id": group_id,
            "message": message
        }
        return await self.send_action("send_group_msg", message_dict)

    async def send_direct_message(self, user_id: str, msg: QQMessageChain):
        return await self.send_direct_segments(user_id=user_id, message=msg.to_list())

    async def send_direct_segments(self, user_id: Union[str, int], message: list[dict]):
        """Send a pre-built OneBot message segment list to a private chat."""
        message_dict = {
            "user_id": user_id,
            "message": message
        }
        return await self.send_action("send_private_msg", message_dict)

    async def send_poke(self, user_id: Union[str, int], group_id: Union[str, int, None] = None):
        if group_id:
            message_dict = {
                "user_id": user_id,
                "group_id": group_id
            }
        else:
            message_dict = {
                "user_id": user_id
            }
        resp = await self.send_action("send_poke", message_dict)
        return resp

    async def get_record(self, file_id, output_format: Literal['mp3', 'amr', 'wma', 'm4a', 'spx', 'ogg', 'wav', 'flac'] = "mp3"):
        message_dict = {
            "file_id": file_id,
            "out_format": output_format
        }
        resp = await self.send_action("get_record", message_dict)
        return resp

    async def get_user_info(self, user_id: Union[str, int]):
        message_dict = {
            "user_id": user_id
        }
        resp = await self.send_action("get_stranger_info", message_dict)
        return resp

    async def get_group_info(self, group_id: Union[str, int]):
        message_dict = {
            "group_id": group_id
        }
        resp = await self.send_action("get_group_info", message_dict)
        return resp

    async def get_msg(self, message_id: Union[str, int]):
        message_dict = {
            "message_id": message_id
        }
        resp = await self.send_action("get_msg", message_dict)
        return resp

    async def get_forward_msg(self, message_id: Union[str, int]):
        message_dict = {
            "message_id": message_id
        }
        resp = await self.send_action("get_forward_msg", message_dict)
        return resp

    async def forward_group_single_message(self, group_id: Union[str, int], message_id: Union[str, int]):
        """Forward one existing message to a group."""
        return await self.send_action("forward_group_single_msg", {
            "message_id": message_id,
            "group_id": group_id,
        })

    async def forward_direct_single_message(self, user_id: Union[str, int], message_id: Union[str, int]):
        """Forward one existing message to a private chat."""
        return await self.send_action("forward_friend_single_msg", {
            "message_id": message_id,
            "user_id": user_id,
        })

    async def get_group_file_url(self, group_id: Union[str, int], file_id: str):
        """Get the downloadable URL for a group file."""
        return await self.send_action("get_group_file_url", {
            "group_id": group_id,
            "file_id": file_id,
        })

    async def get_private_file_url(self, file_id: str):
        """Get the downloadable URL for a private file."""
        return await self.send_action("get_private_file_url", {"file_id": file_id})

    async def upload_private_file(self, user_id: str, file: str, name: str):
        message_dict = {
            "user_id": user_id,
            "file": file,
            "name": name
        }
        resp = await self.send_action("upload_private_file", message_dict)
        return resp

    async def upload_group_file(self, group_id: str, file: str, name: str):
        message_dict = {
            "group_id": group_id,
            "file": file,
            "name": name
        }
        resp = await self.send_action("upload_group_file", message_dict)
        return resp

    async def send_action(self, action: str, params: dict, timeout: float = 10.0) -> dict:
        """发送API请求并等待响应"""
        # Fail before the wait, not after it: an exhausted reconnect leaves
        # self.websocket as None with neither event set, and the socket check further
        # down would only be reached after burning the full 10s wait.
        if self.websocket is None:
            raise ConnectionError(f"NapCat WebSocket 未连接，无法执行 {action}")

        # Wait for shutdown_event as well: close() only clears login_success_event,
        # which does not wake a caller already blocked in wait(). No response_futures
        # entry exists yet on this path either, so close() cannot fail the call, and
        # waiting for the login event alone burns the full 10s before raising
        # TimeoutError.
        login_wait = asyncio.create_task(self.login_success_event.wait())
        shutdown_wait = asyncio.create_task(self.shutdown_event.wait())
        try:
            done, _ = await asyncio.wait(
                {login_wait, shutdown_wait},
                timeout=10,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            login_wait.cancel()
            shutdown_wait.cancel()
        if shutdown_wait in done:
            raise ConnectionError("NapCat 连接已关闭")
        if not done:
            logger.error("send_action 失败： 登录成功事件未触发")
            raise asyncio.TimeoutError("等待登录成功事件超时")

        echo = str(uuid.uuid4())

        # 创建Future来等待响应
        future = asyncio.Future()
        self.response_futures[echo] = future

        message = {
            "action": action.replace("/", ""),
            "params": params,
            "echo": echo
        }

        try:
            if self.websocket is None:
                raise ConnectionError(f"NapCat WebSocket 未连接，无法执行 {action}")
            await self.websocket.send(json.dumps(message))
            # print(f"📤 发送请求: {action} (echo: {echo})")

            # 等待响应（不调用recv，由监听任务处理）
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            # Discard the pending Future entry; do not await it (awaiting a Future
            # here would raise CancelledError and mask the intended TimeoutError).
            self.response_futures.pop(echo, None)
            raise TimeoutError(f"请求 {action} 超时")
        except Exception:
            # Same as above: just drop the entry without awaiting it.
            self.response_futures.pop(echo, None)
            raise

    async def get_login_info(self):
        """获取登录信息"""
        response = await self.send_action("get_login_info", {})
        return response

    async def close(self) -> None:
        self.shutdown_event.set()
        self.login_success_event.clear()
        # fail 挂起请求：等待响应的调用方立即收到明确异常，
        # 而非各自耗尽 wait_for 超时
        for future in self.response_futures.values():
            if not future.done():
                future.set_exception(ConnectionError("NapCat 连接已关闭"))
        self.response_futures.clear()
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        # On a reconnect failure, listen_messages calls close() from within
        # _listening_task itself: a task must not cancel and then await itself,
        # and it must not swallow its own cancellation signal either.
        current = asyncio.current_task()
        if (
            self._listening_task is not None
            and self._listening_task is not current
            and not self._listening_task.done()
        ):
            self._listening_task.cancel()
            try:
                await self._listening_task  # 等待任务被取消
            except asyncio.CancelledError:
                logger.info(f"已停止监听账号 {self.self_id} 的消息")
                return
            except Exception as e:
                logger.error(f"取消监听消息任务时发生错误: {e}")
                return
        logger.info(f"已停止监听账号 {self.self_id} 的消息")
