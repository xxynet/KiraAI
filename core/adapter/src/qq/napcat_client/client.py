import asyncio
import json
import uuid
import traceback
import websockets
from datetime import datetime
from core.logging_manager import get_logger
from typing import Union, Optional, Literal, Callable
from .utils import QQMessageChain


logger = get_logger("napcat", "blue")


def ws_compatible_connect(uri, *, extra_headers, **kwargs):
    """
    使用自定义的 connect 函数来同时兼容新版和旧版 websockets

    默认使用旧版参数名 ``extra_headers``
    """
    return websockets.connect(
        uri,
        extra_headers=extra_headers,
        **kwargs
    )


try:
    import websockets.asyncio.client

    if websockets.connect == websockets.asyncio.client.connect:
        def ws_compatible_connect(uri, *, extra_headers, **kwargs):
            """
            如果 ``websockets.connect`` 对应新版 ``asyncio`` 实现，需要把参数名 ``extra_headers`` 改为 ``additional_headers``
            """
            return websockets.connect(
                uri,
                additional_headers=extra_headers,
                **kwargs
            )
except ImportError:
    pass


class NapCatWebSocketClient:
    def __init__(self, ws_url: str = "ws://localhost:3001", access_token: Optional[str] = None):
        self.ws_url = ws_url
        self.access_token = access_token
        self.self_id = None
        self.websocket = None
        self.response_futures: dict[str, asyncio.Future] = {}
        self.shutdown_event = asyncio.Event()
        self.last_heartbeat: Optional[int] = None
        self.login_success_event: asyncio.Event = asyncio.Event()
        self._listening_task: Optional[asyncio.Task] = None
        self.event_callbacks: dict[str, list[Callable]] = {
            "group": [],
            "private": [],
            "notice": [],
            "napcat": [],
            "meta": []
        }

    async def run(self, bt_uin: str, ws_uri: str, ws_token: Optional[str] = None, ws_listen_ip: str = "0.0.0.0"):
        self.self_id = bt_uin
        self.ws_url = ws_uri
        self.access_token = ws_token

        @self.meta_event()
        async def on_meta_message(msg: dict):
            if msg.get("meta_event_type") == "lifecycle":
                self.login_success_event.set()

        @self.napcat_event()
        async def on_napcat_message(msg: dict):
            if msg.get("status", "") == "failed":
                if msg.get("retcode") == 1403:
                    logger.error("invalid token")
                    await self.close()

        con_resp = await self.connect()
        if con_resp.get("status") == "ok":
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
                if self._listening_task and not self._listening_task.done():
                    self._listening_task.cancel()
                    try:
                        await self._listening_task  # 等待任务被取消
                    except asyncio.CancelledError:
                        logger.info("监听消息任务已取消")
                    except Exception as e:
                        logger.error(f"取消任务时发生错误: {e}")
                return

            await self._listening_task
        elif con_resp.get("status") == "failed":
            logger.error(f"连接失败：{con_resp.get('message')}")
            return

    async def connect(self):
        headers = {}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"

        logger.info(f"连接到 {self.ws_url}")
        try:
            self.websocket = await ws_compatible_connect(self.ws_url, extra_headers=headers, max_size=2**24, open_timeout=5.0, ping_timeout=10.0)
            return {"status": "ok"}
        except Exception as e:
            return {"status": "failed", "message": str(e)}

    def group_event(self):
        def wrapper(func):
            self.event_callbacks["group"].append(func)
            return func
        return wrapper

    def private_event(self):
        def wrapper(func):
            self.event_callbacks["private"].append(func)
            return func
        return wrapper

    def notice_event(self):
        def wrapper(func):
            self.event_callbacks["notice"].append(func)
            return func
        return wrapper

    def napcat_event(self):
        def wrapper(func):
            self.event_callbacks["napcat"].append(func)
            return func
        return wrapper

    def meta_event(self):
        def wrapper(func):
            self.event_callbacks["meta"].append(func)
            return func
        return wrapper

    async def listen_messages(self):
        """唯一的消息接收入口"""
        logger.info(f"🎧 开始监听账号 {self.self_id} 的消息...")
        try:
            while not self.shutdown_event.is_set():
                async for message in self.websocket:
                    try:
                        data = json.loads(message)
                        await self.handle_message(data)
                    except json.JSONDecodeError:
                        logger.error(f"❌ 无法解析消息: {message}")
        except websockets.exceptions.ConnectionClosed:
            logger.warning("🔌 WebSocket 连接已关闭")
        except Exception as e:
            logger.error(f"❌ 监听错误: {e}")

    async def handle_message(self, data: dict):
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
                            asyncio.create_task(func(data))
                elif message_type == "private":
                    if self.event_callbacks["private"]:
                        for func in self.event_callbacks["private"]:
                            asyncio.create_task(func(data))
            elif post_type == "notice":
                if self.event_callbacks["notice"]:
                    for func in self.event_callbacks["notice"]:
                        asyncio.create_task(func(data))
            elif post_type == "meta_event":
                if self.event_callbacks["meta"]:
                    for func in self.event_callbacks["meta"]:
                        asyncio.create_task(func(data))
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
                asyncio.create_task(func(data))

    async def send_group_message(self, group_id: str, msg: QQMessageChain):
        message_dict = {
            "group_id": group_id,
            "message": msg.to_list()
        }
        resp = await self.send_action("send_group_msg", message_dict)
        return resp

    async def send_direct_message(self, user_id: str, msg: QQMessageChain):
        message_dict = {
            "user_id": user_id,
            "message": msg.to_list()
        }
        resp = await self.send_action("send_private_msg", message_dict)
        return resp

    async def send_poke(self, user_id: Union[str, int], group_id: Union[str, int] = None):
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
            await self.websocket.send(json.dumps(message))
            # print(f"📤 发送请求: {action} (echo: {echo})")

            # 等待响应（不调用recv，由监听任务处理）
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            await self.response_futures.pop(echo, None)
            raise TimeoutError(f"请求 {action} 超时")
        except Exception:
            await self.response_futures.pop(echo, None)
            raise

    async def get_login_info(self):
        """获取登录信息"""
        response = await self.send_action("get_login_info", {})
        return response

    async def close(self):
        self.shutdown_event.set()
        self.login_success_event.clear()
        if self.websocket:
            await self.websocket.close()
        if self._listening_task and not self._listening_task.done():
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
