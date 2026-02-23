import json
import asyncio
from pathlib import Path
from typing import Union, Optional
from datetime import datetime

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraIMMessage

from core.prompt_manager import Prompt

from core.utils.tool_utils import BaseTool


class DefaultPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.session_events: dict[str, asyncio.Event] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        bot_cfg = ctx.config["bot_config"].get("bot", {})
        self.debounce_interval = float(bot_cfg.get("max_message_interval", 1.5))
        self.max_buffer_messages = int(bot_cfg.get("max_buffer_messages", 3))
    
    async def initialize(self):
        logger.info(f"[Default Plugin]")
    
    async def terminate(self):
        """
        Cleanup when plugin is terminated
        """
        pass

    @staticmethod
    def _get_current_time_str() -> str:
        now = datetime.now()
        return now.strftime("%b %d %Y %H:%M %a")

    def _format_user_message(self, msg: Union[KiraIMMessage]) -> str:
        """格式化用户消息"""
        date_str = self._get_current_time_str()
        # TODO format it in message processor
        if isinstance(msg, KiraIMMessage):
            if msg.is_group_message():
                # group message format
                return f"[{date_str}] [message_id: {str(msg.message_id)}] [group_name: {msg.group.group_name} group_id: {msg.group.group_id} user_nickname: {msg.sender.nickname}, user_id: {msg.sender.user_id}] | {msg.message_str}"
            else:
                # direct message format
                return f"[{date_str}] [message_id: {str(msg.message_id)}] [user_nickname: {msg.sender.nickname}, user_id: {msg.sender.user_id}] | {msg.message_str}"
        else:
            return ""

    @on.im_message(priority=Priority.HIGH)
    async def handle_msg(self, event: KiraMessageEvent):
        sid = event.session.sid
        event.buffer()

        buffer_len = self.ctx.message_processor.get_session_buffer_length(sid)
        if buffer_len + 1 >= self.max_buffer_messages:
            event.flush()
            return

        if sid not in self.session_events:
            self.session_events[sid] = asyncio.Event()
        if sid not in self.session_tasks:
            self.session_tasks[sid] = asyncio.create_task(self._debounce_loop(sid))
        self.session_events[sid].set()

    async def _debounce_loop(self, sid: str):
        event = self.session_events[sid]
        while True:
            await event.wait()
            event.clear()
            try:
                await asyncio.sleep(self.debounce_interval)
            except asyncio.CancelledError:
                break
            if event.is_set():
                continue
            buffer_len = self.ctx.message_processor.get_session_buffer_length(sid)
            if buffer_len == 0:
                continue
            await self.ctx.message_processor.flush_session_messages(sid)

    @on.im_batch_message(priority=Priority.MEDIUM)
    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        for message in event.messages:
            formatted_message = self._format_user_message(message)
            message_prompt = Prompt(
                name=f"message",
                source="system",
                content=formatted_message
            )
            event.prompt.append(message_prompt)

