import asyncio

from core.plugin import BasePlugin, logger, on, Priority
from core.chat.message_utils import KiraMessageEvent, KiraMessageBatchEvent, KiraIMMessage
from core.chat.message_elements import Text


class DebouncePlugin(BasePlugin):
    def __init__(self, ctx, cfg: dict):
        super().__init__(ctx, cfg)
        self.session_events: dict[str, asyncio.Event] = {}
        self.session_tasks: dict[str, asyncio.Task] = {}
        bot_cfg = ctx.config["bot_config"].get("bot", {})
        self.debounce_interval = float(bot_cfg.get("max_message_interval", 1.5))
        self.max_buffer_messages = int(bot_cfg.get("max_buffer_messages", 3))

        self.waking_words = cfg.get("waking_words", [])
    
    async def initialize(self):
        logger.info(f"[Debounce] enabled")
    
    async def terminate(self):
        """
        Cleanup when plugin is terminated
        """
        pass

    @on.im_message(priority=Priority.HIGH)
    async def handle_msg(self, event: KiraMessageEvent):

        # === Check waking words ===
        for m in event.message.chain:
            if isinstance(m, Text) and any(w in m.text for w in self.waking_words):
                event.message.is_mentioned = True
                break

        # Ignore unmentioned messages
        if not event.is_mentioned:
            event.stop()
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
            try:
                await self.ctx.message_processor.flush_session_messages(sid)
            except Exception:
                logger.exception(f"[Debounce] Error flushing session {sid}")

    @on.im_batch_message(priority=Priority.MEDIUM)
    async def handle_batch_event(self, event: KiraMessageBatchEvent):
        pass
