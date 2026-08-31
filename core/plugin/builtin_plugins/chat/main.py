import asyncio
import random

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent
from core.provider import LLMRequest
from core.chat.message_elements import Text


class DefaultChatPlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.session_events: dict[str, asyncio.Event] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        self._terminating = False
        bot_cfg = ctx.config["bot_config"].get("bot", {})
        self.debounce_interval = float(bot_cfg.get("max_message_interval", 1.5))
        self.max_buffer_messages = int(bot_cfg.get("max_buffer_messages", 3))
        self.max_unmentioned_messages = int(self.plugin_cfg.get("max_unmentioned_messages", 5))
        self.receive_unmentioned = self.plugin_cfg.get("receive_unmentioned", True)
        self.group_chat_prompt = self.plugin_cfg.get("group_chat_prompt", "")
        self.group_proactive_chat = self.plugin_cfg.get("group_proactive_chat", False)
        self.group_proactive_chat_probability = self.plugin_cfg.get("group_proactive_chat_probability", 0.1)

        self.waking_words = cfg.get("waking_words", [])
    
    async def initialize(self):
        self._terminating = False
        logger.info(f"[Default Chat] initialize")
    
    async def terminate(self):
        """Cancel all pending debounce tasks before the plugin is unloaded."""
        self._terminating = True
        tasks = list(self.session_tasks.values())
        self.session_tasks.clear()
        self.session_events.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    @on.im_message(priority=Priority.HIGH)
    async def handle_msg(self, event: KiraMessageEvent):

        # === Check waking words ===
        for m in event.message.chain:
            if isinstance(m, Text) and any(w in m.text for w in self.waking_words):
                event.message.is_mentioned = True
                break

        # Ignore unmentioned messages
        if not event.is_mentioned:
            if self.receive_unmentioned:
                buffer = self.ctx.get_buffer(str(event.session))
                if buffer.get_length() >= self.max_unmentioned_messages:
                    buffer.pop(count=buffer.get_length()-self.max_unmentioned_messages+1)
                event.buffer()
                if self.group_proactive_chat:
                    if random.random() < self.group_proactive_chat_probability:
                        logger.info("[Chat] Triggered proactive chat")
                        event.flush()
            else:
                event.discard()
            return

        sid = event.session.sid
        event.buffer()

        buffer_len = self.ctx.message_processor.get_session_buffer_length(sid)
        if buffer_len + 1 >= self.max_buffer_messages:
            event.flush()
            return

        if sid not in self.session_events:
            self.session_events[sid] = asyncio.Event()
        if sid not in self.session_tasks:
            self.session_tasks[sid] = asyncio.create_task(
                self._debounce_loop(sid, self.session_events[sid]),
                name=f"chat_debounce_{sid}",
            )
        self.session_events[sid].set()

    async def _debounce_loop(self, sid: str, event: asyncio.Event):
        try:
            while True:
                await event.wait()
                event.clear()
                await asyncio.sleep(self.debounce_interval)
                if event.is_set() and not self.receive_unmentioned:
                    continue
                buffer_len = self.ctx.message_processor.get_session_buffer_length(sid)
                if buffer_len == 0:
                    return
                try:
                    await self.ctx.message_processor.flush_session_messages(sid)
                except Exception:
                    logger.exception(f"[Debounce] Error flushing session {sid}")
                return
        except asyncio.CancelledError:
            raise
        finally:
            current_task = asyncio.current_task()
            if self.session_tasks.get(sid) is not current_task:
                return
            self.session_tasks.pop(sid, None)
            if event.is_set() and not self._terminating:
                self.session_tasks[sid] = asyncio.create_task(
                    self._debounce_loop(sid, event),
                    name=f"chat_debounce_{sid}",
                )
            else:
                self.session_events.pop(sid, None)

    @on.llm_request(priority=Priority.MEDIUM)
    async def inject_group_prompt(self, event: KiraMessageBatchEvent, req: LLMRequest, *_):
        if not event.is_group_message():
            return
        if self.group_chat_prompt:
            for p in req.system_prompt:
                if p.name == "chat_env":
                    p.content += self.group_chat_prompt
                    break
